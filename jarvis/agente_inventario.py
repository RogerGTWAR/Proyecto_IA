pass
import re
import random
import threading
import time
import traceback
import logging
import os
from contextvars import ContextVar
from collections.abc import MutableMapping
from collections import deque

from core.database import conectar
from integrations.arduino.led_service import servicio_led, resolver_filas
from jarvis.nlp_jarvis import normalizar_texto, procesador_nlp, IntentRouter, EntityResolver
from jarvis.llm_jarvis import interpretar_con_llm
from jarvis.herramientas_jarvis import (REGISTRO_HERRAMIENTAS, crear_plan,
                                 inferir_capacidad, registrar)


_contador_respuestas = 0
DEBUG_JARVIS = os.getenv('JARVIS_DEBUG','').lower() in ('1','true','si')
_traza_local = threading.local()


def _inicio_amable():
    global _contador_respuestas
    opciones = ("Claro.", "Sí, lo encontré.", "Por supuesto.")
    inicio = opciones[_contador_respuestas % len(opciones)]
    _contador_respuestas += 1
    return inicio


def formatear_respuesta_stock(nombre, stock, stock_minimo):
    stock_texto=format(stock,'f') if hasattr(stock,'as_tuple') else str(stock)
    if '.' in stock_texto: stock_texto=stock_texto.rstrip('0').rstrip('.')
    if stock == 0:
        return f"{_inicio_amable()} {nombre} se encuentra agotado."
    if stock <= stock_minimo:
        return (f"{_inicio_amable()} {nombre} tiene {stock_texto} unidades disponibles y está en stock bajo. "
                f"Su stock mínimo es {stock_minimo}.")
    return f"{_inicio_amable()} Actualmente hay {stock_texto} unidades de {nombre} disponibles."


def formatear_respuesta_ubicacion(nombre, ubicaciones):
    if not ubicaciones:
        return f"Revisé el inventario. {nombre} no tiene existencias disponibles actualmente."
    if len(ubicaciones) == 1:
        fila = ubicaciones[0]
        return f"{_inicio_amable()} {nombre} está ubicado en {fila.codigo_ubicacion}, con {fila.cantidad} unidades."
    partes = [f"{fila.codigo_ubicacion} con {fila.cantidad} unidades" for fila in ubicaciones]
    return f"{_inicio_amable()} {nombre} está disponible en:\n- " + "\n- ".join(partes) + "."


def formatear_respuesta_error(mensaje):
    return f"No pude completar la consulta. {mensaje}"


def formatear_respuesta_ayuda():
    return ("Puedo consultar productos, stock, ubicaciones, movimientos, empleados, "
            "rostros registrados, alertas, anomalías, predicciones, conteos y estado de servicios. "
            "También puedo generar reportes y localizar con LEDs. Las entradas, salidas, transferencias, ajustes, aplicación de conteos, "
            "atención de alertas y cambios de vigilancia requieren tu confirmación.")


class ConversationState(dict):
    """Memoria acotada de una conversación; no persiste stock ni historial en SQL."""
    def __init__(self):
        super().__init__()
        self.lock=threading.RLock()
        self.turnos=deque(maxlen=20)
        self.limpiar()

    def limpiar(self):
        self.clear();self.turnos.clear()
        if hasattr(self,'eventos'):self.eventos.clear()
        self.update(ultimo_producto_id=None,ultimo_producto_nombre=None,
            ultimo_empleado_id=None,ultimo_empleado_nombre=None,ultimo_subject=None,
            ultima_alerta=None,ultima_intencion=None,ultimo_dominio=None,
            ultima_categoria=None,ultimo_movimiento=None,ultimo_resultado=None,
            producto_anterior=None,candidatos_ambiguos=[],plan_pendiente=[],filtros_pendientes={},
            ultimo_plan_producto=['consultar_stock'],historial_corto_de_turnos=self.turnos,
            intencion_pendiente=None,entidad_pendiente=None,tipo_entidad_pendiente=None,
            estado_dialogo='IDLE',pregunta_incompleta=None,ultimo_tema=None,
            ultima_ubicacion=None,ultima_prediccion=None,ultima_anomalia=None,ultimo_empleado=None,producto_visual=None)
        self.update(plan_orquestador=None,confirmacion_pendiente=None,dominio_pendiente=None,
            referencias={},ultimos_resultados=[],ultima_accion=None)

    ALIAS = {'producto_actual':'ultimo_producto_id','empleado_actual':'ultimo_empleado_id',
        'ubicacion_actual':'ultima_ubicacion','movimiento_actual':'ultimo_movimiento',
        'alerta_actual':'ultima_alerta','anomalia_actual':'ultima_anomalia',
        'intencion_actual':'ultima_intencion','pending_intent':'intencion_pendiente',
        'pending_entity':'tipo_entidad_pendiente','pending_confirmation':'confirmacion_pendiente'}

    def __getitem__(self, clave):return super().__getitem__(self.ALIAS.get(clave,clave))
    def __setitem__(self, clave, valor):return super().__setitem__(self.ALIAS.get(clave,clave),valor)
    def get(self, clave, defecto=None):return super().get(self.ALIAS.get(clave,clave),defecto)

    def esperar(self, plan, tipo='producto', candidatos=None, filtros=None, pregunta=None):
        self.update(plan_pendiente=list(plan),intencion_pendiente=plan[-1] if plan else None,
            tipo_entidad_pendiente=tipo,entidad_pendiente=None,
            candidatos_ambiguos=list(candidatos or []),tipo_candidatos=tipo,
            filtros_pendientes=dict(filtros or {}),pregunta_incompleta=pregunta,
            estado_dialogo='WAITING_FOR_ANOMALY_SELECTION' if tipo=='anomalia' else 'WAITING_FOR_DISAMBIGUATION' if candidatos else
                'WAITING_FOR_PRODUCT' if tipo=='producto' else
                'WAITING_FOR_LOCATION' if tipo=='ubicacion' else 'WAITING_FOR_CLARIFICATION')
        if candidatos and tipo=='producto':self['lista_productos']=list(candidatos)

    def completar(self):
        self.update(plan_pendiente=[],intencion_pendiente=None,entidad_pendiente=None,
            tipo_entidad_pendiente=None,candidatos_ambiguos=[],filtros_pendientes={},
            pregunta_incompleta=None,estado_dialogo='IDLE',tipo_candidatos='producto',mapa_pendiente=False)

    def recordar_producto(self,producto,origen='previous_turn'):
        if self.get('ultimo_producto_id')!=producto['id_producto']:
            self['producto_anterior']={'id_producto':self.get('ultimo_producto_id'),'nombre':self.get('ultimo_producto_nombre')}
            self.pop('ultima_prediccion',None);self.pop('ultima_ubicacion',None)
        self.update(ultimo_producto_id=producto['id_producto'],ultimo_producto_nombre=producto.get('nombre'),
            ultima_categoria=producto.get('categoria'),origen_contexto=origen)


ConversationContext = ConversationState  # Compatibilidad, sin otra memoria.
_intent_router = IntentRouter()
_entity_resolver = EntityResolver(procesador_nlp)
_contexto_escritorio=ConversationState()
_contexto_actual=ContextVar('conversacion_jarvis',default=_contexto_escritorio)
_conversaciones={'escritorio':_contexto_escritorio}
_bloqueo_conversaciones=threading.RLock()

class _ReferenciaContexto(MutableMapping):
    def __getitem__(self,k):return _contexto_actual.get()[k]
    def __setitem__(self,k,v):_contexto_actual.get()[k]=v
    def __delitem__(self,k):del _contexto_actual.get()[k]
    def __iter__(self):return iter(_contexto_actual.get())
    def __len__(self):return len(_contexto_actual.get())

contexto_agente=_ReferenciaContexto()

def obtener_contexto(sesion='escritorio'):
    if sesion=='desktop':sesion='escritorio'
    if not isinstance(sesion,str) or not re.fullmatch(r'[a-zA-Z0-9:_-]{1,80}',sesion):
        raise ValueError('Identificador de conversación inválido.')
    with _bloqueo_conversaciones:
        if sesion not in _conversaciones:
            if len(_conversaciones)>=64:
                raise ValueError('Hay demasiadas conversaciones abiertas; reinicia el servicio.')
            _conversaciones[sesion]=ConversationContext()
        return _conversaciones[sesion]

def establecer_producto_visual(id_producto,nombre=None):
    """La UI solo entrega identidad; el siguiente turno consulta stock fresco en SQL."""
    ctx=obtener_contexto()
    with ctx.lock:
        ctx['producto_visual']={'id_producto':int(id_producto),'nombre':nombre}
        if ctx.get('ultimo_producto_id') is None and ctx['estado_dialogo']=='IDLE':
            ctx.recordar_producto(ctx['producto_visual'],'visual')
            ctx['contexto_visual_pendiente']=True

INTENCIONES_CON_PRODUCTO = {
    "consultar_stock", "consultar_ubicacion", "ultimo_retiro",
    "ultimo_movimiento", "historial_producto", "stock_minimo", "consultar_producto",
}


def _guardar_traza(**datos):
    actual = getattr(_traza_local, "datos", {})
    actual.update(datos)
    _traza_local.datos = actual

RESPUESTAS_SOCIALES = {
    "saludo": (
        "Hola, amigo. ¿En qué puedo ayudarte?",
        "Hola. Estoy listo para ayudarte con el inventario.",
        "Buenas. ¿Qué necesitas revisar?",
    ),
    "como_estas": (
        "Todo bien, amigo. ¿En qué puedo ayudarte?",
        "Todo bien por aquí. ¿Qué necesitas revisar?",
        "Estoy listo para ayudarte con el inventario. ¿Qué necesitas?",
    ),
    "agradecimiento": ("Con gusto, amigo.", "Para eso estoy.", "Cuando quieras."),
    "despedida": ("Hasta luego, amigo.", "Nos vemos. Aquí estaré cuando necesites algo."),
}

PALABRAS_IGNORADAS = {
    "a", "al", "de", "del", "el", "en", "esta", "estan", "hay", "la",
    "las", "lo", "los", "me", "mi", "mostrar", "muestrame", "para", "por",
    "producto", "productos", "puedo", "que", "se", "un", "una", "y",
    "actualmente", "almacen", "disponible", "disponibles", "queda", "quedan",
    "stock", "existencia", "existencias", "cantidad", "cuanto", "cuantos",
    "donde", "ubicacion", "ubicaciones", "seccion", "pasillo", "encontrar",
    "quien", "hizo", "realizo", "retiro", "retiro", "saco", "salida",
    "ultimo", "ultima", "ultimos", "ultimas", "movimiento", "movimientos",
    "historial", "tenemos", "tiene", "tienen",
    "jarvis", "jarbis", "yarvis", "hola", "hey", "oye", "buenas",
    "buenos", "dias", "tardes", "noches", "onda", "tal", "como",
    "estas", "andas", "amigo", "gracias", "favor", "minimo", "bajo",
    "precio", "cuesta", "cuestan", "categoria", "categorias", "cuando",
}


def _singular(palabra):
    if len(palabra) > 5 and palabra.endswith("es"):
        return palabra[:-2]
    if len(palabra) > 4 and palabra.endswith("s"):
        return palabra[:-1]
    return palabra


def detectar_intencion_inventario(pregunta):
    texto = normalizar_texto(pregunta)
    if not texto:
        return None
    if any(frase in texto for frase in ("stock bajo", "poco stock", "pocas existencias")):
        return "stock_bajo"
    if any(frase in texto for frase in ("agotados", "agotado", "sin existencias", "no tienen stock")):
        return "productos_agotados"
    if re.search(r"\b(?:ultimos movimientos|movimientos recientes)\b(?!\s+(?:de|del|para)\b)", texto):
        return "consultar_movimientos"
    if "historial" in texto or "movimientos del" in texto or "movimientos de" in texto:
        return "historial_producto"
    if ("ultimo retiro" in texto or "ultima salida" in texto or
            any(p in texto.split() for p in ("retiro", "retiro", "saco")) or
            ("quien" in texto and "retir" in texto)):
        return "ultimo_retiro"
    if "ultimo movimiento" in texto or "ultima movimiento" in texto or "cuando fue el ultimo" in texto:
        return "ultimo_movimiento"
    if any(p in texto.split() for p in ("donde", "ubicacion", "ubicaciones", "seccion", "pasillo", "encontrar")):
        return "consultar_ubicacion"
    if "stock minimo" in texto or "minimo de stock" in texto:
        return "stock_minimo"
    if any(p in texto.split() for p in ("cuanto", "cuantos", "stock", "existencias", "disponible", "disponibles", "quedan")):
        return "consultar_stock"
    return None


