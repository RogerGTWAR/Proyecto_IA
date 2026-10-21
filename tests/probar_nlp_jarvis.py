"""Prueba reproducible del clasificador con frases separadas del entrenamiento."""

import sys
from pathlib import Path as _RutaProyecto
_RAIZ_PROYECTO = _RutaProyecto(__file__).resolve().parents[1]
if str(_RAIZ_PROYECTO) not in sys.path:
    sys.path.insert(0, str(_RAIZ_PROYECTO))


from jarvis.nlp_jarvis import procesador_nlp


CASOS = [
    ("cuantas unidades quedan del articulo", "consultar_stock"),
    ("hay disponibilidad de motores", "consultar_stock"),
    ("en cual pasillo dejaron el taladro", "consultar_ubicacion"),
    ("encuentra donde guardaron los tornillos", "consultar_ubicacion"),
    ("operacion mas nueva del motor", "ultimo_movimiento"),
    ("actividad anterior del taladro", "historial_producto"),
    ("quien fue responsable de sacar el producto", "ultimo_retiro"),
    ("articulos que necesitan reposicion", "stock_bajo"),
    ("lista de articulos sin unidades", "productos_agotados"),
    ("avisos pendientes del sistema", "consultar_alertas"),
    ("consulta los datos del trabajador carlos", "consultar_empleado"),
    ("operaciones recientes del almacen", "consultar_movimientos"),
    ("panorama general de existencias", "resumen_inventario"),
    ("buen día jarvis", "saludo"),
    ("te lo agradezco mucho", "agradecimiento"),
    ("hasta la próxima", "despedida"),
    ("cómo debo dirigirme a ti", "pregunta_nombre"),
    ("explícame en qué puedes ayudar", "ayuda"),
]


def ejecutar_prueba():
    aciertos = 0
    print(f"{'ENTRADA':48} {'ESPERADA':24} {'PREDICHA':24} CONFIANZA")
    print("-" * 112)
    for texto, esperada in CASOS:
        resultado = procesador_nlp.interpretar(texto)
        predicha = resultado.intencion or "baja_confianza"
        aciertos += predicha == esperada
        print(f"{texto[:47]:48} {esperada:24} {predicha:24} {resultado.confianza:.3f}")
    exactitud = aciertos / len(CASOS)
    print(f"\nExactitud observada: {aciertos}/{len(CASOS)} = {exactitud:.2%}")
    return exactitud


if __name__ == "__main__":
    ejecutar_prueba()
