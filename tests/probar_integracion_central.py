"""Integración de datos reales con transacciones que se revierten."""

import sys
from pathlib import Path as _RutaProyecto
_RAIZ_PROYECTO = _RutaProyecto(__file__).resolve().parents[1]
if str(_RAIZ_PROYECTO) not in sys.path:
    sys.path.insert(0, str(_RAIZ_PROYECTO))

from unittest.mock import patch
from decimal import Decimal
from datetime import timedelta
import unittest
from jarvis import agente_inventario as agente
from inventory import mapa_almacen as mapa
from probar_inventario import InventarioSQL,ConexionPrueba
from ai.prediction.prediccion_stock import calcular_riesgo,predecir_agotamiento

class IntegracionCentralSQL(InventarioSQL):
    # Reutilizar únicamente el montaje transaccional, no repetir sus pruebas.
    def test_contexto_stock_mapa_prediccion_y_reset(self):
        self.entrada('100')
        agente.reiniciar_contexto()
        with patch.object(agente,'conectar',side_effect=lambda:ConexionPrueba(self.c,'central')):
            r=agente.procesar_consulta('¿Cuántos '+self.prefijo+' quedan?',True)
            self.assertIn('100',r['respuesta']); self.assertEqual(agente.contexto_agente['ultimo_producto_id'],self.p)
            r=agente.procesar_consulta('¿Dónde está?',True)
            self.assertEqual(r['acciones_ui'],[{'tipo':'producto_mapa','id':self.p}])
            self.assertEqual(r['datos']['ubicaciones'][0]['id_ubicacion'],self.a)
            self.assertNotIn('resaltando',r['respuesta'])
            r=agente.procesar_consulta('¿Cuánto tiempo durará?',True)
            self.assertFalse(r['datos']['prediccion']['datos_suficientes'])
            self.assertIsNone(r['datos']['prediccion']['fecha_agotamiento'])
        agente.reiniciar_contexto(); self.assertIsNone(agente.contexto_agente.get('ultima_prediccion'))

    def test_mapa_transferencia_preserva_total(self):
        from inventory import movimientos
        self.entrada('100')
        movimientos.registrar_transferencia(self.emp,self.p,self.a,self.b,'25')
        filas=mapa.ubicaciones_producto(self.p)
        self.assertEqual(sum(u['cantidad'] for u in filas),Decimal('100'))
        self.assertEqual({u['id_ubicacion'] for u in filas},{self.a,self.b})
        self.assertEqual(mapa.productos_ubicacion(self.b)[0]['cantidad'],Decimal('25'))
        self.assertEqual(predecir_agotamiento(self.p,False,ventana=7)['dias_con_salidas'],0)
        self.assertIn(self.p,{p['id_producto'] for p in mapa.buscar_productos_mapa('tornillos')})

    def test_fecha_riesgo_y_ventana_sin_consumo(self):
        from inventory import movimientos
        self.entrada('100')
        for i in range(5):
            n=movimientos.registrar_salida(self.emp,self.p,self.a,5)
            self.c.cursor().execute('UPDATE movimientos SET fecha_movimiento=DATEADD(day,-?,SYSDATETIME()) WHERE id_movimiento=?',i,n)
        r=predecir_agotamiento(self.p,False,ventana=30)
        self.assertEqual(r['dias_restantes_promedio'],15)
        self.assertEqual(r['fecha_agotamiento'],r['fecha_analisis']+timedelta(days=15))
        self.assertEqual(r['riesgo'],'MEDIO'); self.assertEqual(r['tendencia'],'ESTABLE')
        self.assertIn('transferencias',r['explicacion'])
        self.c.cursor().execute('UPDATE movimientos SET fecha_movimiento=DATEADD(day,-60,fecha_movimiento) WHERE id_empleado=?',self.emp)
        r=predecir_agotamiento(self.p,False,ventana=7)
        self.assertFalse(r['datos_suficientes']); self.assertIsNone(r['fecha_agotamiento'])

class Riesgo(unittest.TestCase):
    def test_riesgo_prioriza_agotado_minimo_y_cobertura(self):
        self.assertEqual(calcular_riesgo(0,0,None),'CRÍTICO')
        self.assertEqual(calcular_riesgo(4,10,100),'CRÍTICO')
        self.assertEqual(calcular_riesgo(10,10,100),'ALTO')
        self.assertEqual(calcular_riesgo(100,10,20),'MEDIO')
        self.assertEqual(calcular_riesgo(100,10,50),'BAJO')

# La subclase incorpora solo sus propios casos.
def load_tests(loader,tests,pattern):
    conjunto=unittest.TestSuite()
    for nombre in ('test_contexto_stock_mapa_prediccion_y_reset','test_mapa_transferencia_preserva_total','test_fecha_riesgo_y_ventana_sin_consumo'):
        conjunto.addTest(IntegracionCentralSQL(nombre))
    conjunto.addTests(loader.loadTestsFromTestCase(Riesgo))
    return conjunto
