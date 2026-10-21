"""Conteos reales en transacciones revertidas, sin datos persistidos."""
import unittest
from decimal import Decimal
from unittest.mock import patch
from inventory import conteo_inventario as conteo


class ConteosSQL(unittest.TestCase):
    def setUp(self):
        from core.database import conectar
        from tests.probar_inventario import ConexionPrueba
        from inventory import inventario_service as inv
        from inventory import movimientos as mov
        from inventory import alertas
        from ai.prediction import prediccion_stock
        self.c=conectar();self.c.cursor().execute('BEGIN TRANSACTION');self.numero=0
        self.addCleanup(self.c.close);self.addCleanup(self.c.rollback)
        def aislada():
            self.numero+=1;return ConexionPrueba(self.c,'conteo'+str(self.numero))
        for modulo in (inv,mov,alertas,prediccion_stock):
            p=patch.object(modulo,'conectar',side_effect=aislada);p.start();self.addCleanup(p.stop)
        q=self.c.cursor()
        fila=q.execute('''SELECT TOP 1 p.id_producto,e.id_ubicacion FROM productos p
            JOIN existencias e ON e.id_producto=p.id_producto JOIN ubicaciones u ON u.id_ubicacion=e.id_ubicacion
            WHERE p.estado=1 AND p.fecha_eliminacion IS NULL AND p.control_lotes=0 AND e.fecha_eliminacion IS NULL
            AND u.estado=1 AND u.fecha_eliminacion IS NULL
            AND (SELECT COUNT(*) FROM existencias ex WHERE ex.id_producto=p.id_producto AND ex.fecha_eliminacion IS NULL)=1
            ORDER BY p.id_producto''').fetchone()
        if fila is None:self.skipTest('No hay producto activo con una ubicación para la verificación transaccional.')
        self.p,self.a=fila
        self.emp=q.execute('SELECT TOP 1 id_empleado FROM empleados WHERE estado=1 AND fecha_eliminacion IS NULL ORDER BY id_empleado').fetchone()[0]
        mov.registrar_ajuste(self.emp,self.p,self.a,0,'Verificación transaccional de conteo')
    def entrada(self,cantidad):
        from inventory.movimientos import registrar_entrada
        return registrar_entrada(self.emp,self.p,self.a,cantidad)
    def saldo(self):
        from inventory.inventario_service import consultar
        return consultar('SELECT stock_actual FROM vw_stock_producto WHERE id_producto=?',self.p)[0]['stock_actual']
    def filas(self):return [f for f in conteo.listar_conteo_ubicacion(self.a) if f['id_producto']==self.p]
    def test_incompleto_rechaza_aplicar(self):
        self.entrada(20);filas=self.filas();filas[0]['contado']=False
        numero=conteo.guardar_conteo(self.emp,self.a,filas)
        with self.assertRaisesRegex(ValueError,'Complete'):conteo.aplicar_conteo(numero)
        self.assertEqual(self.saldo(),20)
    def test_reanudar_actualiza_mismo_borrador_y_cierra(self):
        self.entrada(20);filas=self.filas();filas[0]['contado']=False
        numero=conteo.guardar_conteo(self.emp,self.a,filas)
        c,filas=conteo.cargar_conteo(numero)
        self.assertFalse(filas[0]['contado'])
        filas[0].update(contado=True,cantidad_fisica=Decimal(19))
        self.assertEqual(conteo.guardar_conteo(self.emp,self.a,filas,id_conteo=numero),numero)
        conteo.aplicar_conteo(numero);self.assertEqual(self.saldo(),19)
        with self.assertRaisesRegex(ValueError,'cerrado'):conteo.guardar_conteo(self.emp,self.a,filas,id_conteo=numero)
        with self.assertRaises(ValueError):conteo.aplicar_conteo(numero)
        observacion=self.c.cursor().execute("SELECT TOP 1 observacion FROM movimientos WHERE id_empleado=? ORDER BY id_movimiento DESC",self.emp).fetchone()[0]
        self.assertIn('Ajuste generado por conteo',observacion)
    def test_sin_diferencias_no_crea_movimientos(self):
        self.entrada(20);filas=self.filas();filas[0]['contado']=True
        antes=self.c.cursor().execute('SELECT COUNT(*) FROM movimientos WHERE id_empleado=?',self.emp).fetchone()[0]
        numero=conteo.guardar_conteo(self.emp,self.a,filas);conteo.aplicar_conteo(numero)
        despues=self.c.cursor().execute('SELECT COUNT(*) FROM movimientos WHERE id_empleado=?',self.emp).fetchone()[0]
        self.assertEqual(antes,despues)
    def test_legacy_sin_confirmacion_no_se_aplica(self):
        self.entrada(20);numero=conteo.guardar_conteo(self.emp,self.a,self.filas())
        self.c.cursor().execute('UPDATE detalle_conteos SET contado=NULL WHERE id_conteo=?',numero)
        with self.assertRaisesRegex(ValueError,'Complete'):conteo.aplicar_conteo(numero)
    def test_stock_referencia_no_puede_reescribirse(self):
        self.entrada(20);filas=self.filas();numero=conteo.guardar_conteo(self.emp,self.a,filas)
        filas[0]['cantidad_sistema']=Decimal(21)
        with self.assertRaisesRegex(ValueError,'referencia'):conteo.guardar_conteo(self.emp,self.a,filas,id_conteo=numero)
        self.assertEqual(conteo.cargar_conteo(numero)[1][0]['cantidad_sistema'],20)
    def test_stock_obsoleto_se_rechaza(self):
        self.entrada(20);filas=self.filas();filas[0]['cantidad_fisica']=19
        numero=conteo.guardar_conteo(self.emp,self.a,filas);self.entrada(1)
        with self.assertRaisesRegex(ValueError,'stock cambió'):conteo.aplicar_conteo(numero)
        self.assertEqual(self.saldo(),21)
    def test_borrador_modificado_despues_de_revisar_se_rechaza(self):
        from copy import deepcopy
        self.entrada(20);filas=self.filas();filas[0]['cantidad_fisica']=19
        numero=conteo.guardar_conteo(self.emp,self.a,filas);revisadas=deepcopy(filas)
        filas[0]['cantidad_fisica']=18;conteo.guardar_conteo(self.emp,self.a,filas,id_conteo=numero)
        with self.assertRaisesRegex(ValueError,'borrador cambió'):
            conteo.aplicar_conteo(numero,esperado=revisadas,empleado_esperado=self.emp)
        self.assertEqual(self.saldo(),20)
    def test_reversion_integra_si_otro_producto_cambia(self):
        from inventory.movimientos import registrar_entrada
        self.entrada(20)
        filas=[f for f in conteo.listar_conteo_ubicacion(self.a) if f.get('id_lote') is None]
        if len(filas)<2:self.skipTest('La ubicación no contiene dos productos sin lotes para comprobar reversión conjunta.')
        for f in filas:f.update(cantidad_fisica=f['cantidad_sistema']+1,contado=True)
        numero=conteo.guardar_conteo(self.emp,self.a,filas)
        ultimo=max(f['id_producto'] for f in filas);registrar_entrada(self.emp,ultimo,self.a,1)
        antes={f['id_producto']:f['cantidad_sistema'] for f in conteo.listar_conteo_ubicacion(self.a)}
        with self.assertRaisesRegex(ValueError,'stock cambió'):conteo.aplicar_conteo(numero)
        despues={f['id_producto']:f['cantidad_sistema'] for f in conteo.listar_conteo_ubicacion(self.a)}
        self.assertEqual(antes,despues)
        self.assertEqual(self.c.cursor().execute('SELECT COUNT(*) FROM detalle_conteos WHERE id_conteo=? AND id_movimiento IS NOT NULL',numero).fetchone()[0],0)


if __name__=='__main__':unittest.main()