def detectar_conversacion_social(pregunta):
    texto = normalizar_texto(pregunta)
    if any(frase in texto for frase in ("como te llamas", "cual es tu nombre")):
        return "pregunta_nombre"
    if any(frase in texto for frase in ("quien eres", "presentate", "que eres")):
        return "presentacion"
    if any(frase in texto for frase in ("que puedo preguntarte", "que puedes hacer", "ayuda", "ayudame")):
        return "ayuda_general"
    if any(frase in texto for frase in ("gracias", "muchas gracias", "te agradezco")):
        return "agradecimiento"
    if any(frase in texto for frase in ("adios", "hasta luego", "nos vemos", "hasta pronto")):
        return "despedida"
    if any(frase in texto for frase in ("como estas", "como andas", "que onda", "que tal")):
        return "como_estas"
    if any(frase in texto for frase in ("hola", "hey", "oye", "buenas", "buenos dias", "buenas tardes", "buenas noches")):
        return "saludo"
    return None


def detectar_intencion(pregunta):
    resultado = procesador_nlp.interpretar(pregunta)
    if resultado.entidades.get("SUBJECT_NUMERO") is not None:
        return "consultar_subject"
    return (resultado.intencion or inferir_capacidad(resultado.texto_normalizado)
            or detectar_intencion_inventario(pregunta)
            or detectar_conversacion_social(pregunta) or "desconocida")


def generar_respuesta_social(intencion):
    if intencion in RESPUESTAS_SOCIALES:
        from jarvis.jarvis_personality import social
        return social(intencion)
    if intencion == "pregunta_nombre":
        return "Me llamo Jarvis, soy el asistente inteligente del sistema de inventario."
    if intencion == "presentacion":
        return ("Soy Jarvis, el asistente inteligente del sistema. Puedo ayudarte a consultar "
                "productos, stock, ubicaciones, movimientos y alertas.")
    if intencion == "ayuda_general":
        return formatear_respuesta_ayuda()
    return None


def _introduccion_social(pregunta):
    intencion = detectar_conversacion_social(pregunta)
    if intencion == "como_estas":
        return "Todo bien, amigo."
    if intencion == "saludo":
        return "Hola, amigo."
    return ""


def obtener_productos_activos():
    conexion = conectar()
    cursor = conexion.cursor()
    try:
        cursor.execute("""SELECT id_producto,codigo,nombre FROM productos
                          WHERE estado=1 AND fecha_eliminacion IS NULL ORDER BY nombre;""")
        return [{"id_producto": fila.id_producto, "codigo": fila.codigo,
                 "nombre": fila.nombre} for fila in cursor.fetchall()]
    finally:
        cursor.close()
        conexion.close()


def buscar_producto_en_pregunta(pregunta):
    # La entidad se extrae y valida contra el catálogo real de SQL Server.
    resultado = procesador_nlp.interpretar(pregunta)
    return procesador_nlp.resolver_producto(resultado, obtener_productos_activos())


def _es_seguimiento_contextual(pregunta):
    """Usa contexto solo cuando no se escribió claramente otro nombre de producto."""
    texto = normalizar_texto(pregunta)
    palabras_relevantes = [p for p in texto.split()
                           if p not in PALABRAS_IGNORADAS and len(p) >= 3]
    referencias = {"lo", "la", "los", "las", "ese", "esa", "ellos", "ellas"}
    return not palabras_relevantes or bool(referencias.intersection(texto.split()))


def consultar_stock_producto(id_producto):
    conexion = conectar(); cursor = conexion.cursor()
    try:
        cursor.execute("""SELECT p.nombre, p.stock_minimo,
                           COALESCE(SUM(e.cantidad), 0) AS stock_actual
                           FROM productos p LEFT JOIN existencias e ON e.id_producto=p.id_producto
                                                                  AND e.fecha_eliminacion IS NULL AND EXISTS(SELECT 1 FROM ubicaciones ua WHERE ua.id_ubicacion=e.id_ubicacion AND ua.estado=1 AND ua.fecha_eliminacion IS NULL)
                           WHERE p.id_producto=? AND p.fecha_eliminacion IS NULL
                           GROUP BY p.nombre,p.stock_minimo;""", id_producto)
        p = cursor.fetchone()
        if p is None: return "No encontré el producto solicitado."
        return formatear_respuesta_stock(p.nombre, p.stock_actual, p.stock_minimo)
    finally: cursor.close(); conexion.close()


def consultar_ubicaciones_producto(id_producto):
    conexion = conectar(); cursor = conexion.cursor()
    try:
        cursor.execute("SELECT nombre FROM productos WHERE id_producto=? AND fecha_eliminacion IS NULL;", id_producto)
        p = cursor.fetchone()
        if p is None: return "No encontré el producto solicitado."
        from inventory.mapa_almacen import ubicaciones_producto,describir_ubicacion
        from jarvis.jarvis_personality import respuesta_ubicaciones
        return respuesta_ubicaciones(ubicaciones_producto(id_producto),describir_ubicacion)[0]
    finally: cursor.close(); conexion.close()


def consultar_stock_minimo_producto(id_producto):
    conexion = conectar(); cursor = conexion.cursor()
    try:
        cursor.execute("""SELECT nombre, stock_minimo FROM productos
                          WHERE id_producto=? AND estado=1 AND fecha_eliminacion IS NULL;""", id_producto)
        producto = cursor.fetchone()
        if producto is None:
            return "No encontré el producto solicitado."
        return f"El stock mínimo de {producto.nombre} es de {producto.stock_minimo} unidades."
    finally:
        cursor.close(); conexion.close()


def _consultar_movimiento(id_producto, solo_salida):
    conexion = conectar(); cursor = conexion.cursor()
    try:
        filtro = " AND tm.nombre = 'Salida'" if solo_salida else ""
        cursor.execute("""SELECT TOP 1 p.nombre producto,tm.nombre tipo,d.cantidad,m.fecha_movimiento,
                           CONCAT(e.nombres,' ',e.apellidos) empleado,uo.codigo_ubicacion origen
                           FROM movimientos m JOIN tipos_movimiento tm ON tm.id_tipo_movimiento=m.id_tipo_movimiento
                           JOIN detalle_movimientos d ON d.id_movimiento=m.id_movimiento
                           JOIN productos p ON p.id_producto=d.id_producto
                           JOIN empleados e ON e.id_empleado=m.id_empleado
                           LEFT JOIN ubicaciones uo ON uo.id_ubicacion=d.id_ubicacion_origen
                           WHERE d.id_producto=? AND m.fecha_eliminacion IS NULL
                             AND d.fecha_eliminacion IS NULL""" + filtro +
                       " ORDER BY m.fecha_movimiento DESC,m.id_movimiento DESC;", id_producto)
        return cursor.fetchone()
    finally: cursor.close(); conexion.close()


def consultar_ultimo_retiro(id_producto):
    m = _consultar_movimiento(id_producto, True)
    if m is None: return "No hay salidas registradas para este producto."
    fecha = m.fecha_movimiento.strftime("%d/%m/%Y a las %H:%M")
    origen = f" desde la ubicación {m.origen}" if m.origen else ""
    return (f"La última salida de {m.producto} fue realizada por {m.empleado} el {fecha}, "
            f"con una cantidad de {m.cantidad} unidades{origen}.")


def consultar_ultimo_movimiento(id_producto):
    m = _consultar_movimiento(id_producto, False)
    if m is None: return "No hay movimientos registrados para este producto."
    fecha = m.fecha_movimiento.strftime("%d/%m/%Y a las %H:%M")
    return (f"El último movimiento de {m.producto} fue {m.tipo}, realizado por {m.empleado} "
            f"el {fecha} por {m.cantidad} unidades.")


def _productos_por_estado(agotados):
    conexion = conectar(); cursor = conexion.cursor()
    try:
        operador = "= 0" if agotados else "> 0 AND COALESCE(SUM(e.cantidad),0) <= p.stock_minimo"
        cursor.execute("""SELECT p.nombre,COALESCE(SUM(e.cantidad),0) stock,p.stock_minimo
                           FROM productos p LEFT JOIN existencias e ON e.id_producto=p.id_producto
                                                                  AND e.fecha_eliminacion IS NULL AND EXISTS(SELECT 1 FROM ubicaciones ua WHERE ua.id_ubicacion=e.id_ubicacion AND ua.estado=1 AND ua.fecha_eliminacion IS NULL)
                           WHERE p.estado=1 AND p.fecha_eliminacion IS NULL
                           GROUP BY p.id_producto,p.nombre,p.stock_minimo
                           HAVING COALESCE(SUM(e.cantidad),0) """ + operador + " ORDER BY p.nombre;")
        return cursor.fetchall()
    finally: cursor.close(); conexion.close()


def consultar_productos_stock_bajo():
    filas = _productos_por_estado(False)
    if not filas: return "Actualmente no hay productos con stock bajo."
    return f"Actualmente hay {len(filas)} productos con stock bajo:\n\n" + "\n".join(
        f"- {f.nombre}: {f.stock} unidades, mínimo {f.stock_minimo}." for f in filas)


def consultar_productos_agotados():
    filas = _productos_por_estado(True)
    if not filas: return "Actualmente no hay productos agotados."
    return "Actualmente están agotados:\n\n" + "\n".join(f"- {f.nombre}" for f in filas)


def consultar_historial_producto(id_producto):
    conexion = conectar(); cursor = conexion.cursor()
    try:
        cursor.execute("SELECT nombre FROM productos WHERE id_producto=?;", id_producto); p = cursor.fetchone()
        cursor.execute("""SELECT TOP 10 m.fecha_movimiento,tm.nombre tipo,d.cantidad,
                           CONCAT(e.nombres,' ',e.apellidos) empleado
                           FROM movimientos m JOIN tipos_movimiento tm ON tm.id_tipo_movimiento=m.id_tipo_movimiento
                           JOIN detalle_movimientos d ON d.id_movimiento=m.id_movimiento
                           JOIN empleados e ON e.id_empleado=m.id_empleado
                           WHERE d.id_producto=? AND m.fecha_eliminacion IS NULL
                             AND d.fecha_eliminacion IS NULL
                           ORDER BY m.fecha_movimiento DESC,m.id_movimiento DESC;""", id_producto)
        filas = cursor.fetchall()
        if not filas: return f"No hay movimientos registrados para {p.nombre}."
        lineas = [f"{i}. {f.fecha_movimiento:%d/%m/%Y} - {f.tipo} - {f.cantidad} unidades - {f.empleado}"
                  for i, f in enumerate(filas, 1)]
        return f"Últimos movimientos de {p.nombre}:\n\n" + "\n".join(lineas)
    finally: cursor.close(); conexion.close()


def obtener_empleados_activos():
    conexion = conectar(); cursor = conexion.cursor()
    try:
        cursor.execute("""SELECT id_empleado,codigo_empleado,
                          CONCAT(nombres,' ',apellidos) nombre,cargo,fecha_creacion
                          FROM empleados WHERE estado=1 AND fecha_eliminacion IS NULL
                          ORDER BY nombres,apellidos;""")
        return [{"id_empleado": f.id_empleado, "codigo_empleado": f.codigo_empleado,
                 "nombre": f.nombre, "cargo": f.cargo,"fecha_creacion":f.fecha_creacion} for f in cursor.fetchall()]
    finally: cursor.close(); conexion.close()


def consultar_empleado_por_id(id_empleado):
    conexion = conectar(); cursor = conexion.cursor()
    try:
        cursor.execute("""SELECT codigo_empleado,CONCAT(nombres,' ',apellidos) nombre,cargo
                          FROM empleados WHERE id_empleado=? AND estado=1
                          AND fecha_eliminacion IS NULL;""", id_empleado)
        fila = cursor.fetchone()
        if not fila:
            return "No encontré un empleado activo con ese nombre."
        cargo = fila.cargo or "sin cargo registrado"
        return f"{fila.nombre} tiene el código {fila.codigo_empleado} y figura como {cargo}."
    finally: cursor.close(); conexion.close()


def consultar_alertas_pendientes():
    conexion = conectar(); cursor = conexion.cursor()
    try:
        cursor.execute("""SELECT TOP 5 ta.nombre tipo,a.nivel,a.mensaje
                          FROM alertas a JOIN tipos_alerta ta ON ta.id_tipo_alerta=a.id_tipo_alerta
                          WHERE a.atendida=0 AND a.fecha_eliminacion IS NULL
                          ORDER BY a.fecha_creacion DESC;""")
        filas = cursor.fetchall()
        if not filas: return "No hay alertas pendientes actualmente."
        return f"Hay {len(filas)} alertas pendientes recientes:\n\n" + "\n".join(
            f"- {f.tipo} ({f.nivel}): {f.mensaje}" for f in filas)
    finally: cursor.close(); conexion.close()


def consultar_movimientos_recientes():
    conexion = conectar(); cursor = conexion.cursor()
    try:
        cursor.execute("""SELECT TOP 5 m.fecha_movimiento,tm.nombre tipo,p.nombre producto,d.cantidad
                          FROM movimientos m JOIN tipos_movimiento tm ON tm.id_tipo_movimiento=m.id_tipo_movimiento
                          JOIN detalle_movimientos d ON d.id_movimiento=m.id_movimiento
                          JOIN productos p ON p.id_producto=d.id_producto
                          WHERE m.fecha_eliminacion IS NULL AND d.fecha_eliminacion IS NULL
                          ORDER BY m.fecha_movimiento DESC,m.id_movimiento DESC;""")
        filas = cursor.fetchall()
        if not filas: return "No hay movimientos registrados."
        return "Movimientos más recientes:\n\n" + "\n".join(
            f"- {f.fecha_movimiento:%d/%m/%Y}: {f.tipo}, {f.producto}, {f.cantidad} unidades." for f in filas)
    finally: cursor.close(); conexion.close()


