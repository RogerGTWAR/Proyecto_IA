"""Pruebas locales del agente sin modificar ni depender de SQL Server."""

import sys
from pathlib import Path as _RutaProyecto
_RAIZ_PROYECTO = _RutaProyecto(__file__).resolve().parents[1]
if str(_RAIZ_PROYECTO) not in sys.path:
    sys.path.insert(0, str(_RAIZ_PROYECTO))


import unittest
from datetime import datetime
from unittest.mock import patch

from jarvis import agente_inventario as agente
try:
    from jarvis import api_jarvis
except ModuleNotFoundError as error:
    if error.name != 'fastapi':
        raise
    api_jarvis = None
from jarvis.llm_jarvis import validar_decision

PRODUCTOS = [
    {"id_producto": 1, "codigo": "PROD-001", "nombre": "Motor eléctrico"},
    {"id_producto": 2, "codigo": "PROD-002", "nombre": "Taladro industrial"},
    {"id_producto": 3, "codigo": "PROD-003", "nombre": "Tornillo 1/2"},
]


class PruebasAgente(unittest.TestCase):
    def setUp(self):
        agente.reiniciar_contexto()
        self.fichas=[dict(p,stock_actual=15,stock_minimo=20,unidad_medida='Unidad',estado=True) for p in PRODUCTOS]
        self.ubicaciones=[dict(id_ubicacion=1,codigo_ubicacion='A-P01-E01',almacen='Principal',zona='A',pasillo='01',estante='E01',nivel='01',cantidad=15,unidad_medida='Unidad')]
        self.parches = [
            patch.dict('jarvis.jarvis_consultas.LECTURAS', {
                'alertas':lambda filtros:[dict(id_alerta=1,tipo='Stock bajo',nivel='ALTA',mensaje='alertas reales',fecha_generacion=datetime(2026,10,1))],
                'facial':lambda filtros:[dict(nombre='Persona desconocida',estado_identidad='NO_RECONOCIDO',motor_facial='SFace',fecha=datetime(2026,10,1))]}),
            patch('jarvis.herramientas_jarvis.datos_producto',side_effect=lambda i:next(p for p in self.fichas if p['id_producto']==i)),
            patch('jarvis.herramientas_jarvis.datos_ubicaciones',return_value=self.ubicaciones),
            patch('jarvis.herramientas_jarvis.datos_inventario',return_value=self.fichas),
            patch('jarvis.herramientas_jarvis.datos_anomalias',return_value=[]),
            patch('jarvis.herramientas_jarvis.datos_prediccion',side_effect=lambda i:dict(producto=next(p for p in PRODUCTOS if p['id_producto']==i)['nombre'],datos_suficientes=True,dias_restantes_promedio=5,riesgo='ALTO',explicacion='',mensaje='')),
            patch('jarvis.herramientas_jarvis.datos_movimientos',return_value=[dict(id_movimiento=1,id_producto=1,id_empleado=7,empleado='Carlos López',tipo_movimiento='Salida',producto='Motor eléctrico',cantidad=2,fecha_movimiento=datetime(2026,10,1))]),
            patch.object(agente, "interpretar_con_llm", return_value=(None, 0.0, "sin servicio")),
            patch.object(agente, "obtener_productos_activos", return_value=PRODUCTOS),
            patch.object(agente, "obtener_empleados_activos", return_value=[]),
            patch.object(agente, "consultar_stock_producto", side_effect=lambda i: f"stock:{i}"),
            patch.object(agente, "consultar_ubicaciones_producto", side_effect=lambda i: f"ubicacion:{i}"),
            patch.object(agente, "consultar_ultimo_retiro", side_effect=lambda i: f"retiro:{i}"),
            patch.object(agente, "consultar_productos_stock_bajo", return_value="stock bajo real"),
            patch.object(agente, "consultar_alertas_pendientes", return_value="alertas reales"),
            patch.object(agente, "consultar_predicciones_agotamiento", return_value="predicción real"),
            patch.object(agente, "consultar_anomalias_inventario", return_value="análisis real"),
            patch.object(agente, "consultar_subject", return_value="subject real"),
            patch.object(agente, "_normalizar_subject", return_value="subject17"),
            patch.object(agente, "consultar_reabastecimiento", return_value="reabastecimiento real"),
            patch.object(agente, "consultar_alertas_reconocimiento", return_value="alerta facial real"),
            patch.object(agente, "consultar_estado_general", return_value="estado general real"),
            patch('ai.facial.rostros_empleados.obtener_empleado_por_etiqueta', return_value=None),
        ]
        for parche in self.parches: parche.start()

    def tearDown(self):
        for parche in reversed(self.parches): parche.stop()

    def test_stock_ubicacion_y_contexto(self):
        self.assertIn('15',agente.procesar_pregunta("¿Cuántos motores quedan?"))
        self.assertIn('A-P01-E01',agente.procesar_pregunta("¿Dónde están?"))

    def test_ultimo_retiro(self):
        self.assertIn('Salida',agente.procesar_pregunta("¿Quién retiró el último motor?"))

    def test_ortografia_y_producto_inexistente(self):
        self.assertIn("Motor eléctrico", agente.procesar_pregunta("motore"))
        self.assertIn("No estoy seguro de qué quieres consultar", agente.procesar_pregunta("computadora cuántica"))

    def test_consultas_globales(self):
        self.assertIn('Motor eléctrico',agente.procesar_pregunta("productos con stock bajo"))
        self.assertIn("alertas reales", agente.procesar_pregunta("Jarvis dime si hay alertas"))
        self.assertIn('podría durar',agente.procesar_pregunta("qué podría agotarse pronto"))

    def test_saludo_mas_consulta(self):
        self.assertIn('15',agente.procesar_pregunta("Hola Jarvis, ¿cómo estamos de motores?"))

    def test_lista_blanca_llm(self):
        valida = validar_decision({"intencion": "consultar_stock", "entidades": {"producto": "motor"}})
        peligrosa = validar_decision({"intencion": "borrar_base", "entidades": {}})
        self.assertEqual(valida["intencion"], "consultar_stock")
        self.assertIsNone(peligrosa)

    def test_anomalias_respuesta_estructurada_y_solo_lectura(self):
        resultado = agente.procesar_consulta_estructurada("hay movimientos extraños")
        self.assertIn('No hay anomalías',resultado["respuesta"])
        self.assertEqual(resultado["intencion"], "consultar_anomalias")
        self.assertIn("tiempo_ms", resultado)
        rechazo = agente.procesar_pregunta("elimina el producto motor")
        self.assertIn("No ejecuté cambios", rechazo)

    def test_pregunta_ambigua(self):
        ambiguos = [PRODUCTOS[0], {"id_producto": 4, "codigo": "PROD-004",
                                   "nombre": "Motor industrial"}]
        with patch.object(agente.procesador_nlp, "resolver_producto", return_value=ambiguos):
            respuesta=agente.procesar_pregunta("stock de motor")
            self.assertIn("2 productos", respuesta)
            self.assertIn("consultar el stock", respuesta)

    def test_subject_reabastecimiento_y_alerta_facial(self):
        subject = agente.procesar_consulta_estructurada("¿Quién es el sujeto 17?")
        self.assertEqual(subject["intencion"], "consultar_subject")
        self.assertEqual(subject["respuesta"], "subject real")
        comprar = agente.procesar_consulta_estructurada(
            "Jarvis, ¿hay algo que tenga que comprar pronto?"
        )
        self.assertEqual(comprar["intencion"], "consultar_reabastecimiento")
        self.assertEqual(comprar["respuesta"], "reabastecimiento real")
        alerta = agente.procesar_consulta_estructurada("¿Hubo personas no reconocidas?")
        self.assertEqual(alerta["intencion"], "facial_listar")
        self.assertIn("Persona desconocida", alerta["respuesta"])

    def test_rostro_y_movimientos_empleado(self):
        empleado = [{"id_empleado": 7, "codigo_empleado": "EMP-007",
                     "nombre": "Carlos López", "cargo": "Auxiliar"}]
        with patch.object(agente, "obtener_empleados_activos", return_value=empleado), \
             patch.object(agente, "consultar_rostro_empleado", return_value="rostro real"), \
             patch.object(agente, "consultar_movimientos_empleado", return_value="movimientos reales"):
            rostro = agente.procesar_consulta_estructurada("¿Carlos tiene rostro registrado?")
            self.assertEqual(rostro["intencion"], "consultar_rostro_empleado")
            self.assertEqual(rostro["respuesta"], "rostro real")
            movimientos = agente.procesar_consulta_estructurada("¿Qué movimientos hizo Carlos?")
            self.assertIn('Carlos López',movimientos["respuesta"])

    def test_plan_con_stock_y_ubicacion(self):
        resultado = agente.procesar_consulta_estructurada(
            "¿Cuántos motores quedan y dónde están?"
        )
        self.assertIn('15',resultado['respuesta'])
        self.assertIn('A-P01-E01',resultado['respuesta'])
        self.assertEqual(resultado['acciones_ui'],[])
        self.assertTrue(any(a['tipo']=='producto_mapa' for a in resultado['acciones_opcionales']))

    def test_resumen_general_integrado(self):
        resultado = agente.procesar_consulta_estructurada("¿Cómo está el inventario?")
        self.assertEqual(resultado["intencion"], "resumen_inventario")
        self.assertEqual(resultado["respuesta"], "estado general real")


@unittest.skipIf(api_jarvis is None, 'FastAPI no está instalado; API opcional no disponible.')
class PruebasAPI(unittest.TestCase):
    def test_post_agente_consultar(self):
        esperado = {"respuesta": "Hay 15 unidades.", "intencion": "consultar_stock",
                    "entidades": {"producto": "Motor eléctrico"},
                    "origen": "NLP local", "tiempo_ms": 12.5}
        with patch.object(api_jarvis, "procesar_consulta", return_value=esperado):
            respuesta = api_jarvis.consultar(
                api_jarvis.ConsultaAgente(mensaje="¿Cuántos motores quedan?")
            )
        self.assertEqual(respuesta, esperado)


if __name__ == "__main__":
    unittest.main(verbosity=2)
