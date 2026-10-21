"""Resolución de tipos y aislamiento del cálculo; verificaciones SQL con rollback."""
from copy import deepcopy
from datetime import date,timedelta
from decimal import Decimal
import unittest
from unittest.mock import Mock,patch
from ai.prediction import prediccion_stock as pred
from inventory.tipos_alerta import obtener_tipo_alerta,PROXIMO_AGOTARSE
from core.database import conectar


class Resolucion(unittest.TestCase):
    def cursor(self, filas=None):
        q=Mock()
        q.execute.return_value.fetchall.return_value=filas if filas is not None else [(3,'Proximo a agotarse',True,None)]
        return q

    def test_normalizacion_y_clave_estable(self):
        for nombre in ('Próximo a agotarse','proximo a agotarse',' PROXIMO   A AGOTARSE ',PROXIMO_AGOTARSE):
            self.assertEqual(obtener_tipo_alerta(nombre,self.cursor()),3)

    def test_id_obtenido_del_catalogo(self):
        self.assertEqual(obtener_tipo_alerta(PROXIMO_AGOTARSE,self.cursor([(87,'PRÓXIMO A AGOTARSE',True,None)])),87)

    def test_inactivo_y_eliminado_no_autorizan(self):
        for filas in ([(3,'Proximo a agotarse',False,None)],[(3,'Proximo a agotarse',True,date.today())]):
            self.assertIsNone(obtener_tipo_alerta(PROXIMO_AGOTARSE,self.cursor(filas),obligatorio=False))
            with self.assertRaises(ValueError):obtener_tipo_alerta(PROXIMO_AGOTARSE,self.cursor(filas))

    def test_duplicados_semanticos_no_se_eligen_arbitrariamente(self):
        with self.assertRaisesRegex(ValueError,'equivalentes'):
            obtener_tipo_alerta(PROXIMO_AGOTARSE,self.cursor([(3,'Proximo a agotarse',True,None),(8,'Próximo a agotarse',True,None)]))


class CalculoIndependiente(unittest.TestCase):
    def datos(self,stock=10,dias=10):
        hoy=date(2026,10,13)
        return dict(producto='Producto seleccionado',stock_actual=Decimal(stock),stock_minimo=Decimal(2),
            fecha_analisis=hoy,ventana=30,dias_analizados=10,dias_con_salidas=dias,
            consumo_diario=[dict(fecha=hoy-timedelta(days=9-i),cantidad=5) for i in range(10)],
            consumo_promedio_diario=5.0,consumo_maximo=5,consumo_minimo=5)

    def test_fallo_de_alerta_conserva_prediccion_y_se_registra(self):
        with patch.object(pred,'analizar_consumo_producto',return_value=self.datos()), \
             patch.object(pred,'_actualizar_alerta',side_effect=RuntimeError('Persistencia no disponible')), \
             self.assertLogs('prediccion_stock',level='WARNING'):
            resultado=pred.predecir_agotamiento(1)
        self.assertTrue(resultado['datos_suficientes'])
        self.assertEqual(resultado['dias_restantes_promedio'],2)
        self.assertIn('advertencia_alerta',resultado)

    def test_sin_datos_no_toca_alertas(self):
        with patch.object(pred,'analizar_consumo_producto',return_value=self.datos(dias=0)), \
             patch.object(pred,'_actualizar_alerta') as actualizar:
            resultado=pred.predecir_agotamiento(1)
        self.assertFalse(resultado['datos_suficientes']);actualizar.assert_not_called()

    def test_consulta_sin_persistencia(self):
        with patch.object(pred,'analizar_consumo_producto',return_value=self.datos()), \
             patch.object(pred,'_actualizar_alerta') as actualizar:
            pred.predecir_agotamiento(1,actualizar_alertas=False)
        actualizar.assert_not_called()


class ConexionSinConfirmar:
    """Usar la transacción real del caso; la función no puede confirmarla."""
    def __init__(self,c):self.c=c
    def cursor(self):return self.c.cursor()
    def commit(self):pass
    def rollback(self):self.c.rollback()
    def close(self):pass


class AlertasSQL(unittest.TestCase):
    def setUp(self):
        self.c=conectar();self.q=self.c.cursor()
        self.addCleanup(self.c.close);self.addCleanup(self.c.rollback)
        self.tipo=obtener_tipo_alerta(PROXIMO_AGOTARSE,self.q)
        self.p,self.nombre=self.q.execute('SELECT TOP 1 id_producto,nombre FROM productos WHERE estado=1 ORDER BY id_producto').fetchone()
        self.q.execute('UPDATE alertas SET atendida=1 WHERE id_producto=? AND id_tipo_alerta=?',self.p,self.tipo)
        parche=patch.object(pred,'conectar',return_value=ConexionSinConfirmar(self.c));parche.start();self.addCleanup(parche.stop)

    def pendientes(self):
        return self.q.execute('SELECT COUNT(*) FROM alertas WHERE id_producto=? AND id_tipo_alerta=? AND atendida=0 AND fecha_eliminacion IS NULL',self.p,self.tipo).fetchone()[0]

    def test_tipo_real_sin_tilde(self):
        self.assertEqual(self.tipo,3)

    def test_riesgo_crea_una_sola_pendiente(self):
        pred._actualizar_alerta(self.p,self.nombre,2)
        pred._actualizar_alerta(self.p,self.nombre,3)
        self.assertEqual(self.pendientes(),1)

    def test_sin_riesgo_no_crea_alerta(self):
        pred._actualizar_alerta(self.p,self.nombre,30)
        self.assertEqual(self.pendientes(),0)

    def test_agotado_no_crea_alerta_de_agotamiento_futuro(self):
        pred._actualizar_alerta(self.p,self.nombre,0)
        self.assertEqual(self.pendientes(),0)

    def test_repetir_prediccion_con_riesgo_no_duplica(self):
        # Fixture únicamente en memoria: comprobar el contrato cálculo -> SQL.
        datos=CalculoIndependiente().datos()
        with patch.object(pred,'analizar_consumo_producto',side_effect=lambda *a,**k:deepcopy(datos)):
            for _ in range(2):
                resultado=pred.predecir_agotamiento(self.p)
                self.assertTrue(resultado['datos_suficientes'])
                self.assertNotIn('advertencia_alerta',resultado)
        self.assertEqual(self.pendientes(),1)


if __name__=='__main__':unittest.main()