def consultar_resumen_inventario():
    conexion = conectar(); cursor = conexion.cursor()
    try:
        cursor.execute("""SELECT COUNT(DISTINCT p.id_producto) productos,
                          COALESCE(SUM(e.cantidad),0) unidades
                          FROM productos p LEFT JOIN existencias e ON e.id_producto=p.id_producto
                          AND e.fecha_eliminacion IS NULL AND EXISTS(SELECT 1 FROM ubicaciones ua WHERE ua.id_ubicacion=e.id_ubicacion AND ua.estado=1 AND ua.fecha_eliminacion IS NULL)
                          WHERE p.estado=1 AND p.fecha_eliminacion IS NULL;""")
        fila = cursor.fetchone()
        return f"El inventario activo contiene {fila.productos} productos y {fila.unidades} unidades en total."
    finally: cursor.close(); conexion.close()


def consultar_movimientos_empleado(id_empleado):
    conexion = conectar(); cursor = conexion.cursor()
    try:
        cursor.execute("""SELECT TOP 10 m.fecha_movimiento,tm.nombre tipo,p.nombre producto,d.cantidad
                          FROM movimientos m JOIN tipos_movimiento tm ON tm.id_tipo_movimiento=m.id_tipo_movimiento
                          JOIN detalle_movimientos d ON d.id_movimiento=m.id_movimiento
                          JOIN productos p ON p.id_producto=d.id_producto
                          WHERE m.id_empleado=? AND m.fecha_eliminacion IS NULL
                            AND d.fecha_eliminacion IS NULL
                          ORDER BY m.fecha_movimiento DESC,m.id_movimiento DESC;""", id_empleado)
        filas = cursor.fetchall()
        if not filas: return "Ese empleado no tiene movimientos registrados."
        return "Movimientos recientes del empleado:\n\n" + "\n".join(
            f"- {f.fecha_movimiento:%d/%m/%Y}: {f.tipo}, {f.producto}, {f.cantidad} unidades." for f in filas)
    finally: cursor.close(); conexion.close()


def consultar_predicciones_agotamiento(id_producto=None):
    from core.automatizacion_inventario import obtener_prediccion as predecir_agotamiento
    productos = obtener_productos_activos()
    if id_producto is not None:
        productos = [p for p in productos if p["id_producto"] == id_producto]
    riesgos, insuficientes = [], 0
    for producto in productos:
        # El agente conversacional es de solo lectura: no crea ni atiende alertas.
        resultado = predecir_agotamiento(
            producto["id_producto"], actualizar_alertas=False
        )
        if not resultado.get("datos_suficientes"):
            insuficientes += 1
            continue
        estado = str(resultado.get("estado") or "")
        dias = resultado.get("dias_restantes_promedio")
        if dias is not None:
            detalle = f"{dias:.1f} días" if isinstance(dias, (int, float)) else estado
            riesgos.append((dias,f"- {producto['nombre']}: {detalle} ({estado})."))
    if riesgos:
        return "Productos ordenados por agotamiento estimado (primero el más próximo):\n\n" + "\n".join(texto for _,texto in sorted(riesgos))
    if id_producto is not None and insuficientes:
        return "No hay suficientes movimientos históricos para estimar el agotamiento de ese producto."
    if insuficientes == len(productos):
        return "No hay suficientes movimientos históricos para estimar agotamientos."
    return "Las predicciones actuales no muestran productos con riesgo de agotamiento."


def consultar_anomalias_inventario():
    from ai.anomalies.deteccion_anomalias import analizar_movimientos,listar_anomalias
    filas = listar_anomalias()
    cantidad = len(filas)
    if cantidad == 0:
        return "No hay anomalías registradas. El servicio evalúa los movimientos nuevos automáticamente."
    detalle = "\n".join(
        f"- {f.get('fecha')}: {f.get('producto')} — {f.get('nivel')}: {f.get('motivo')}" for f in filas[:5])
    return f"Se detectaron {cantidad} anomalías:\n\n{detalle}"


def _normalizar_subject(pregunta_o_etiqueta):
    """Resuelve sujeto 3/subject03 contra las etiquetas reales sin asumir relleno."""
    texto = normalizar_texto(pregunta_o_etiqueta)
    coincidencia = re.search(r"\b(?:subject|sujeto|persona)\s*0*(\d{1,6})\b", texto)
    if not coincidencia:
        return None
    numero = int(coincidencia.group(1))
    from ai.facial.rostros_empleados import listar_etiquetas_disponibles, listar_relaciones
    etiquetas = {str(r.get("etiqueta_modelo") or "").lower()
                 for r in listar_relaciones() if r.get("etiqueta_modelo")}
    etiquetas.update(e.lower() for e in listar_etiquetas_disponibles(incluir_asignadas=True))
    reales = sorted(e for e in etiquetas
                   if re.fullmatch(r"subject0*" + str(numero), e, re.IGNORECASE))
    return reales[0] if reales else f"subject{numero}"


def consultar_subject(pregunta_o_etiqueta):
    from ai.facial.rostros_empleados import listar_etiquetas_disponibles, obtener_empleado_por_etiqueta
    etiqueta = _normalizar_subject(pregunta_o_etiqueta)
    if not etiqueta:
        return "No pude identificar el número del subject que deseas consultar."
    empleado = obtener_empleado_por_etiqueta(etiqueta)
    if empleado:
        cargo = empleado.get("cargo") or "sin cargo registrado"
        return (f"El {etiqueta} corresponde a {empleado['nombre']}, código "
                f"{empleado['codigo_empleado']}, {cargo}.")
    etiquetas = {e.lower() for e in listar_etiquetas_disponibles(incluir_asignadas=True)}
    if etiqueta.lower() in etiquetas:
        return f"El {etiqueta} existe en el modelo, pero todavía no está asociado a un empleado activo."
    return f"No encontré {etiqueta} registrado."


def consultar_rostro_empleado(id_empleado):
    from ai.facial.rostros_empleados import listar_relaciones
    relaciones = [r for r in listar_relaciones() if r["id_empleado"] == id_empleado]
    if not relaciones:
        return "El empleado no tiene un rostro registrado."
    relacion = relaciones[0]
    etiqueta = relacion.get("etiqueta_modelo")
    if etiqueta and relacion.get("relacion_activa"):
        return f"{relacion['nombre']} tiene el rostro {etiqueta} registrado y activo."
    return f"{relacion['nombre']} no tiene un rostro activo registrado."


def listar_estado_rostros(solo_sin_rostro=False):
    from ai.facial.rostros_empleados import listar_relaciones
    relaciones = listar_relaciones()
    seleccionadas = [r for r in relaciones
                     if bool(r.get("etiqueta_modelo") and r.get("relacion_activa")) != solo_sin_rostro]
    if not seleccionadas:
        return ("Todos los empleados activos tienen rostro registrado."
                if solo_sin_rostro else "No hay empleados con rostro registrado.")
    if solo_sin_rostro:
        return "Empleados sin rostro registrado:\n\n" + "\n".join(
            f"- {r['nombre']} ({r['codigo_empleado']})." for r in seleccionadas)
    return "Empleados con rostro registrado:\n\n" + "\n".join(
        f"- {r['nombre']}: {r['etiqueta_modelo']}." for r in seleccionadas)


def consultar_catalogo_productos():
    from inventory.productos import listar_productos
    filas = listar_productos()
    if not filas:
        return "No hay productos activos registrados."
    return f"Hay {len(filas)} productos activos:\n\n" + "\n".join(
        f"- {p['nombre']}: {p['stock_actual']} {p['unidad_medida']}." for p in filas[:20])


def consultar_producto_menor_stock():
    from inventory.productos import listar_productos
    filas = listar_productos()
    if not filas:
        return "No hay productos activos registrados."
    minimo = min(p["stock_actual"] for p in filas)
    productos = [p for p in filas if p["stock_actual"] == minimo]
    nombres = ", ".join(p["nombre"] for p in productos)
    return f"El menor stock es de {minimo} unidades y corresponde a: {nombres}."


def consultar_detalle_producto(id_producto):
    from inventory.productos import obtener_producto_por_id
    producto = obtener_producto_por_id(id_producto)
    if not producto:
        return "No encontré ese producto activo."
    descripcion = producto.get("descripcion") or "sin descripción"
    return (f"{producto['nombre']} ({producto['codigo']}) pertenece a {producto['categoria']}; "
            f"tiene {producto['stock_actual']} {producto['unidad_medida']}, "
            f"stock mínimo {producto['stock_minimo']} y está {producto['estado'].lower()}. "
            f"Descripción: {descripcion}.")


def consultar_movimientos_hoy():
    from datetime import date
    from inventory.movimientos import buscar_movimientos
    hoy = date.today().isoformat()
    filas = buscar_movimientos(fecha_desde=hoy, fecha_hasta=hoy)
    if not filas:
        return "No hay movimientos registrados hoy."
    return "Movimientos de hoy:\n\n" + "\n".join(
        f"- {f['tipo_movimiento']}: {f['producto']}, {f['cantidad']} unidades, {f['empleado']}."
        for f in filas[:15])


def consultar_alertas_reconocimiento():
    from inventory.alertas import listar_alertas
    filas = [a for a in listar_alertas(solo_pendientes=True)
             if normalizar_texto(a.get("tipo")) == "empleado no reconocido"]
    if not filas:
        return "No hay alertas pendientes de personas no reconocidas."
    return f"Hay {len(filas)} alertas pendientes de personas no reconocidas:\n\n" + "\n".join(
        f"- {a['mensaje']}" for a in filas[:10])


def consultar_alertas_filtradas(nivel=None, solo_stock=False):
    from inventory.alertas import listar_alertas
    filas = listar_alertas(solo_pendientes=True)
    if nivel:
        filas = [a for a in filas if normalizar_texto(a.get("nivel")) == normalizar_texto(nivel)]
    if solo_stock:
        tipos_stock = {"stock bajo", "producto agotado", "stock excedido", "proximo a agotarse"}
        filas = [a for a in filas if normalizar_texto(a.get("tipo")) in tipos_stock]
    if not filas:
        detalle = " de stock" if solo_stock else ""
        detalle += f" de nivel {nivel}" if nivel else ""
        return f"No hay alertas pendientes{detalle}."
    return f"Encontré {len(filas)} alertas pendientes:\n\n" + "\n".join(
        f"- {a['tipo']} ({a['nivel']}): {a['mensaje']}" for a in filas[:10])


def consultar_reabastecimiento():
    """Combina stock mínimo y predicción real, sin crear alertas."""
    from core.automatizacion_inventario import obtener_prediccion as predecir_agotamiento
    from inventory.productos import listar_productos
    productos = listar_productos()
    recomendaciones, insuficientes = [], 0
    for producto in productos:
        razones = []
        if producto["stock_actual"] <= producto["stock_minimo"]:
            razones.append(f"stock {producto['stock_actual']} / mínimo {producto['stock_minimo']}")
        prediccion = predecir_agotamiento(producto["id_producto"], actualizar_alertas=False)
        if not prediccion.get("datos_suficientes"):
            insuficientes += 1
        elif normalizar_texto(prediccion.get("estado")) == "proximo a agotarse":
            dias = prediccion.get("dias_restantes_promedio")
            razones.append(f"agotamiento estimado en {dias:.1f} días" if dias is not None
                           else "riesgo de agotamiento")
        if razones:
            recomendaciones.append(f"- {producto['nombre']}: " + "; ".join(razones) + ".")
    if recomendaciones:
        return "Conviene revisar el reabastecimiento de:\n\n" + "\n".join(recomendaciones)
    if productos and insuficientes == len(productos):
        return "No hay suficiente historial para calcular una predicción confiable."
    return "Por ahora no detecto productos con riesgo próximo de agotamiento."


def consultar_estado_general():
    """Compone un diagnóstico real sin permitir que el LLM fabrique cifras."""
    consultas = (
        ("resumen", consultar_resumen_inventario),
        ("stock bajo", consultar_productos_stock_bajo),
        ("agotados", consultar_productos_agotados),
        ("alertas", consultar_alertas_pendientes),
        ("predicción", consultar_predicciones_agotamiento),
        ("anomalías", consultar_anomalias_inventario),
    )
    resultados = []
    for nombre, funcion in consultas:
        try:
            resultados.append(funcion())
        except Exception:
            print(f"No se pudo completar {nombre} en el resumen general.")
            traceback.print_exc()
            resultados.append(f"No pude consultar {nombre} en este momento.")
    return "\n\n".join(resultados)


