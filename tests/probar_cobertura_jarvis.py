"""Cobertura lingüística: cinco formulaciones por capacidad principal."""

import sys
from pathlib import Path as _RutaProyecto
_RAIZ_PROYECTO = _RutaProyecto(__file__).resolve().parents[1]
if str(_RAIZ_PROYECTO) not in sys.path:
    sys.path.insert(0, str(_RAIZ_PROYECTO))


import unittest

from jarvis.agente_inventario import detectar_intencion


CASOS = {
    "consultar_stock": (
        "cantidad disponible del motor", "dime las unidades del taladro",
        "tenemos tornillos disponibles", "existencias actuales del rodamiento",
        "cómo vamos de motores",
    ),
    "consultar_ubicacion": (
        "en qué estante dejaron motores", "localízame el taladro",
        "dónde guardaron los tornillos", "ubícame los rodamientos",
        "en cuál pasillo está el motor",
    ),
    "consultar_empleado": (
        "quién es Carlos", "cargo de Ana", "datos de Juan",
        "información sobre Carlos", "consulta al empleado Carlos",
    ),
    "consultar_subject": (
        "quién es subject17", "a quién pertenece sujeto 3",
        "persona 8 está registrada", "empleado asociado a subject12",
        "información del sujeto 4",
    ),
    "consultar_alertas": (
        "tenemos alertas pendientes", "hay avisos importantes",
        "muéstrame las alertas", "problemas detectados en almacén",
        "consulta las notificaciones",
    ),
    "consultar_reabastecimiento": (
        "qué tengo que comprar pronto", "qué debo pedir",
        "hace falta reabastecer algo", "productos para comprar",
        "qué se está acabando",
    ),
    "consultar_anomalias": (
        "hay algo raro", "movimientos fuera de lo normal",
        "cantidades inusuales", "actividad sospechosa",
        "detectaste anomalías",
    ),
    "resumen_inventario": (
        "cómo está el inventario", "estado general del almacén",
        "dame el panorama general", "situación actual del inventario",
        "resumen del almacén",
    ),
}


class CoberturaJarvis(unittest.TestCase):
    def test_cinco_formas_por_capacidad(self):
        for esperado, frases in CASOS.items():
            for frase in frases:
                with self.subTest(capacidad=esperado, frase=frase):
                    self.assertEqual(detectar_intencion(frase), esperado)


if __name__ == "__main__":
    unittest.main(verbosity=2)
