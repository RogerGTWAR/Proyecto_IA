"""Catálogo central, validación y ejecución controlada de herramientas Jarvis."""

from dataclasses import dataclass
from typing import Callable


ENTIDADES_JARVIS = {
    "producto": ("categoria", "existencia", "ubicacion", "detalle_movimiento", "alerta", "prediccion"),
    "existencia": ("producto", "ubicacion"),
    "movimiento": ("tipo_movimiento", "detalle_movimiento", "empleado", "alerta"),
    "detalle_movimiento": ("movimiento", "producto", "ubicacion"),
    "empleado": ("movimiento", "rostro", "subject", "alerta"),
    "rostro": ("empleado", "subject"),
    "alerta": ("tipo_alerta", "producto", "movimiento", "empleado"),
    "anomalia": ("producto", "movimiento", "empleado"),
}

CAPACIDADES_JARVIS = {
    "productos": ("listar", "buscar", "detalle", "codigo", "categoria", "precio", "stock", "stock_minimo", "estado"),
    "existencias": ("stock_total", "stock_por_ubicacion", "ubicaciones"),
    "movimientos": ("recientes", "por_producto", "por_empleado", "ultima_salida", "ultimo_movimiento", "movimientos_hoy"),
    "empleados": ("listar_activos", "detalle", "cargo", "movimientos", "rostro_asociado"),
    "rostros": ("subject_asociado", "empleado_asociado", "con_rostro", "sin_rostro", "estado_cnn"),
    "alertas": ("pendientes", "stock", "nivel", "anomalias", "personas_no_reconocidas"),
    "prediccion": ("riesgo_agotamiento", "reabastecimiento"),
    "anomalias": ("movimientos_anormales", "cantidades_inusuales"),
    "inventario": ("resumen", "problemas", "actividad_reciente"),
}


@dataclass(frozen=True)
class Herramienta:
    nombre: str
    descripcion: str
    parametros: tuple
    entidad: str
    funcion: Callable
    requiere_confirmacion: bool = False


REGISTRO_HERRAMIENTAS = {}

SENALES_CAPACIDAD = {
    "consultar_stock": ("cuanto", "cuantos", "cantidad disponible", "unidades", "existencias", "tenemos"),
    "consultar_ubicacion": ("donde", "ubicacion", "ubica", "localiza", "estante", "pasillo"),
    "consultar_empleado": ("quien es", "cargo", "datos de", "informacion sobre", "empleado"),
    "consultar_subject": ("subject", "sujeto", "persona"),
    "consultar_alertas": ("alerta", "alertas", "aviso", "notificacion", "problema detectado"),
    "consultar_reabastecimiento": ("comprar", "pedir", "reabastecer", "reponer", "se esta acabando"),
    "consultar_anomalias": ("anomalia", "raro", "anormal", "inusual", "sospechos", "extrano"),
    "consultar_producto": ("precio", "cuesta", "categoria", "hablame", "informacion del producto"),
    "resumen_inventario": ("como esta el inventario", "como estamos", "estado general", "panorama",
                            "situacion actual", "resumen", "deberia revisar", "algo urgente"),
}


def registrar(nombre, descripcion, parametros, entidad, funcion, requiere_confirmacion=False):
    REGISTRO_HERRAMIENTAS[nombre] = Herramienta(
        nombre, descripcion, tuple(parametros), entidad, funcion, requiere_confirmacion
    )


def obtener_descripciones():
    return {nombre: {"descripcion": h.descripcion, "parametros": h.parametros,
                     "entidad": h.entidad, "requiere_confirmacion":h.requiere_confirmacion}
            for nombre, h in REGISTRO_HERRAMIENTAS.items()}


def inferir_capacidad(texto_normalizado):
    """Mapeo semántico declarativo usado antes de declarar una frase desconocida."""
    puntajes = {accion: sum(1 for señal in señales if señal in texto_normalizado)
                for accion, señales in SENALES_CAPACIDAD.items()}
    mejor = max(puntajes, key=puntajes.get)
    return mejor if puntajes[mejor] else None