def consultar_contenido_ubicacion(codigo):
    from inventory.inventario_service import consultar
    lugares=consultar('SELECT id_ubicacion,codigo_ubicacion FROM ubicaciones WHERE codigo_ubicacion COLLATE Latin1_General_CI_AI=? AND estado=1 AND fecha_eliminacion IS NULL',codigo)
    if not lugares: return f'No encontré una ubicación activa llamada {codigo}.'
    filas=consultar('SELECT p.codigo,p.nombre,e.cantidad,p.unidad_medida FROM existencias e JOIN productos p ON p.id_producto=e.id_producto WHERE e.id_ubicacion=? AND e.fecha_eliminacion IS NULL AND p.estado=1 AND p.fecha_eliminacion IS NULL AND e.cantidad>0 ORDER BY p.nombre',lugares[0]['id_ubicacion'])
    if not filas: return f"La ubicación {lugares[0]['codigo_ubicacion']} no tiene productos con stock disponible."
    return f"Contenido de {lugares[0]['codigo_ubicacion']}:\n"+'\n'.join(f"- {p['codigo']} · {p['nombre']}: {p['cantidad']} {p['unidad_medida']}." for p in filas)


def consultar_productos_mas_movidos_mes():
    from inventory.inventario_service import consultar
    filas=consultar("""SELECT TOP 10 p.codigo,p.nombre,SUM(d.cantidad) cantidad
        FROM detalle_movimientos d JOIN movimientos m ON m.id_movimiento=d.id_movimiento
        JOIN productos p ON p.id_producto=d.id_producto
        JOIN tipos_movimiento tm ON tm.id_tipo_movimiento=m.id_tipo_movimiento
        WHERE m.fecha_movimiento>=DATEFROMPARTS(YEAR(SYSDATETIME()),MONTH(SYSDATETIME()),1)
        AND m.fecha_movimiento<=SYSDATETIME() AND m.fecha_eliminacion IS NULL AND d.fecha_eliminacion IS NULL
        AND tm.nombre IN('Entrada','Salida') GROUP BY p.codigo,p.nombre ORDER BY cantidad DESC""")
    if not filas: return 'Sin datos suficientes: no hay entradas ni salidas registradas este mes.'
    return 'Productos con mayor movimiento este mes (entradas + salidas, sin transferencias):\n'+'\n'.join(f"- {p['codigo']} · {p['nombre']}: {p['cantidad']}." for p in filas)


def consultar_producto_mayor_stock():
    from inventory.inventario_service import buscar_inventario
    filas=buscar_inventario()
    if not filas: return 'No hay productos activos en el inventario.'
    mayor=max(p['stock_actual'] for p in filas)
    return 'Mayor stock disponible:\n'+'\n'.join(f"- {p['nombre']}: {p['stock_actual']} {p['unidad_medida']}." for p in filas if p['stock_actual']==mayor)


HERRAMIENTAS = {
    "contenido_ubicacion": consultar_contenido_ubicacion,
    "mas_movidos_mes": consultar_productos_mas_movidos_mes,
    "mayor_stock": consultar_producto_mayor_stock,
    "consultar_stock": consultar_stock_producto,
    "consultar_ubicacion": consultar_ubicaciones_producto,
    "ultimo_movimiento": consultar_ultimo_movimiento,
    "ultimo_retiro": consultar_ultimo_retiro,
    "historial_producto": consultar_historial_producto,
    "consultar_stock_bajo": consultar_productos_stock_bajo,
    "stock_bajo": consultar_productos_stock_bajo,
    "consultar_agotados": consultar_productos_agotados,
    "productos_agotados": consultar_productos_agotados,
    "consultar_alertas": consultar_alertas_pendientes,
    "consultar_movimientos": consultar_movimientos_recientes,
    "consultar_empleado": consultar_empleado_por_id,
    "consultar_movimientos_empleado": consultar_movimientos_empleado,
    "movimientos_empleado": consultar_movimientos_empleado,
    "resumen_inventario": consultar_estado_general,
    "consultar_prediccion_stock": consultar_predicciones_agotamiento,
    "prediccion_agotamiento": consultar_predicciones_agotamiento,
    "consultar_subject": consultar_subject,
    "consultar_rostro_empleado": consultar_rostro_empleado,
    "consultar_producto": consultar_detalle_producto,
    "listar_productos": consultar_catalogo_productos,
    "producto_menor_stock": consultar_producto_menor_stock,
    "consultar_reabastecimiento": consultar_reabastecimiento,
    "consultar_anomalias": consultar_anomalias_inventario,
    "alertas_reconocimiento": consultar_alertas_reconocimiento,
    "consultar_alertas_filtradas": consultar_alertas_filtradas,
    "movimientos_hoy": consultar_movimientos_hoy,
}

_METADATOS_HERRAMIENTAS = {
    "contenido_ubicacion": ("Consulta los productos de una ubicación registrada.", ("codigo",), "ubicacion"),
    "consultar_empleado": ("Obtiene un empleado por identificador registrado.", ("id_empleado",), "empleado"),
    "movimientos_empleado": ("Consulta movimientos de un empleado.", ("id_empleado",), "movimiento"),
    "consultar_stock": ("Obtiene el stock actual total de un producto.", ("id_producto",), "producto"),
    "consultar_ubicacion": ("Obtiene las ubicaciones y cantidades de un producto.", ("id_producto",), "producto"),
    "consultar_producto": ("Obtiene código, categoría, precio, stock y estado.", ("id_producto",), "producto"),
    "ultimo_movimiento": ("Obtiene el movimiento más reciente de un producto.", ("id_producto",), "movimiento"),
    "ultimo_retiro": ("Obtiene la última salida, empleado, fecha y cantidad.", ("id_producto",), "movimiento"),
    "historial_producto": ("Lista el historial real de un producto.", ("id_producto",), "movimiento"),
    "consultar_subject": ("Obtiene el empleado asociado a un subject facial.", ("pregunta_o_etiqueta",), "subject"),
    "consultar_rostro_empleado": ("Consulta el subject facial de un empleado.", ("id_empleado",), "rostro"),
    "consultar_movimientos_empleado": ("Lista movimientos de un empleado.", ("id_empleado",), "movimiento"),
    "consultar_prediccion_stock": ("Calcula riesgo de agotamiento con datos históricos.", (), "prediccion"),
    "consultar_reabastecimiento": ("Combina stock mínimo y predicción para sugerir revisión.", (), "prediccion"),
    "consultar_anomalias": ("Analiza movimientos reales mediante detección de anomalías.", (), "anomalia"),
    "consultar_alertas": ("Lista alertas pendientes reales.", (), "alerta"),
    "resumen_inventario": ("Combina estado, alertas, predicción y anomalías.", (), "inventario"),
}
for _nombre, _funcion in HERRAMIENTAS.items():
    _descripcion, _parametros, _entidad = _METADATOS_HERRAMIENTAS.get(
        _nombre, (f"Ejecuta la consulta segura {_nombre}.", (), "inventario")
    )
    registrar(_nombre, _descripcion, _parametros, _entidad, _funcion)


def reiniciar_contexto(sesion='escritorio'):
    ctx=obtener_contexto(sesion)
    with ctx.lock:ctx.limpiar()


def _respuesta_ayuda():
    return formatear_respuesta_ayuda()


def _ejecutar_herramienta_segura(nombre, funcion, *argumentos):
    try:
        definicion = REGISTRO_HERRAMIENTAS.get(nombre)
        if definicion is None:
            _guardar_traza(motivo_fallback="HERRAMIENTA_NO_ENCONTRADA")
            return "No tengo una herramienta autorizada para esa consulta."
        # El nombre debe estar autorizado; la función solo la aporta el orquestador Python.
        resultado = funcion(*argumentos)
        _guardar_traza(herramienta=nombre, resultado=resultado)
        return resultado
    except Exception:
        print(f"Error técnico en herramienta Jarvis: {nombre}")
        traceback.print_exc()
        mensajes = {
            "consultar_prediccion_stock": "Tuve un problema al consultar la predicción de stock.",
            "consultar_reabastecimiento": "Tuve un problema al consultar el reabastecimiento.",
            "consultar_anomalias": "Tuve un problema al analizar las anomalías del inventario.",
            "consultar_subject": "Tuve un problema al consultar el registro facial.",
            "consultar_alertas": "Tuve un problema al consultar las alertas.",
        }
        return mensajes.get(nombre, "Tuve un problema al consultar esa información.")


