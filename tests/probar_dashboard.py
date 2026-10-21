"""Regresión de agregados reales, ausencia de datos y actividad de sesión."""

import sys
from pathlib import Path as _RutaProyecto
_RAIZ_PROYECTO = _RutaProyecto(__file__).resolve().parents[1]
if str(_RAIZ_PROYECTO) not in sys.path:
    sys.path.insert(0, str(_RAIZ_PROYECTO))

import unittest
from datetime import datetime
from unittest.mock import patch
from collections import deque
from ui.dashboard import resumir, cargar_datos, Dashboard

class Agregados(unittest.TestCase):
    def test_stock_bajo_y_agotado_no_se_duplican(self):
        productos=[{'nombre':'A','stock_actual':0,'estado_stock':'Agotado','categoria':'C'},
                   {'nombre':'B','stock_actual':2,'estado_stock':'Stock bajo','categoria':'C'},
                   {'nombre':'C','stock_actual':8,'estado_stock':'Normal','categoria':'D'}]
        r=resumir(productos,[{'estado':True},{'estado':False}],[{'estado':'Pendiente'},{'estado':'Atendida'}],[],{'anomalias_detectadas':0})
        self.assertEqual(r['kpi'],dict(productos=3,stock=10,bajo=1,agotados=1,alertas=1,empleados=1,movimientos=0,anomalias=0,valor=0,movimientos_dia=0))
        self.assertEqual(r['categorias'],{'C':2,'D':8})
    def test_detalles_no_inflan_operaciones_y_transferencia_no_inflan_entrada(self):
        datos=[{'id_movimiento':1,'tipo_movimiento':'Entrada','cantidad':2,'producto':'A'},
               {'id_movimiento':1,'tipo_movimiento':'Entrada','cantidad':3,'producto':'B'},
               {'id_movimiento':2,'tipo_movimiento':'Transferencia','cantidad':99,'producto':'A'},
               {'id_movimiento':3,'tipo_movimiento':'Salida','cantidad':1,'producto':'A'}]
        r=resumir([],[],[],datos,{'anomalias_detectadas':2})
        self.assertEqual(r['kpi']['movimientos'],3)
        self.assertEqual(r['entradas_salidas'],{'Entrada':5,'Salida':1})
        self.assertEqual(dict(r['mayor_movimiento']),{'A':3,'B':3})
    def test_fuente_fallida_no_se_muestra_como_cero(self):
        self.assertTrue(all(v is None for v in resumir(None,None,None,None,None)['kpi'].values()))
    def test_anomalias_sin_historial_suficiente_no_son_cero_confirmado(self):
        self.assertIsNone(resumir([],[],[],[],{'anomalias_detectadas':0,'mensaje':'Insuficiente'})['kpi']['anomalias'])
    def test_conexion_fallida_no_invoca_consultas_ni_inventa_cifras(self):
        from tests.probar_system_state import aislar_estado
        from core.system_state import state_manager
        aislar_estado(self)
        state_manager.update('SQL','OFFLINE')
        with patch('core.database.conectar',side_effect=AssertionError('No health check propio')), patch('ui.dashboard.listar_productos') as productos:
            r=cargar_datos(datetime(2026,10,2))
        productos.assert_not_called(); self.assertEqual(r['base'],'Sin conexión'); self.assertIsNone(r['kpi']['productos'])

class ActividadFacial(unittest.TestCase):
    def test_solo_reconocimientos_confirmados_y_evitar_frames_duplicados(self):
        d=Dashboard.__new__(Dashboard); d.cerrado=False; d.actividad=deque(maxlen=200); d.reconocidos_por_codigo={}; d._mostrar_facial=lambda:None
        for estado in ('DESCONOCIDO','SIN_CALIBRAR','VERIFICANDO'):
            d.registrar_info_facial({'estado':estado,'codigo':'EMP-1','persona':'Persona de prueba'})
        self.assertFalse(d.actividad)
        self.assertFalse(d.reconocidos_por_codigo)
        for _ in range(10): d.registrar_info_facial({'estado':'RECONOCIDO','codigo':'EMP-1','persona':'Persona de prueba'})
        self.assertEqual(len(d.actividad),1)
        d.registrar_info_facial({'estado':'RECONOCIDO','codigo':'EMP-2','persona':'Otra persona de prueba'})
        self.assertEqual(len(d.actividad),2)
        self.assertEqual(set(d.reconocidos_por_codigo),{'EMP-1','EMP-2'})

if __name__=='__main__': unittest.main()