def ejecutar(nombre, parametros=None, confirmado=False):
    herramienta = REGISTRO_HERRAMIENTAS.get(nombre)
    if herramienta is None:
        raise KeyError(f"Herramienta no autorizada: {nombre}")
    if herramienta.requiere_confirmacion and not confirmado:
        raise ValueError('Esta herramienta requiere una confirmación vigente.')
    parametros = parametros or {}
    faltantes = [p for p in herramienta.parametros if p not in parametros]
    if faltantes:
        raise ValueError("Faltan parámetros: " + ", ".join(faltantes))
    permitidos = {p: parametros[p] for p in herramienta.parametros}
    from core.audit_service import operation
    with operation('JARVIS', 'TOOL_EXECUTE', data={'tool':nombre, 'confirmed':confirmado}):
        return herramienta.funcion(**permitidos)


def crear_plan(intencion, texto_normalizado):
    """Planificador declarativo para combinaciones frecuentes y seguras."""
    reglas = (
        (("stock", "cuanto", "cuantos", "cantidad", "quedan", "existencias"),
         ("donde", "ubicacion", "estante", "localiza"),
         ("consultar_stock", "consultar_ubicacion")),
        (("rostro", "subject", "subject"), ("movimiento", "actividad"),
         ("consultar_rostro_empleado", "movimientos_empleado")),
    )
    for grupo_a, grupo_b, acciones in reglas:
        if any(p in texto_normalizado for p in grupo_a) and any(
                p in texto_normalizado for p in grupo_b):
            return list(acciones)
    return [intencion] if intencion else []


def datos_inventario(estado='Todos',categoria=None):
    from inventory.inventario_service import buscar_inventario
    return buscar_inventario(estado=estado,id_categoria=categoria)


def datos_producto(id_producto):
    from inventory.inventario_service import obtener_ficha
    fila=obtener_ficha(id_producto)
    if not fila.get('estado',True):raise ValueError('El producto ya no está activo.')
    return fila


def datos_ubicaciones(id_producto):
    from inventory.mapa_almacen import ubicaciones_producto
    return ubicaciones_producto(id_producto)


def datos_prediccion(id_producto):
    from core.automatizacion_inventario import obtener_prediccion as predecir_agotamiento
    return predecir_agotamiento(id_producto,False)


def datos_movimientos(filtros,producto=None,empleado=None):
    from inventory.movimientos import buscar_movimientos
    return buscar_movimientos(id_producto=producto,id_empleado=empleado,
        fecha_desde=filtros.get('fecha_desde'),fecha_hasta=filtros.get('fecha_hasta'),
        tipo_movimiento=filtros.get('tipo_movimiento'))


def datos_anomalias(filtros):
    # Consultar no persiste ni vuelve a clasificar: conserva el análisis del módulo.
    from ai.anomalies.deteccion_anomalias import listar_anomalias
    nivel=filtros.get('nivel')
    nivel={'ALTO':'ALTA','BAJO':'BAJA','MEDIO':'MEDIA','CRÍTICO':'CRÍTICA'}.get(nivel,nivel)
    return listar_anomalias(fecha_desde=filtros.get('fecha_desde'),
        fecha_hasta=filtros.get('fecha_hasta'),nivel=nivel)


def datos_contenido(filtros):
    from inventory.inventario_service import consultar
    campo=filtros.get('campo_ubicacion');valor=filtros.get('valor_ubicacion')
    if campo not in ('zona','estante','pasillo','ubicacion') or not valor:
        raise ValueError('Indica la zona, estante, pasillo o código de ubicación.')
    columna={'ubicacion':'codigo_ubicacion','zona':'zona','estante':'estante','pasillo':'pasillo'}[campo]
    if campo in ('estante','pasillo'):
        from inventory.organizacion_fisica import numero_fisico
        try:valor=f'{numero_fisico(valor):02}'
        except ValueError:pass
    return consultar('''SELECT u.id_ubicacion,u.codigo_ubicacion,u.almacen,u.zona,u.pasillo,u.estante,u.nivel,e.posicion,
        p.id_producto,p.codigo,p.nombre,e.cantidad,p.unidad_medida
        FROM ubicaciones u JOIN existencias e ON e.id_ubicacion=u.id_ubicacion
        JOIN productos p ON p.id_producto=e.id_producto WHERE u.'''+columna+''' COLLATE Latin1_General_CI_AI=?
        AND u.estado=1 AND u.fecha_eliminacion IS NULL AND p.estado=1 AND p.fecha_eliminacion IS NULL
        AND e.fecha_eliminacion IS NULL ORDER BY u.codigo_ubicacion,e.posicion''',valor)