def _procesar_pregunta_compatibilidad(pregunta):
    _traza_local.datos = {"mensaje": pregunta, "origen": "NLP local", "entidades": {}}
    pregunta_normalizada = normalizar_texto(pregunta)
    if not pregunta_normalizada:
        return "No entendí bien eso, amigo. Puedes preguntarme por stock, ubicaciones, movimientos o alertas."

    acciones_prohibidas = re.compile(
        r"\b(?:borra(?:r)?|elimina(?:r)?|actualiza(?:r)?|modifica(?:r)?|crea(?:r)?|"
        r"inserta(?:r)?|drop|delete|update|insert|truncate)\b",
        re.IGNORECASE,
    )
    if acciones_prohibidas.search(pregunta_normalizada):
        _guardar_traza(intencion="accion_no_permitida", tiempo_nlp=0.0, tiempo_llm=0.0)
        return ("Por seguridad, Jarvis solo realiza consultas de lectura. "
                "No puedo crear, modificar ni eliminar datos del inventario.")

    ubicacion=re.search(r'\b(?:que hay|contenido|productos)\s+(?:en\s+)?(?:la\s+)?ubicacion\s+([a-z0-9-]+)',pregunta_normalizada)
    if ubicacion:
        return _ejecutar_herramienta_segura('contenido_ubicacion',consultar_contenido_ubicacion,ubicacion.group(1))
    if re.search(r'\b(?:mas movidos|mayor movimiento|movieron mas)\b',pregunta_normalizada) and 'mes' in pregunta_normalizada:
        return _ejecutar_herramienta_segura('mas_movidos_mes',consultar_productos_mas_movidos_mes)
    if re.search(r'\b(?:mayor stock|mas stock)\b',pregunta_normalizada):
        return _ejecutar_herramienta_segura('mayor_stock',consultar_producto_mayor_stock)
    if re.search(r'\b(?:agotarse primero|primero en agotarse)\b',pregunta_normalizada):
        return _ejecutar_herramienta_segura('consultar_prediccion_stock',consultar_predicciones_agotamiento)
    try:
        inicio_nlp = time.perf_counter()
        analisis = procesador_nlp.interpretar(pregunta)
        intencion = analisis.intencion
        # Señales inequívocas tienen prioridad también cuando el LLM está ausente.
        if re.search(r"\b(?:ultimos movimientos|movimientos recientes)\b(?!\s+(?:de|del|para)\b)", pregunta_normalizada):
            intencion = "consultar_movimientos"
        elif analisis.entidades.get("SUBJECT_NUMERO") is not None:
            intencion = "consultar_subject"
        elif re.search(r"\b(comprar|reabastecer|reabastecimiento|reponer|se va a acabar)\b",
                       pregunta_normalizada):
            intencion = "consultar_reabastecimiento"
        elif re.search(r"\b(personas?|empleados?) no reconocid", pregunta_normalizada):
            intencion = "alertas_reconocimiento"
        elif re.search(r"\b(anomalia|anomalias|raro|raros|extrano|extranos|inusual)\b",
                       pregunta_normalizada):
            intencion = "consultar_anomalias"
        tiempo_nlp = time.perf_counter() - inicio_nlp
        _guardar_traza(intencion=intencion, confianza=analisis.confianza, tiempo_nlp=tiempo_nlp)

        if intencion in {"saludo", "agradecimiento", "despedida", "pregunta_nombre", "ayuda"}:
            social_equivalente = "ayuda_general" if intencion == "ayuda" else intencion
            return generar_respuesta_social(social_equivalente)

        decision_llm, tiempo_llm, error_llm = interpretar_con_llm(pregunta, contexto_agente)
        plan_llm = []
        texto_resolucion = pregunta
        if decision_llm:
            intencion = decision_llm["intencion"]
            plan_llm = decision_llm.get("acciones", [])
            entidades_llm = decision_llm["entidades"]
            texto_resolucion += " " + " ".join(v for v in entidades_llm.values() if v)
            analisis = procesador_nlp.interpretar(texto_resolucion)
            _guardar_traza(origen="LLM local", intencion=intencion, entidades=entidades_llm,
                           tiempo_llm=tiempo_llm)
        else:
            _guardar_traza(tiempo_llm=tiempo_llm, error_llm=error_llm,
                           motivo_fallback="LLM_NO_DISPONIBLE" if error_llm else None)
        # Las entidades inequívocas siguen teniendo prioridad sobre una salida LLM errónea.
        if analisis.entidades.get("SUBJECT_NUMERO") is not None:
            intencion = "consultar_subject"
        elif re.search(r"\b(comprar|reabastecer|reabastecimiento|reponer|se va a acabar)\b",
                       pregunta_normalizada):
            intencion = "consultar_reabastecimiento"
        # Las reglas antiguas quedan únicamente como respaldo ante baja confianza.
        if not intencion:
            _guardar_traza(motivo_fallback="INTENCION_NO_DETECTADA")
            intencion = (inferir_capacidad(pregunta_normalizada)
                         or detectar_intencion_inventario(pregunta)
                         or detectar_conversacion_social(pregunta))
        if (not intencion and contexto_agente["ultimo_producto_id"]
                and pregunta_normalizada in {"cuando", "y cuando", "cuando fue"}):
            intencion = "ultimo_movimiento"
            _guardar_traza(intencion=intencion)
        plan = plan_llm or crear_plan(intencion, pregunta_normalizada)
        _guardar_traza(plan=plan, contexto=dict(contexto_agente))
        introduccion = "Hola, amigo." if analisis.saludo and intencion not in {
            "saludo", "agradecimiento", "despedida", "pregunta_nombre", "ayuda"} else ""

        productos = (procesador_nlp.resolver_producto(analisis, obtener_productos_activos())
                     if not intencion else [])
        if not intencion and productos:
            producto = productos[0]
            contexto_agente.update({"ultimo_producto_id": producto["id_producto"],
                                    "ultimo_producto_nombre": producto["nombre"]})
            return (f"Encontré {producto['nombre']}. ¿Quieres consultar su stock, "
                    "ubicación o movimientos?")
        if not intencion:
            empleados = procesador_nlp.resolver_empleado(analisis, obtener_empleados_activos())
            if len(empleados) == 1:
                empleado = empleados[0]
                contexto_agente.update({"ultimo_empleado_id": empleado["id_empleado"],
                                        "ultimo_empleado_nombre": empleado["nombre"]})
                return consultar_empleado_por_id(empleado["id_empleado"])
            return ("No encontré suficiente información para responder eso. "
                    "Puedes preguntarme por productos, empleados, rostros, movimientos, "
                    "alertas, anomalías o reabastecimiento.")

        if intencion == "consultar_subject":
            respuesta = _ejecutar_herramienta_segura("consultar_subject", consultar_subject,
                                                      texto_resolucion)
            etiqueta = _normalizar_subject(texto_resolucion)
            if etiqueta:
                contexto_agente["ultimo_subject"] = etiqueta
                try:
                    from ai.facial.rostros_empleados import obtener_empleado_por_etiqueta
                    empleado_subject = obtener_empleado_por_etiqueta(etiqueta)
                    if empleado_subject:
                        contexto_agente.update({"ultimo_empleado_id": empleado_subject["id_empleado"],
                                                "ultimo_empleado_nombre": empleado_subject["nombre"]})
                except Exception:
                    pass
            _guardar_traza(entidades={"subject": etiqueta} if etiqueta else {})
            return respuesta
        if intencion == "listar_productos":
            return _ejecutar_herramienta_segura("listar_productos", consultar_catalogo_productos)
        if intencion == "producto_menor_stock":
            return _ejecutar_herramienta_segura("producto_menor_stock",
                                                consultar_producto_menor_stock)
        if intencion == "listar_rostros":
            return _ejecutar_herramienta_segura("listar_rostros", listar_estado_rostros, False)
        if intencion == "empleados_sin_rostro":
            return _ejecutar_herramienta_segura("empleados_sin_rostro", listar_estado_rostros, True)
        if intencion == "empleados_activos":
            empleados = obtener_empleados_activos()
            return f"Hay {len(empleados)} empleados activos registrados."
        if intencion == "movimientos_hoy":
            return _ejecutar_herramienta_segura("movimientos_hoy", consultar_movimientos_hoy)
        if intencion == "alertas_reconocimiento":
            return _ejecutar_herramienta_segura("alertas_reconocimiento",
                                                consultar_alertas_reconocimiento)
        if intencion == "consultar_reabastecimiento":
            return _ejecutar_herramienta_segura("consultar_reabastecimiento",
                                                consultar_reabastecimiento)

        if intencion == "stock_bajo":
            respuesta = consultar_productos_stock_bajo()
            contexto_agente["ultima_intencion"] = intencion
            return f"{introduccion} {respuesta}".strip()
        if intencion == "productos_agotados":
            respuesta = consultar_productos_agotados()
            contexto_agente["ultima_intencion"] = intencion
            return f"{introduccion} {respuesta}".strip()
        if intencion == "consultar_alertas":
            nivel = analisis.entidades.get("NIVEL_ALERTA")
            solo_stock = "stock" in pregunta_normalizada
            if nivel or solo_stock:
                respuesta = _ejecutar_herramienta_segura(
                    "consultar_alertas_filtradas", consultar_alertas_filtradas,
                    nivel, solo_stock
                )
            else:
                respuesta = _ejecutar_herramienta_segura("consultar_alertas",
                                                          consultar_alertas_pendientes)
            contexto_agente["ultima_alerta"] = respuesta
            return f"{introduccion} {respuesta}".strip()
        if intencion == "consultar_movimientos":
            return f"{introduccion} {consultar_movimientos_recientes()}".strip()
        if intencion == "resumen_inventario":
            respuesta = _ejecutar_herramienta_segura("resumen_inventario",
                                                      consultar_estado_general)
            return f"{introduccion} {respuesta}".strip()
        if intencion == "consultar_anomalias":
            respuesta = _ejecutar_herramienta_segura("consultar_anomalias",
                                                      consultar_anomalias_inventario)
            return f"{introduccion} {respuesta}".strip()
        if intencion in {"consultar_empleado", "movimientos_empleado",
                         "consultar_rostro_empleado", "rostro_y_movimientos"}:
            empleados = obtener_empleados_activos()
            encontrados = procesador_nlp.resolver_empleado(analisis, empleados)
            if (not encontrados and contexto_agente["ultimo_empleado_id"] and
                    _es_seguimiento_contextual(pregunta)):
                encontrados = [{"id_empleado": contexto_agente["ultimo_empleado_id"],
                                "nombre": contexto_agente["ultimo_empleado_nombre"],
                                "codigo_empleado": ""}]
            if not encontrados:
                return "No encontré un empleado activo con ese nombre o código."
            if len(encontrados) > 1:
                return "Encontré varios empleados relacionados: " + ", ".join(e["nombre"] for e in encontrados) + "."
            empleado = encontrados[0]
            contexto_agente.update({"ultimo_empleado_id": empleado["id_empleado"],
                                    "ultimo_empleado_nombre": empleado["nombre"],
                                    "ultima_intencion": intencion})
            _guardar_traza(entidades={"empleado": empleado["nombre"]})
            if intencion == "movimientos_empleado":
                return consultar_movimientos_empleado(empleado["id_empleado"])
            if intencion == "consultar_rostro_empleado":
                return _ejecutar_herramienta_segura("consultar_rostro_empleado",
                                                    consultar_rostro_empleado,
                                                    empleado["id_empleado"])
            if intencion == "rostro_y_movimientos":
                rostro = _ejecutar_herramienta_segura("consultar_rostro_empleado",
                                                      consultar_rostro_empleado,
                                                      empleado["id_empleado"])
                movimientos = consultar_movimientos_empleado(empleado["id_empleado"])
                return f"{rostro}\n\n{movimientos}"
            return consultar_empleado_por_id(empleado["id_empleado"])

        if intencion == "prediccion_agotamiento":
            productos_pred = procesador_nlp.resolver_producto(analisis, obtener_productos_activos())
            producto_id = productos_pred[0]["id_producto"] if len(productos_pred) == 1 else None
            if producto_id:
                _guardar_traza(entidades={"producto": productos_pred[0]["nombre"]})
            respuesta = _ejecutar_herramienta_segura("consultar_prediccion_stock",
                                                      consultar_predicciones_agotamiento,
                                                      producto_id)
            return f"{introduccion} {respuesta}".strip()

        productos = procesador_nlp.resolver_producto(analisis, obtener_productos_activos())
        if (not productos and intencion in INTENCIONES_CON_PRODUCTO and
                contexto_agente["ultimo_producto_id"] and _es_seguimiento_contextual(pregunta)):
            productos = [{"id_producto": contexto_agente["ultimo_producto_id"],
                          "nombre": contexto_agente["ultimo_producto_nombre"]}]
        if not productos:
            if intencion == "ultimo_movimiento" and not contexto_agente["ultimo_producto_id"]:
                return _ejecutar_herramienta_segura("consultar_movimientos",
                                                    consultar_movimientos_recientes)
            _guardar_traza(motivo_fallback="ENTIDAD_NO_RESUELTA")
            return "Indícame qué producto deseas consultar."
        if len(productos) > 1:
            nombres = ", ".join(p["nombre"] for p in productos)
            return f"Encontré varios productos relacionados: {nombres}. Especifica cuál deseas consultar."
        producto = productos[0]
        contexto_agente.update({"ultimo_producto_id": producto["id_producto"],
                                "ultimo_producto_nombre": producto["nombre"],
                                "ultima_intencion": intencion})
        _guardar_traza(entidades={"producto": producto["nombre"]})
        if plan == ["consultar_stock", "consultar_ubicacion"]:
            stock = _ejecutar_herramienta_segura("consultar_stock",
                                                 consultar_stock_producto,
                                                 producto["id_producto"])
            ubicacion = _ejecutar_herramienta_segura("consultar_ubicacion",
                                                     consultar_ubicaciones_producto,
                                                     producto["id_producto"])
            return f"{stock}\n\n{ubicacion}"
        if intencion == "consultar_producto":
            return _ejecutar_herramienta_segura("consultar_producto",
                                                consultar_detalle_producto,
                                                producto["id_producto"])
        funciones = {"consultar_stock": consultar_stock_producto,
                     "consultar_ubicacion": consultar_ubicaciones_producto,
                     "stock_minimo": consultar_stock_minimo_producto,
                     "ultimo_retiro": consultar_ultimo_retiro,
                     "ultimo_movimiento": consultar_ultimo_movimiento,
                     "historial_producto": consultar_historial_producto}
        if intencion not in funciones:
            _guardar_traza(motivo_fallback="HERRAMIENTA_NO_ENCONTRADA")
            return "Entendí la consulta, pero todavía no tengo una herramienta segura para resolverla."
        respuesta = funciones[intencion](producto["id_producto"])
        return f"{introduccion} {respuesta}".strip()
    except Exception:
        traceback.print_exc()
        return "Tuve un problema al consultar el inventario. Intenta nuevamente."


def _consulta_estructurada_compatibilidad(pregunta):
    inicio = time.perf_counter()
    respuesta = _procesar_pregunta_compatibilidad(pregunta)
    traza = dict(getattr(_traza_local, "datos", {}))
    traza["tiempo_total"] = time.perf_counter() - inicio
    traza["tiempo_herramienta"] = max(
        0.0,
        traza["tiempo_total"] - traza.get("tiempo_nlp", 0.0) - traza.get("tiempo_llm", 0.0),
    )
    if DEBUG_JARVIS:
        print("\nJARVIS DEBUG")
        print("Mensaje:", pregunta)
        print("Intención:", traza.get("intencion"))
        print("Entidades:", traza.get("entidades"))
        print("Contexto:", traza.get("contexto"))
        print("Plan:", traza.get("plan"))
        print("Herramienta:", traza.get("herramienta") or traza.get("intencion"))
        print("Resultado:", traza.get("resultado", respuesta))
        print("Motivo fallback:", traza.get("motivo_fallback"))
        print(f"NLP: {traza.get('tiempo_nlp', 0)*1000:.1f} ms")
        print(f"LLM: {traza.get('tiempo_llm', 0)*1000:.1f} ms")
        print(f"Herramienta/SQL: {traza['tiempo_herramienta']*1000:.1f} ms")
        print(f"Total: {traza['tiempo_total']*1000:.1f} ms")
    return {"respuesta": respuesta, "intencion": traza.get("intencion"),
            "entidades": traza.get("entidades", {}), "origen": traza.get("origen"),
            "tiempo_ms": round(traza["tiempo_total"] * 1000, 2)}



def _aclarar_productos(filas,plan,filtros,confirmar=False):
    ctx=_contexto_actual.get()
    ctx.esperar(plan,'producto',filas,filtros,ctx.get('pregunta_incompleta'))
    if confirmar and len(filas)==1:
        ctx['estado_dialogo']='WAITING_FOR_CONFIRMATION'
    opciones='\n'.join(f'{i}. {p["nombre"]} ({p.get("codigo", "sin código")})' for i,p in enumerate(filas,1))
    pregunta={'consultar_ubicacion':'¿Cuál quieres localizar?', 'consultar_stock':'¿De cuál quieres consultar el stock?',
              'prediccion_agotamiento':'¿De cuál quieres estimar la duración?'}.get(plan[-1] if plan else None,'¿Cuál quieres consultar?')
    respuesta=f'Encontré {len(filas)} '+('producto' if len(filas)==1 else 'productos')+':\n'+opciones+'\n'+pregunta
    if confirmar and len(filas)==1:respuesta=f'¿Te refieres a {filas[0]["nombre"]} ({filas[0].get("codigo", "sin código")})? Puedes confirmar o indicar otro producto.'
    return {'respuesta':respuesta,
            'voz':respuesta if confirmar and len(filas)==1 else f'Encontré {len(filas)} coincidencias. '+pregunta+' Indica el número, el nombre o el código.',
            'intencion':'aclaracion','datos':{'candidatos':filas}}


