"""Pruebas reales de SQL Server: todas las filas creadas se revierten."""

import sys
from pathlib import Path as _RutaProyecto
_RAIZ_PROYECTO = _RutaProyecto(__file__).resolve().parents[1]
if str(_RAIZ_PROYECTO) not in sys.path:
    sys.path.insert(0, str(_RAIZ_PROYECTO))

import unittest
from unittest.mock import patch
from decimal import Decimal
from datetime import date,timedelta
import uuid
from core.database import conectar
from inventory import inventario_service as inv
from inventory import movimientos as mov
from inventory import conteo_inventario as conteo
from inventory import productos
from inventory import alertas
from ai.prediction import prediccion_stock
from inventory import lotes_service

class ConexionPrueba:
    def __init__(self,c,nombre): self.c=c; self.nombre=nombre; c.cursor().execute('SAVE TRANSACTION '+nombre)
    def cursor(self): return self.c.cursor()
    def commit(self): pass
    def rollback(self): self.c.cursor().execute('ROLLBACK TRANSACTION '+self.nombre)
    def close(self): pass

class InventarioSQL(unittest.TestCase):
    def setUp(self):
        self.c=conectar(); self.c.cursor().execute('BEGIN TRANSACTION')
        self.numero=0; self.prefijo='T'+uuid.uuid4().hex[:12]
        def conectar_prueba():
            self.numero+=1; return ConexionPrueba(self.c,'prueba'+str(self.numero))
        self.addCleanup(self.c.close)
        self.addCleanup(self.c.rollback)
        self.patches=[patch.object(m,'conectar',side_effect=conectar_prueba) for m in (inv,mov,productos,alertas,prediccion_stock)]
        for p in self.patches: p.start(); self.addCleanup(p.stop)
        q=self.c.cursor()
        self.cat=q.execute('INSERT categorias(nombre,estado,fecha_creacion) OUTPUT INSERTED.id_categoria VALUES(?,1,SYSDATETIME())',self.prefijo).fetchone()[0]
        self.unidad=inv.guardar_unidad(self.prefijo,'t')
        self.emp=q.execute('INSERT empleados(codigo_empleado,nombres,apellidos,estado,fecha_creacion) OUTPUT INSERTED.id_empleado VALUES(?,?,?,1,SYSDATETIME())',self.prefijo,'Temporal','Prueba').fetchone()[0]
        self.a=q.execute('INSERT ubicaciones(codigo_ubicacion,seccion,estado,fecha_creacion) OUTPUT INSERTED.id_ubicacion VALUES(?,?,1,SYSDATETIME())',self.prefijo+'A','Prueba').fetchone()[0]
        self.b=q.execute('INSERT ubicaciones(codigo_ubicacion,seccion,estado,fecha_creacion) OUTPUT INSERTED.id_ubicacion VALUES(?,?,1,SYSDATETIME())',self.prefijo+'B','Prueba').fetchone()[0]
        self.p=inv.guardar_producto(self.prefijo,'Tornillo 1/2 temporal','Descripción de prueba',self.cat,self.unidad,'2.50','10')
    def saldo(self,u=None):
        if u: return mov._saldo(self.c.cursor(),self.p,u)
        return inv.consultar('SELECT stock_actual FROM vw_stock_producto WHERE id_producto=?',self.p)[0]['stock_actual']
    def entrada(self,cantidad='100',**opciones): return mov.registrar_entrada(self.emp,self.p,self.a,cantidad,**opciones)
    def lotes(self):
        self.c.cursor().execute('UPDATE productos SET control_lotes=1 WHERE id_producto=?',self.p)
        self.entrada('10',codigo_lote='L1',fecha_vencimiento=(date.today()+timedelta(days=7)).isoformat())
        return inv.listar_lotes(self.p)[0]['id_lote']

    def test_01_categoria_unidad_producto(self):
        p=inv.obtener_ficha(self.p); self.assertEqual(p['categoria'],self.prefijo); self.assertEqual(p['id_unidad_medida'],self.unidad)
    def test_02_entrada_salida_transferencia_100_20_30(self):
        self.entrada(); mov.registrar_salida(self.emp,self.p,self.a,20); mov.registrar_transferencia(self.emp,self.p,self.a,self.b,30)
        self.assertEqual(self.saldo(self.a),50); self.assertEqual(self.saldo(self.b),30); self.assertEqual(self.saldo(),80)
    def test_03_decimales_sin_truncar(self):
        self.entrada('2.500'); mov.registrar_salida(self.emp,self.p,self.a,'.750'); self.assertEqual(self.saldo(),Decimal('1.750'))
    def test_04_stock_insuficiente_sin_movimiento_parcial(self):
        self.entrada(30)
        with self.assertRaisesRegex(ValueError,'Disponible: 30'): mov.registrar_salida(self.emp,self.p,self.a,50)
        self.assertEqual(self.saldo(),30); self.assertEqual(len(mov.buscar_movimientos(id_producto=self.p)),1)
    def test_05_alerta_stock_y_resolucion(self):
        self.entrada(5); self.entrada(1)
        activas=inv.consultar('SELECT id_alerta FROM alertas WHERE id_producto=? AND atendida=0',self.p)
        self.assertEqual(len(activas),1)
        self.entrada(100); self.assertFalse(inv.consultar('SELECT id_alerta FROM alertas WHERE id_producto=? AND atendida=0',self.p))
    def test_06_agotado_critico_bajo_normal(self):
        self.assertEqual(inv.estado_stock(0,10),'AGOTADO'); self.assertEqual(inv.estado_stock(5,10),'CRÍTICO')
        self.assertEqual(inv.estado_stock(7,10),'BAJO'); self.assertEqual(inv.estado_stock(11,10),'NORMAL')
    def test_07_ajuste_registra_diferencia(self):
        self.entrada(25); mov.registrar_ajuste(self.emp,self.p,self.a,23,'Conteo físico')
        self.assertEqual(self.saldo(),23); m=mov.buscar_movimientos(id_producto=self.p)[0]
        self.assertEqual(m['tipo_movimiento'],'Ajuste salida'); self.assertEqual(m['cantidad'],2)
    def test_08_conteo_fisico(self):
        self.entrada(100); filas=conteo.listar_conteo_ubicacion(self.a); f=next(f for f in filas if f['id_producto']==self.p); f['cantidad_fisica']=Decimal(98)
        n=conteo.guardar_conteo(self.emp,self.a,[f]); conteo.aplicar_conteo(n); self.assertEqual(self.saldo(),98)
        with self.assertRaises(ValueError): conteo.aplicar_conteo(n)
    def test_09_conteo_rechaza_stock_obsoleto(self):
        self.entrada(100); f=conteo.listar_conteo_ubicacion(self.a)[0]; f['cantidad_fisica']=98
        n=conteo.guardar_conteo(self.emp,self.a,[f]); self.entrada(1)
        with self.assertRaisesRegex(ValueError,'stock cambió'): conteo.aplicar_conteo(n)
        self.assertEqual(self.saldo(),101)
    def test_10_lote_transferencia_y_alerta_vencimiento(self):
        lote=self.lotes(); mov.registrar_transferencia(self.emp,self.p,self.a,self.b,'2.5',id_lote=lote)
        self.assertEqual(self.saldo(),10); self.assertEqual(mov._saldo_lote(self.c.cursor(),lote,self.b),Decimal('2.5'))
        self.assertEqual(inv.listar_lotes(self.p)[0]['estado_vencimiento'],'PRÓXIMO A VENCER')
        self.assertTrue(inv.consultar('SELECT id_alerta FROM alertas WHERE id_lote=? AND atendida=0',lote))
    def test_11_lote_vencido_confirmacion(self):
        self.c.cursor().execute('UPDATE productos SET control_lotes=1 WHERE id_producto=?',self.p)
        self.entrada(4,codigo_lote='V',fecha_vencimiento=(date.today()-timedelta(days=1)).isoformat()); lote=inv.listar_lotes(self.p)[0]['id_lote']
        with self.assertRaisesRegex(ValueError,'confirmación'): mov.registrar_salida(self.emp,self.p,self.a,1,id_lote=lote)
        mov.registrar_salida(self.emp,self.p,self.a,1,id_lote=lote,permitir_vencido=True); self.assertEqual(self.saldo(),3)
    def test_12_busqueda_y_filtros(self):
        self.entrada(4)
        self.assertTrue(any(p['id_producto']==self.p for p in inv.buscar_inventario('TORNILLO',id_categoria=self.cat,id_ubicacion=self.a)))
        self.assertTrue(any(p['id_producto']==self.p for p in inv.buscar_inventario(self.prefijo+'A')))
        self.assertTrue(any(p['id_producto']==self.p for p in inv.buscar_inventario(self.prefijo,estado='Stock bajo')))
    def test_13_inactivos_conservan_historial(self):
        self.entrada(2); productos.eliminar_producto(self.p)
        self.assertTrue(inv.buscar_inventario(self.prefijo,estado='Inactivos'))
        with self.assertRaises(ValueError): self.entrada(1)
        self.assertEqual(len(mov.buscar_movimientos(id_producto=self.p)),1); inv.activar_producto(self.p); self.entrada(1)
    def test_14_fuente_stock_ubicacion_activa(self):
        self.entrada(5); self.c.cursor().execute('UPDATE ubicaciones SET estado=0 WHERE id_ubicacion=?',self.a)
        self.assertEqual(self.saldo(),0)
    def test_15_prediccion_sin_datos(self):
        self.assertFalse(prediccion_stock.predecir_agotamiento(self.p,False)['datos_suficientes'])
    def test_16_costo_motivo_referencia(self):
        motivo=inv.listar_motivos('Entrada')[0]['id_motivo']; self.entrada(2,costo_unitario='1.25',id_motivo=motivo,referencia='Referencia')
        m=mov.buscar_movimientos(id_producto=self.p)[0]; self.assertEqual(m['costo_unitario'],Decimal('1.25')); self.assertEqual(m['referencia'],'Referencia'); self.assertTrue(m['motivo'])
    def test_17_duplicados_y_validaciones(self):
        with self.assertRaises(ValueError): inv.guardar_producto(self.prefijo,'Duplicado','',self.cat,self.unidad,1,1)
        for v in ('-1','NaN','Infinity','1.0001','0'):
            with self.subTest(v=v),self.assertRaises(ValueError): self.entrada(v)
    def test_18_fallo_alerta_revierte_movimiento(self):
        with patch.object(mov,'verificar_alertas_stock',side_effect=RuntimeError('Fallo simulado')):
            with self.assertRaises(RuntimeError): self.entrada(10)
        self.assertEqual(self.saldo(),0); self.assertEqual(len(mov.buscar_movimientos(id_producto=self.p)),0)

    def test_19_jarvis_ubicacion_y_mas_movidos(self):
        from jarvis import agente_inventario as agente
        self.entrada('2.5')
        with patch.object(agente,'conectar',side_effect=lambda:ConexionPrueba(self.c,'jarvis')):
            respuesta=agente.procesar_consulta('¿Qué hay en la ubicación '+self.prefijo+'A?')
            self.assertIn('Tornillo',respuesta); self.assertIn('2.5',respuesta)
            # El catálogo puede tener actividad previa: asegurar un caso dentro del ranking.
            mayor=self.c.cursor().execute('''SELECT COALESCE(MAX(total),0) FROM (
                SELECT SUM(d.cantidad) total FROM detalle_movimientos d
                JOIN movimientos m ON m.id_movimiento=d.id_movimiento
                JOIN tipos_movimiento t ON t.id_tipo_movimiento=m.id_tipo_movimiento
                WHERE d.fecha_eliminacion IS NULL AND m.fecha_eliminacion IS NULL
                  AND t.nombre IN ('Entrada','Salida') GROUP BY d.id_producto) r''').fetchone()[0]
            self.entrada(mayor+Decimal('1'))
            self.assertIn(self.prefijo.upper(),agente.procesar_consulta('¿Qué productos se movieron más este mes?'))
            self.assertIn('No encontré',agente.procesar_consulta('¿Qué hay en la ubicación NOEXISTE?'))

    def test_20_prediccion_y_reabastecimiento_reales(self):
        self.entrada(100)
        for i in range(5):
            m=mov.registrar_salida(self.emp,self.p,self.a,5)
            self.c.cursor().execute('UPDATE movimientos SET fecha_movimiento=DATEADD(day,-?,SYSDATETIME()) WHERE id_movimiento=?',i,m)
        r=prediccion_stock.predecir_agotamiento(self.p,False)
        self.assertTrue(r['datos_suficientes']); self.assertEqual(r['consumo_promedio_diario'],5)
        self.assertEqual(r['dias_restantes_promedio'],15); self.assertEqual(r['cantidad_recomendada'],75)
        self.assertEqual(r['stock_objetivo'],150)

    def test_21_conteo_reversion_de_varios_productos(self):
        p2=inv.guardar_producto(self.prefijo+'2','Segundo temporal','',self.cat,self.unidad,1,1)
        self.entrada(10); mov.registrar_entrada(self.emp,p2,self.a,10)
        filas=conteo.listar_conteo_ubicacion(self.a)
        for f in filas: f['cantidad_fisica']=9
        n=conteo.guardar_conteo(self.emp,self.a,filas)
        mov.registrar_entrada(self.emp,p2,self.a,1)
        with self.assertRaises(ValueError): conteo.aplicar_conteo(n)
        self.assertEqual(self.saldo(),10)

    def test_22_fefo_es_sugerencia_y_no_movimiento(self):
        self.lotes(); self.entrada(2,codigo_lote='L2',fecha_vencimiento=(date.today()+timedelta(days=2)).isoformat())
        sugeridos=inv.sugerir_lotes(self.p,self.a)
        self.assertEqual(sugeridos[0]['codigo_lote'],'L2'); self.assertEqual(self.saldo(),12)

if __name__=='__main__': unittest.main(verbosity=2)