def _seleccion_contextual(texto,filas):
    texto=re.sub(r'^(?:stock|ubicacion|prediccion|duracion)(?:\s+(?:de|del))?\s+', '', texto)
    ordinal=re.search(r'\b(?:el|la|numero|opcion)?\s*(primero|primera|segundo|segunda|tercero|tercera|cuarto|cuarta|quinto|quinta|\d+)\b',texto)
    if not ordinal or not re.fullmatch(r'(?:y )?(?:(?:el|la|numero|opcion) )?(?:primero|primera|segundo|segunda|tercero|tercera|cuarto|cuarta|quinto|quinta|\d+)',texto):return None
    valor=ordinal.group(1)
    indice=int(valor)-1 if valor.isdigit() else ['primero','segundo','tercero','cuarto','quinto'].index(valor[:-1]+'o' if valor.endswith('a') else valor)
    return filas[indice] if 0<=indice<len(filas) else False


def _guardar_resultado(resultado,dominio):
    ctx=_contexto_actual.get();ctx['ultimo_dominio']=dominio;ctx['ultimo_tema']=dominio
    ctx.completar()
    ctx['ultimo_resultado']={'dominio':dominio,'datos':resultado.get('datos'),'intencion':resultado.get('intencion')}
    return resultado


def _acciones_led_ubicacion(producto, filas):
    # Una ubicación sin posición no permite ofrecer una dirección lógica segura.
    try:
        direcciones = resolver_filas(filas)
    except (ValueError, TypeError, KeyError):
        return []
    return [dict(tipo='led_producto', id=producto['id_producto'],
                 etiqueta='Encender LED ' + ', '.join(f'{u["led"]:02}' for u in direcciones))] if direcciones else []


def _procesar_leds(pregunta, ctx, consultar):
    texto = normalizar_texto(pregunta)
    texto = re.sub(r'^jarvis\s*[, :]?\s*', '', texto).rstrip('.!? ')
    comando = re.match(r'^(enciende|encender|prende|apaga|apagar)\s+(.*)$', texto)
    if texto in ('cancelar','cancela','olvidalo','deja eso','otra consulta','reiniciar contexto','reinicia el contexto','olvida la conversacion'):
        ctx.pop('led_pendiente', None)
    if re.match(r'^no\s+(?:enciendas|prendas|apagues|encender|apagar)\b', texto):
        ctx.pop('led_pendiente',None)
        return {'respuesta':'No cambiaré los LEDs.','intencion':'led_cancelado'}
    if comando:
        encendido = comando.group(1) in ('enciende','encender','prende')
        objeto = comando.group(2)
        if not re.search(r'\b(?:luz|luces|led|leds)\b', objeto):
            return consultar(pregunta)
        if not encendido and re.fullmatch(r'(?:todas?\s+(?:las?\s+)?)?(?:luces|leds)', objeto):
            ctx.pop('led_pendiente',None)
            r=servicio_led.apagar_todos()
            return {'respuesta':r['mensaje'],'intencion':'led_apagar_todos','datos':r}
        directo=re.fullmatch(r'(?:el\s+)?led\s+(-?\d+)',objeto)
        if directo:
            ctx.pop('led_pendiente',None)
            r=(servicio_led.encender_led if encendido else servicio_led.apagar_led)(int(directo.group(1)))
            return {'respuesta':r['mensaje'],'intencion':'led','datos':r}
        objetivo=re.sub(r'^(?:(?:la|el|las|los)\s+)?(?:luz|luces|leds?)\b\s*(?:(?:de|del)\s+)?', '', objeto)
        objetivo=re.sub(r'^(?:el|la|los|las)\s+', '', objetivo).strip()
        ctx['led_pendiente']=encendido
        if not objetivo or objetivo in ('ese','esa','este','producto','del producto'):
            if ctx.get('ultimo_producto_id') and not ctx.get('candidatos_ambiguos'):
                r=servicio_led.por_producto(ctx['ultimo_producto_id'],encendido)
                ctx.pop('led_pendiente',None)
                return {'respuesta':r['mensaje'],'intencion':'led','datos':r,
                        'acciones_ui':[{'tipo':'producto_mapa','id':ctx['ultimo_producto_id']}]}
            pregunta='ubicacion'
        else:
            pregunta='ubicacion de '+objetivo
    pendiente=ctx.get('led_pendiente')
    resultado=consultar(pregunta)
    if pendiente is not None:
        p=resultado.get('datos',{}).get('producto')
        if p and resultado.get('intencion')=='consultar_ubicacion':
            ctx.pop('led_pendiente',None)
            r=servicio_led.por_producto(p['id_producto'],pendiente)
            return {'respuesta':r['mensaje'],'intencion':'led','datos':r,
                    'acciones_ui':[{'tipo':'producto_mapa','id':p['id_producto']}]}
        if resultado.get('intencion') not in ('aclaracion','saludo','como_estas','agradecimiento'):
            ctx.pop('led_pendiente',None)
    return resultado


def _consulta_central(pregunta):
    from jarvis.tools import instalar
    instalar()
    from jarvis.jarvis_router import procesar
    return procesar(pregunta,_contexto_actual.get(),
        lambda texto:_procesar_leds(texto,_contexto_actual.get(),_consulta_central_inventario))


def _consulta_central_inventario(pregunta):
    from jarvis.nlp_jarvis import plan_conversacional,extraer_filtros,PALABRAS_CONSULTA,PALABRAS_FUNCIONALES,solicita_mapa
    from jarvis.jarvis_personality import numero,prediccion,social,respuesta_stock,respuesta_lista,respuesta_ubicaciones
    from jarvis import herramientas_jarvis as servicios
    from inventory.mapa_almacen import describir_ubicacion
    ctx=_contexto_actual.get();texto=normalizar_texto(pregunta)
    _traza_local.datos={'mensaje':pregunta,'texto_normalizado':texto,'origen':'Motor conversacional','entidades':{},
        'estado_dialogo_entrada':ctx['estado_dialogo'],'intencion_pendiente_entrada':ctx['intencion_pendiente'],
        'producto_entrada':ctx.get('ultimo_producto_id')}
    if not texto:return {'respuesta':'Escribe o di qué quieres consultar.'}
    if re.search(r'\b(?:borra(?:r)?|elimina(?:r)?|modifica(?:r)?|crea(?:r)?|registra(?:r)?|actualiza(?:r)?|inserta(?:r)?|drop|delete|update|insert|truncate)\b',texto):
        return {'respuesta':'JARVIS solo realiza consultas de lectura. Usa la pantalla correspondiente para modificar el inventario.','intencion':'accion_no_permitida'}
    if texto in ('reiniciar contexto','reinicia el contexto','olvida la conversacion'):
        ctx.limpiar();return {'respuesta':'Contexto reiniciado.','intencion':'reiniciar_contexto'}
    mapa_solicitado=solicita_mapa(texto,bool(ctx.get('ultima_ubicacion')))
    if re.fullmatch(r'(?:abre|abrir|ver|llevame a|llevame al|llevame|ensename|muestrame)\s+(?:el\s+)?mapa',texto):
        producto_id=ctx.get('ultimo_producto_id') if not ctx.get('candidatos_ambiguos') else None
        accion={'tipo':'producto_mapa','id':producto_id} if producto_id else {'tipo':'abrir_mapa'}
        return {'respuesta':'Abro el mapa del almacén.','intencion':'abrir_mapa','acciones_ui':[accion]}
    if ctx['estado_dialogo']=='WAITING_FOR_CONFIRMATION':
        if texto in ('si','correcto','ese','esa','ok','dale'):
            texto=pregunta='el primero'
        elif texto in ('no','ninguno','ninguna'):
            ctx.esperar(ctx['plan_pendiente'],'producto',filtros=ctx['filtros_pendientes'])
            return {'respuesta':'Indica el nombre o código del producto que necesitas.','intencion':'aclaracion'}
    tipo_social=_intent_router.social(texto)
    if tipo_social:
        return {'respuesta':social(tipo_social),'intencion':tipo_social}
    if texto in ('cancelar','cancela','olvidalo','deja eso','otra consulta'):
        ctx.completar()
        return {'respuesta':'Claro. ¿Qué quieres consultar ahora?','intencion':'cancelar_consulta'}
    if texto in ('que puedes hacer','que puedes hacer jarvis','ayuda','ayudame','quien eres'):
        return {'respuesta':formatear_respuesta_ayuda()+' También puedo localizar productos en el mapa.','intencion':'ayuda'}
    if texto in ('como debo dirigirme a ti','como puedo llamarte','como quieres que te llame'):
        return {'respuesta':'Puedes llamarme JARVIS. ¿Qué necesitas consultar?','intencion':'pregunta_nombre'}
    if texto in ('reconocer empleado','reconoce empleado','abrir reconocimiento facial','activa la camara'):
        return {'respuesta':'Abriré el reconocimiento facial. La identidad dependerá de la evidencia de la cámara.','intencion':'facial','acciones_ui':[{'tipo':'facial'}]}
    explicar=bool(re.search(r'\b(?:por que|explicame|explica|detalles|detalle|que paso ahi)\b',texto))
    if explicar and ctx.get('ultimo_dominio')=='anomalia':
        filas=servicios.datos_anomalias(ctx.get('filtros_anomalias',{}))
        anterior=ctx.get('ultima_anomalia');m=re.search(r'movimiento\s*(?:numero|#)?\s*(\d+)',texto)
        elegidas=[a for a in filas if (m and a['id_movimiento']==int(m.group(1))) or (not m and anterior and a['id_anomalia']==anterior['id_anomalia'])]
        if not elegidas:
            ctx.esperar(['explicar_anomalia'],'anomalia',ctx.get('lista_anomalias',[]))
            return {'respuesta':'Selecciona una anomalía de la lista para que explique el motivo.','intencion':'aclaracion'}
        ctx['ultima_anomalia']=elegidas[0]
        return _guardar_resultado({'respuesta':' '.join(a['motivo'] for a in elegidas),'intencion':'explicar_anomalia','datos':elegidas},'anomalia')
    plan=_intent_router.resolver(texto);filtros=extraer_filtros(texto)
    if mapa_solicitado:
        ctx['mapa_pendiente']=True
        if not plan:plan=['consultar_ubicacion']
    elif plan:ctx.pop('mapa_pendiente',None)
    plan_explicito=bool(plan)
    if plan and ctx.get('plan_pendiente') and plan!=ctx['plan_pendiente']:
        if all(a in _intent_router.acciones_producto for a in plan):
            if ctx.get('tipo_entidad_pendiente') not in ('producto','intencion'):ctx.completar()
            ctx.update(plan_pendiente=list(plan),intencion_pendiente=plan[-1],filtros_pendientes=filtros)
        else:
            ctx.completar()
    if plan==['resumen_consumo']:
        from collections import defaultdict
        from decimal import Decimal
        movimientos=servicios.datos_movimientos({**filtros,'tipo_movimiento':'Salida'})
        catalogo={p['id_producto']:p for p in servicios.datos_inventario()}
        cantidades=defaultdict(Decimal);conteos=defaultdict(set)
        for m in movimientos:
            cantidades[m['id_producto']]+=Decimal(str(m['cantidad']));conteos[m['id_producto']].add(m['id_movimiento'])
        if 'mas salidas' in texto:
            orden=sorted(conteos,key=lambda p:(-len(conteos[p]),p))[:5]
            lineas=[f"{catalogo[p]['nombre']}: {len(conteos[p])} salidas." for p in orden if p in catalogo]
            encabezado='Mayor número de salidas registradas:'
        else:
            unidades=defaultdict(list)
            for p,cantidad in cantidades.items():
                if p in catalogo:unidades[catalogo[p]['unidad_medida']].append((p,cantidad))
            lineas=[f"{catalogo[p]['nombre']}: {numero(cantidad)} {unidad}." for unidad,filas in sorted(unidades.items()) for p,cantidad in sorted(filas,key=lambda x:(-x[1],x[0]))[:3]]
            encabezado='Consumo registrado, comparado dentro de cada unidad de medida:'
        return _guardar_resultado({'respuesta':encabezado+'\n'+'\n'.join(lineas) if lineas else 'Sin salidas registradas para ese período.',
                                   'intencion':'resumen_consumo','datos':movimientos},'movimiento')
    if ctx.get('estado_dialogo')=='WAITING_FOR_LOCATION' and not plan:
        plan=list(ctx['plan_pendiente'])
        if not filtros.get('valor_ubicacion') and re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)+',texto):
            filtros.update(campo_ubicacion='ubicacion',valor_ubicacion=texto)
    seguimiento_movimientos=bool(ctx.get('ultimo_dominio')=='movimiento' and not plan and filtros.get('fecha_desde') and _solo_referencia(texto))
    if seguimiento_movimientos:
        plan=['consultar_movimientos']
        filtros={**ctx.get('filtros_movimientos',{}),**filtros}
    if ctx.get('ultimo_dominio')=='anomalia' and re.search(r'\b(?:grave|marcada|marcado)\b',texto):plan=['consultar_anomalias']
    if texto in ('por que','explicame','explicame por que','dame detalles','dame mas detalle','mas detalles'):
        if ctx.get('ultimo_dominio')=='prediccion':plan=['prediccion_agotamiento']
        elif ctx.get('ultimo_dominio')=='producto':plan=['estado_producto']
        elif ctx.get('ultimo_dominio')=='movimiento' and ctx.get('ultimo_movimiento'):
            filas=servicios.datos_movimientos(ctx.get('filtros_movimientos',{}),ctx.get('producto_movimientos'),ctx.get('empleado_movimientos'))
            fila=next((r for r in filas if r['id_movimiento']==ctx['ultimo_movimiento']['id_movimiento']),None)
            return {'respuesta':fila.get('observacion') or 'Ese movimiento no tiene observaciones registradas.' if fila else 'Ese movimiento ya no está disponible.','intencion':'explicar_movimiento','datos':fila}
        else:return {'respuesta':'¿Qué resultado quieres que explique?','intencion':'aclaracion'}
    if plan==['consultar_anomalias']:
        consulta=filtros or ctx.get('filtros_anomalias',{}) if ctx.get('ultimo_dominio')=='anomalia' else filtros
        filas=servicios.datos_anomalias(consulta)
        if 'pendientes' in texto:filas=[a for a in filas if a['estado']=='PENDIENTE']
        niveles={'CRÍTICA':4,'ALTA':3,'MEDIA':2,'BAJA':1}
        filas.sort(key=lambda a:(niveles.get(a['nivel'],0),a['score']),reverse=True)
        ctx.update(lista_anomalias=filas,filtros_anomalias=consulta)
        if 'grave' in texto and filas:
            a=filas[0];ctx['ultima_anomalia']=a
            respuesta=f'La más grave es el movimiento #{a["id_movimiento"]} de {a["producto"]}, nivel {a["nivel"].lower()}.'
        else:
            respuesta=(f'Hay {len(filas)} anomalías; {sum(a["estado"]=="PENDIENTE" for a in filas)} pendientes.' if filas else 'No hay anomalías registradas para ese período y filtros.')
            if len(filas)==1:ctx['ultima_anomalia']=filas[0]
            else:ctx.pop('ultima_anomalia',None)
        return _guardar_resultado({'respuesta':respuesta,'intencion':'consultar_anomalias','datos':filas},'anomalia')
    if ctx.get('ultimo_dominio')=='anomalia' and _seleccion_contextual(texto,ctx.get('lista_anomalias',[])) is not None:
        a=_seleccion_contextual(texto,ctx.get('lista_anomalias',[]))
        if not a:return {'respuesta':'Indica una anomalía de la lista anterior.'}
        actual=servicios.datos_anomalias(ctx.get('filtros_anomalias',{}))
        a=next((f for f in actual if f['id_anomalia']==a['id_anomalia']),None)
        if not a:return {'respuesta':'Esa anomalía ya no está disponible.'}
        ctx['ultima_anomalia']=a
        explicacion_pendiente=ctx.get('plan_pendiente')==['explicar_anomalia']
        return _guardar_resultado({'respuesta':a['motivo'] if explicacion_pendiente else f'Movimiento #{a["id_movimiento"]}: {a["producto"]}, nivel {a["nivel"].lower()}.','datos':a,'intencion':'explicar_anomalia' if explicacion_pendiente else 'seleccionar_anomalia'},'anomalia')
    if re.search(r'\b(?:ahi|alli|esa ubicacion)\b',texto) and re.search(r'\b(?:hay|productos|contenido|muestrame|muestra|ver)\b',texto):
        anteriores=ctx.get('ultima_ubicacion') or []
        if len(anteriores)==1:filtros.update(campo_ubicacion='ubicacion',valor_ubicacion=anteriores[0]['codigo_ubicacion'])
        else:
            if not anteriores:
                ctx.esperar(['contenido_ubicacion'],'ubicacion',pregunta=pregunta)
                return {'respuesta':'¿Qué ubicación quieres consultar?','intencion':'aclaracion'}
            ctx.esperar(['contenido_ubicacion'],'ubicacion',anteriores,pregunta=pregunta)
            return {'respuesta':'Hay varias ubicaciones:\n'+'\n'.join(f'{i}. {u["codigo_ubicacion"]}' for i,u in enumerate(anteriores,1))+'\n¿Cuál quieres consultar?'}
        plan=['contenido_ubicacion']
    candidatos=ctx.get('candidatos_ambiguos') or (ctx.get('lista_productos',[])
        if ctx.get('ultimo_dominio') in ('producto','productos','prediccion') and ctx.get('estado_dialogo')=='IDLE' else [])
    seleccion=_seleccion_contextual(texto,candidatos)
    if seleccion is False:return {'respuesta':'Ese número no está en la lista. Indica una de las opciones mostradas.'}
    if seleccion is not None and ctx.get('tipo_candidatos')=='ubicacion':
        filtros={'campo_ubicacion':'ubicacion','valor_ubicacion':seleccion['codigo_ubicacion']};plan=['contenido_ubicacion']
    if plan==['contenido_ubicacion']:
        if not filtros.get('valor_ubicacion'):
            ctx.esperar(plan,'ubicacion',filtros=filtros,pregunta=pregunta)
            return {'respuesta':'¿Qué zona, estante, pasillo o ubicación quieres consultar?','intencion':'aclaracion'}
        filas=servicios.datos_contenido(filtros);ctx.update(candidatos_ambiguos=[],ultima_ubicacion=filas)
        lineas=[f'{r["nombre"]}: {numero(r["cantidad"])} {r["unidad_medida"]} en {r["codigo_ubicacion"]}.' for r in filas]
        resultado=respuesta_lista(lineas,'registros de existencias')
        if not filas:resultado['respuesta']='No encontré existencias en esa ubicación.'
        accion={'tipo':'ubicaciones','ids':sorted({r['id_ubicacion'] for r in filas})}
        navegar=ctx.pop('mapa_pendiente',False) or mapa_solicitado
        resultado.update(intencion='contenido_ubicacion',datos=filas,
            acciones_ui=[accion] if filas and navegar else [],acciones_opcionales=[accion] if filas and not navegar else [])
        return _guardar_resultado(resultado,'ubicacion')
    seleccion_critica=False
    if re.search(r'\b(?:mas critico|mas critica)\b',texto):
        filas=servicios.datos_inventario()
        if not filas:return {'respuesta':'No hay productos activos registrados.'}
        p=min(filas,key=lambda r:(0 if float(r['stock_actual'])==0 else 1,float(r['stock_actual'])/float(r['stock_minimo']) if float(r['stock_minimo'])>0 else float('inf')))
        ctx.recordar_producto(p);plan=['estado_producto'];seleccion=p;seleccion_critica=True
    analisis=procesador_nlp.interpretar(pregunta)
    if not plan and ctx.get('plan_pendiente') and re.search(r'\b(?:empleados?|rostros?|alertas?|avisos?|reabastecimiento|resumen del inventario)\b',texto):
        ctx.completar()
        return None  # La ruta existente resuelve la nueva consulta de otro dominio.
    necesita_catalogo=bool(plan or texto.startswith('y ') or candidatos or ctx.get('plan_pendiente')) and not (plan==['consultar_movimientos'] and _solo_referencia(texto))
    productos=[seleccion] if seleccion is not None else _entity_resolver.productos(analisis,obtener_productos_activos()) if necesita_catalogo else []
    origen='explicit'
    if seleccion is not None and not seleccion_critica:
        origen='candidate'
        plan=plan or ctx.get('plan_pendiente') or ctx.get('ultimo_plan_producto') or ['consultar_stock']
        filtros=filtros if plan_explicito else ctx.get('filtros_pendientes') or filtros
    elif ctx.get('candidatos_ambiguos') and ctx.get('tipo_candidatos')=='producto':
        coincidencias=_entity_resolver.productos(analisis,ctx['candidatos_ambiguos'])
        if coincidencias:
            productos=coincidencias;origen='candidate';plan=plan or ctx.get('plan_pendiente',[]);filtros=filtros or ctx.get('filtros_pendientes',{})
    if not plan and ctx.get('plan_pendiente'):
        plan=list(ctx['plan_pendiente'])
        filtros={**ctx.get('filtros_pendientes',{}),**filtros}
        if productos:origen='pending_dialog'
    if texto in ('el otro','y el otro','la otra','y la otra'):
        otros=[p for p in ctx.get('lista_productos',[]) if p['id_producto']!=ctx.get('ultimo_producto_id')]
        plan=ctx.get('plan_pendiente') or ctx.get('ultimo_plan_producto') or ['consultar_stock']
        if len(otros)!=1:
            return _aclarar_productos(otros,plan,{}) if otros else {'respuesta':'¿Qué otro producto quieres consultar?','intencion':'aclaracion'}
        productos=otros;origen='candidate'
    if texto in ('el anterior','y el anterior'):
        anterior=ctx.get('producto_anterior')
        if not anterior or not anterior.get('id_producto'):return {'respuesta':'No hay un producto anterior seleccionado.'}
        productos=[anterior];plan=ctx.get('ultimo_plan_producto') or ['consultar_stock'];origen='previous_product'
    if texto in ('y los otros','los otros','los mismos','y esos','y ese','ese','esa','ellos','ellas') and not plan:
        if texto in ('los otros','y los otros'):
            otros=[p for p in ctx.get('lista_productos',[]) if p['id_producto']!=ctx.get('ultimo_producto_id')]
            return _aclarar_productos(otros,ctx.get('ultimo_plan_producto') or ['consultar_stock'],{}) if otros else {'respuesta':'¿Qué otros productos quieres consultar?'}
        plan=ctx.get('ultimo_plan_producto') or ['consultar_stock']
    if texto.startswith('y ') and productos and origen=='explicit' and not plan:plan=['consultar_stock']
    if not plan and analisis.intencion in INTENCIONES_CON_PRODUCTO:
        plan=[analisis.intencion]
        if not productos:productos=procesador_nlp.resolver_producto(analisis,obtener_productos_activos())
    if productos and analisis.entidades.get('PRODUCTO_SUGERIDO') and origen=='explicit':
        return _aclarar_productos(productos,plan,filtros,confirmar=True)
    if productos and plan==['consultar_riesgo']:plan=['prediccion_agotamiento']
    grupos={'stock_bajo','productos_agotados','consultar_riesgo'}
    prediccion_global='prediccion_agotamiento' in plan and not productos and ('primero' in texto or bool(re.search(r'\b(?:que|cual|cuales)\b.*\b(?:agotarse|agotaria|agotara)\b',texto)))
    if any(a in grupos for a in plan) or prediccion_global:
        if productos and set(plan)<= {'stock_bajo','productos_agotados'}:plan=['estado_producto']
        else:
            estado='Stock bajo' if 'stock_bajo' in plan else 'Agotados' if 'productos_agotados' in plan else 'Todos'
            filas=servicios.datos_inventario(estado)
            ctx.update(lista_productos=filas,candidatos_ambiguos=[],tipo_candidatos='producto')
            partes=[];datos={'productos':filas}
            if estado!='Todos':partes.append(respuesta_lista([f'{r["nombre"]}: {numero(r["stock_actual"])} {r["unidad_medida"]}.' for r in filas],'productos')['respuesta'])
            if 'prediccion_agotamiento' in plan or 'consultar_riesgo' in plan:
                resultados=[dict(servicios.datos_prediccion(r['id_producto']),id_producto=r['id_producto']) for r in filas];validos=[r for r in resultados if r['datos_suficientes']]
                if 'consultar_riesgo' in plan:
                    riesgos={'CRÍTICO'} if 'critico' in texto else {'BAJO'} if 'bajo' in texto else {'MEDIO'} if 'medio' in texto else {'ALTO','CRÍTICO'}
                    validos=[r for r in validos if r['riesgo'] in riesgos]
                    partes.append('\n'.join(prediccion(r) for r in validos) or ('Sin datos suficientes para evaluar el riesgo.' if not any(r['datos_suficientes'] for r in resultados) else 'No hay productos con ese riesgo estimado.'))
                else:
                    validos=[r for r in validos if r['dias_restantes_promedio'] is not None]
                    if validos:
                        r=min(validos,key=lambda r:r['dias_restantes_promedio']);p=next(p for p in filas if p['id_producto']==r['id_producto'])
                        ctx.recordar_producto(p);ctx['ultima_prediccion']=r;partes.append(prediccion(r));datos['prediccion']=r
                    else:partes.append('Sin datos suficientes para estimar cuál se agotaría primero.')
                datos['predicciones']=validos
            resultado={'respuesta':'\n'.join(partes),'voz':f'Hay {len(filas)} productos en la consulta. '+(prediccion(datos['prediccion']) if datos.get('prediccion') else 'El detalle está en pantalla.'),'intencion':plan[-1],'datos':datos}
            return _guardar_resultado(resultado,'prediccion' if datos.get('prediccion') else 'productos')
    if plan==['consultar_movimientos']:
        if len(productos)>1:return _aclarar_productos(productos,plan,filtros)
        # Una consulta global con hoy/ayer conserva su alcance; pronombres sí usan la entidad previa.
        empleado=None
        encontrados=procesador_nlp.resolver_empleado(analisis,obtener_empleados_activos()) if not productos and not _solo_referencia(texto) else []
        if len(encontrados)>1:return {'respuesta':'Encontré varios empleados: '+', '.join(e['nombre'] for e in encontrados)+'. Indica su nombre completo o código.','intencion':'aclaracion'}
        if len(encontrados)==1:
            e=encontrados[0];empleado=e['id_empleado'];ctx.update(ultimo_empleado_id=empleado,ultimo_empleado_nombre=e['nombre'],ultimo_empleado=e)
        if re.search(r'\b(?:el|ella|ese empleado)\b',texto) and ctx.get('ultimo_dominio')=='empleado':empleado=ctx.get('ultimo_empleado_id')
        referencia=bool(re.search(r'\b(?:ese|esa|esos|esas|su|sus|del producto|ese producto)\b',texto))
        producto=productos[0]['id_producto'] if productos else ctx.get('ultimo_producto_id') if referencia and _solo_referencia(texto) else None
        if seguimiento_movimientos:
            producto=ctx.get('producto_movimientos');empleado=ctx.get('empleado_movimientos')
        filas=servicios.datos_movimientos(filtros,producto,empleado)
        ctx.update(filtros_movimientos=filtros,producto_movimientos=producto,empleado_movimientos=empleado,ultimo_movimiento=filas[0] if filas else None)
        total=len({m['id_movimiento'] for m in filas})
        partes=[f'#{m["id_movimiento"]} · {m["tipo_movimiento"]} · {m["producto"]}: {numero(m["cantidad"])} · {m["fecha_movimiento"]:%d/%m/%Y}' for m in filas[:10]]
        resultado={'respuesta':f'Hay {total} movimientos'+(' para ese período.' if filtros.get('fecha_desde') else ' registrados.')+('\n'+'\n'.join(partes) if partes else ''),'voz':f'Hay {total} movimientos. '+('Te muestro los recientes en pantalla.' if filas else ''),'datos':filas,'intencion':'consultar_movimientos'}
        return _guardar_resultado(resultado,'movimiento')
    if plan==['contenido_categoria']:
        from inventory.productos import listar_categorias
        categorias=listar_categorias()
        consulta=re.sub(r'^.*?categorias?\s*','',texto)
        a=procesador_nlp.interpretar(consulta)
        encontradas=procesador_nlp.resolver_catalogo(a,categorias,'id_categoria',('nombre',),'CATEGORIA')
        if len(encontradas)!=1:return {'respuesta':'Indica una categoría registrada'+(': '+', '.join(c['nombre'] for c in encontradas) if encontradas else '.')}
        ctx['ultima_categoria']=encontradas[0]
        filas=servicios.datos_inventario(categoria=encontradas[0]['id_categoria'])
        r=respuesta_lista([f'{p["nombre"]}: {numero(p["stock_actual"])} {p["unidad_medida"]}.' for p in filas],'productos');r.update(datos=filas,intencion='contenido_categoria')
        return _guardar_resultado(r,'categoria')
    if not plan:
        if ctx.get('ultimo_dominio')=='empleado' and _solo_referencia(texto) and ctx.get('ultimo_empleado_id'):
            funcion=consultar_rostro_empleado if 'rostro' in texto else consultar_empleado_por_id
            return {'respuesta':funcion(ctx['ultimo_empleado_id']),'intencion':'consultar_rostro_empleado' if 'rostro' in texto else 'consultar_empleado','datos':{'id_empleado':ctx['ultimo_empleado_id']}}
        if analisis.intencion is None:
            if not productos:productos=_entity_resolver.productos(analisis,obtener_productos_activos())
            if len(productos)>1:return _aclarar_productos(productos,[],{})
            if len(productos)==1:
                ctx.recordar_producto(productos[0]);ctx['ultimo_dominio']='producto'
                ctx.esperar([],'intencion',pregunta=pregunta)
                ctx['entidad_pendiente']=dict(productos[0])
                return {'respuesta':f'Encontré {productos[0]["nombre"]}. ¿Quieres consultar stock, ubicación, movimientos o predicción?','intencion':'aclaracion'}
        return None
    if not productos and _solo_referencia(texto) and ctx.get('ultimo_producto_id') and not ctx.get('candidatos_ambiguos') and ctx.get('estado_dialogo')!='WAITING_FOR_PRODUCT':
        productos=[{'id_producto':ctx['ultimo_producto_id']}];origen='visual' if ctx.pop('contexto_visual_pendiente',False) else 'previous_turn'
    if not productos:
        candidatos=ctx.get('candidatos_ambiguos',[]) if ctx.get('tipo_candidatos')=='producto' else []
        ctx.esperar(plan,'producto',candidatos,filtros,pregunta)
        if candidatos:return _aclarar_productos(candidatos,plan,filtros)
        preguntas={'consultar_ubicacion':'Claro. ¿Qué producto quieres localizar?',
            'consultar_stock':'¿De qué producto quieres consultar el stock?',
            'prediccion_agotamiento':'¿De qué producto quieres consultar la duración estimada?'}
        return {'respuesta':preguntas.get(plan[-1],'¿Qué producto quieres consultar?') if _solo_referencia(texto)
            else 'No encontré ese producto. Indica su nombre o código.','intencion':'aclaracion'}
    if len(productos)>1:return _aclarar_productos(productos,plan,filtros)
    p=servicios.datos_producto(productos[0]['id_producto'])
    if not p:
        ctx.esperar(plan,'producto',filtros=filtros,pregunta=pregunta)
        return {'respuesta':'Ese producto ya no está disponible. Indica otro nombre o código.','intencion':'aclaracion'}
    ctx.recordar_producto(p,origen)
    ctx.update(ultimo_plan_producto=plan,ultima_intencion=plan[-1])
    _guardar_traza(plan=plan,intencion=plan[-1],entidades={'producto':p['codigo']},context_source=origen,confianza=analisis.confianza)
    partes=[];voz=[];datos={'producto':p};acciones=[];opcionales=[]
    for accion in plan:
        if accion=='consultar_stock':partes.append(respuesta_stock(p,origen!='explicit'))
        elif accion in ('estado_producto','stock_minimo'):
            bajo=float(p['stock_actual'])<=float(p['stock_minimo'])
            partes.append(f'{p["nombre"]}: '+('está agotado.' if not p['stock_actual'] else 'está en stock bajo.' if bajo else 'está por encima del stock mínimo.')+f' Stock: {numero(p["stock_actual"])}; mínimo: {numero(p["stock_minimo"])} {p["unidad_medida"]}.')
        elif accion=='consultar_ubicacion':
            filas=servicios.datos_ubicaciones(p['id_producto']);datos['ubicaciones']=filas;ctx['ultima_ubicacion']=filas
            texto_ubicacion,voz_ubicacion=respuesta_ubicaciones(filas,describir_ubicacion,p)
            partes.append(texto_ubicacion);voz.append(voz_ubicacion)
            accion_mapa={'tipo':'producto_mapa','id':p['id_producto']}
            navegar=ctx.pop('mapa_pendiente',False) or mapa_solicitado
            if filas:(acciones if navegar else opcionales).append(accion_mapa)
            opcionales.extend(_acciones_led_ubicacion(p,filas))
        elif accion=='prediccion_agotamiento':
            r=servicios.datos_prediccion(p['id_producto']);ctx['ultima_prediccion']=r;datos['prediccion']=r
            texto_prediccion=prediccion(r,explicar)
            if origen!='explicit':texto_prediccion=re.sub(r'^'+re.escape(r['producto'])+r'[: ]+','',texto_prediccion,count=1)
            partes.append(texto_prediccion[:1].upper()+texto_prediccion[1:])
        else:
            funcion=HERRAMIENTAS.get(accion)
            if funcion is not None:partes.append(funcion(p['id_producto']))
    hablada=[]
    for parte in partes:
        if 'consultar_ubicacion' in plan and parte==partes[plan.index('consultar_ubicacion')]:hablada.extend(voz)
        else:hablada.append(parte)
    return _guardar_resultado({'respuesta':'\n'.join(partes),'voz':' '.join(hablada),'datos':datos,'acciones_ui':acciones,
        'acciones_opcionales':opcionales,'intencion':plan[-1]},'prediccion' if plan[-1]=='prediccion_agotamiento' else 'producto')


def _solo_referencia(texto):
    from jarvis.nlp_jarvis import PALABRAS_FUNCIONALES,PALABRAS_CONSULTA
    ignoradas=PALABRAS_FUNCIONALES|PALABRAS_CONSULTA|{'estan','ahi','alli','minimo','tiempo','pueden','podrian','duraran','cuanto','durara','duraran','cuanto','podra','tambien','bajos','muestre','hoy','ayer','esta','este','semana','mes','ultimos','su','sus'}
    return not any(t for t in texto.split() if t not in ignoradas)


def procesar_consulta(pregunta, estructurada=False, sesion='escritorio'):
    """Único punto de entrada público para interfaz, voz y FastAPI."""
    from jarvis.jarvis_personality import presentar,version_voz
    ctx=obtener_contexto(sesion);token=_contexto_actual.set(ctx)
    with ctx.lock:
        try:
            inicio=time.perf_counter()
            _traza_local.datos={'mensaje':str(pregunta),'sesion':sesion}
            try:
                resultado=_consulta_central(pregunta)
                if resultado is None:
                    resultado=_consulta_estructurada_compatibilidad(pregunta)
                    if ctx.get('ultimo_empleado_id') and resultado.get('intencion') in ('consultar_empleado','movimientos_empleado','consultar_rostro_empleado','rostro_y_movimientos'):
                        ctx['ultimo_dominio']='empleado'
                        ctx['ultimo_empleado']={'id_empleado':ctx['ultimo_empleado_id'],'nombre':ctx['ultimo_empleado_nombre']}
                    if resultado.get('intencion') not in (None,'desconocida','aclaracion','saludo','como_estas','agradecimiento','despedida'):
                        ctx.completar()
                        ctx['ultimo_tema']=ctx.get('ultimo_dominio')
                        ctx['ultimo_resultado']={'dominio':ctx.get('ultimo_dominio'),'datos':resultado.get('datos'),'intencion':resultado.get('intencion')}
                resultado['respuesta']=presentar(resultado['respuesta'])
                resultado.setdefault('voz',version_voz(resultado['respuesta']))
                resultado.setdefault('acciones_ui',[]);resultado.setdefault('datos',{})
                resultado.setdefault('acciones_opcionales',[])
                if resultado.get('intencion') in ('led','led_apagar_todos'):
                    ctx['ultima_accion']={'accion':resultado['intencion'],'resultado':resultado['respuesta']}
                    resultado['accion_ejecutada']=ctx['ultima_accion']
                ctx['ultima_intencion']=resultado.get('intencion') or ctx.get('ultima_intencion')
            except ValueError as error:
                resultado={'respuesta':str(error),'voz':str(error),'intencion':'aclaracion','acciones_ui':[],'datos':{}}
            except Exception:
                logging.getLogger('jarvis').exception('No se pudo consultar un servicio')
                resultado={'respuesta':'No pude consultar la base de datos en este momento.','intencion':'error','acciones_ui':[],'datos':{}}
            # Un solo resultado lógico; TTS solo adapta signos para pronunciación.
            resultado['voz']=version_voz(resultado['respuesta'])
            resultado['tiempo_ms']=round((time.perf_counter()-inicio)*1000,2)
            resultado['origen']='Motor conversacional'
            _guardar_traza(intencion=resultado.get('intencion'),respuesta_estructurada=resultado,
                contexto_utilizado=ctx.get('origen_contexto'),dominio=ctx.get('ultimo_dominio'))
            if resultado.get('intencion')!='reiniciar_contexto':
                ctx.turnos.append({'usuario':str(pregunta)[:500],'intencion':resultado.get('intencion'),'respuesta':resultado['respuesta'][:1500]})
            if DEBUG_JARVIS:
                logging.getLogger('jarvis').warning('Input=%r Normalized=%r DialogState=%s PendingIntent=%s CurrentProduct=%s Candidates=%r Router=%r Result=%r',pregunta,normalizar_texto(pregunta),ctx['estado_dialogo'],ctx['intencion_pendiente'],ctx['ultimo_producto_id'],[p.get('codigo',p.get('codigo_ubicacion')) for p in ctx['candidatos_ambiguos']],getattr(_traza_local,'datos',{}),resultado)
            return resultado if estructurada else resultado['respuesta']
        finally:_contexto_actual.reset(token)


def procesar_pregunta(pregunta):
    """Compatibilidad de llamadas antiguas: usa el mismo motor y memoria."""
    return procesar_consulta(pregunta)


def procesar_consulta_estructurada(pregunta):
    return procesar_consulta(pregunta,True)
