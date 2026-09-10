import re
import random
import traceback
import unicodedata
from difflib import SequenceMatcher

from database import conectar


_contador_respuestas = 0


def _inicio_amable():
    global _contador_respuestas
    opciones = ("Claro.", "Sí, lo encontré.", "Por supuesto.")
    inicio = opciones[_contador_respuestas % len(opciones)]
    _contador_respuestas += 1
    return inicio


def formatear_respuesta_stock(nombre, stock, stock_minimo):
    if stock == 0:
        return f"{_inicio_amable()} {nombre} se encuentra agotado."
    if stock <= stock_minimo:
        return (f"{_inicio_amable()} {nombre} tiene {stock} unidades disponibles y está en stock bajo. "
                f"Su stock mínimo es {stock_minimo}.")
    return f"{_inicio_amable()} Actualmente hay {stock} unidades de {nombre} disponibles."


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
    return ("Puedo ayudarte a consultar stock, ubicación de productos, últimos movimientos, "
            "productos agotados, stock bajo y alertas.")


contexto_agente = {
    "ultimo_producto_id": None,
    "ultimo_producto_nombre": None,
    "ultima_intencion": None,
}

INTENCIONES_CON_PRODUCTO = {
    "consultar_stock", "consultar_ubicacion", "ultimo_retiro",
    "ultimo_movimiento", "historial_producto", "stock_minimo",
}

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
}


def normalizar_texto(texto):
    texto = unicodedata.normalize("NFD", texto.lower().strip())
    texto = "".join(caracter for caracter in texto
                    if unicodedata.category(caracter) != "Mn")
    texto = re.sub(r"[^a-z0-9\-/ ]", " ", texto)
    texto = " ".join(texto.split())
    return re.sub(r"\b(?:jarbis|yarvis)\b", "jarvis", texto)


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
    return detectar_intencion_inventario(pregunta) or detectar_conversacion_social(pregunta) or "desconocida"


def generar_respuesta_social(intencion):
    if intencion in RESPUESTAS_SOCIALES:
        return random.choice(RESPUESTAS_SOCIALES[intencion])
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
    texto = normalizar_texto(pregunta)
    palabras = {_singular(p) for p in texto.split() if p not in PALABRAS_IGNORADAS and len(p) >= 3}
    productos = obtener_productos_activos()

    # Primero se comprueban códigos y coincidencias literales/parciales.
    por_codigo = [p for p in productos if normalizar_texto(p["codigo"]) in texto]
    if por_codigo:
        return por_codigo

    coincidencias = []
    for producto in productos:
        nombre = normalizar_texto(producto["nombre"])
        palabras_nombre = {_singular(p) for p in nombre.split()}
        if nombre in texto or (palabras and palabras.issubset(palabras_nombre)):
            coincidencias.append(producto)
        elif palabras and any(p in palabras_nombre or any(p in n or n in p for n in palabras_nombre)
                              for p in palabras):
            coincidencias.append(producto)
    if coincidencias:
        return coincidencias

    # Si no hubo coincidencia parcial, se toleran errores pequeños de escritura.
    termino = " ".join(sorted(palabras))
    aproximadas = []
    if termino:
        for producto in productos:
            nombre = normalizar_texto(producto["nombre"])
            candidatos = [nombre, *nombre.split()]
            puntaje = max(SequenceMatcher(None, termino, candidato).ratio()
                          for candidato in candidatos)
            if puntaje >= 0.72:
                aproximadas.append((puntaje, producto))
    if not aproximadas:
        return []
    mejor = max(puntaje for puntaje, _ in aproximadas)
    return [producto for puntaje, producto in aproximadas if puntaje >= mejor - 0.06]


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
                                                                  AND e.fecha_eliminacion IS NULL
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
        cursor.execute("""SELECT u.codigo_ubicacion,e.cantidad FROM existencias e
                           JOIN ubicaciones u ON u.id_ubicacion=e.id_ubicacion
                           WHERE e.id_producto=? AND e.cantidad>0 AND e.fecha_eliminacion IS NULL
                             AND u.fecha_eliminacion IS NULL ORDER BY u.codigo_ubicacion;""", id_producto)
        filas = cursor.fetchall()
        return formatear_respuesta_ubicacion(p.nombre, filas)
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
                                                                  AND e.fecha_eliminacion IS NULL
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


def reiniciar_contexto():
    contexto_agente["ultimo_producto_id"] = None
    contexto_agente["ultimo_producto_nombre"] = None
    contexto_agente["ultima_intencion"] = None


def _respuesta_ayuda():
    return formatear_respuesta_ayuda()


def procesar_pregunta(pregunta):
    if not normalizar_texto(pregunta):
        return "No entendí bien eso, amigo. Puedes preguntarme por stock, ubicaciones, movimientos o alertas."

    intencion = detectar_intencion_inventario(pregunta)
    introduccion = _introduccion_social(pregunta) if intencion else ""
    if not intencion:
        social = detectar_conversacion_social(pregunta)
        respuesta = generar_respuesta_social(social)
        return respuesta or ("No estoy seguro de lo que quisiste decir. "
                             "Intenta preguntarme por un producto o por el inventario.")

    try:
        if intencion == "stock_bajo":
            respuesta = consultar_productos_stock_bajo()
            contexto_agente["ultima_intencion"] = intencion
            return f"{introduccion} {respuesta}".strip()
        if intencion == "productos_agotados":
            respuesta = consultar_productos_agotados()
            contexto_agente["ultima_intencion"] = intencion
            return f"{introduccion} {respuesta}".strip()
        productos = buscar_producto_en_pregunta(pregunta)
        if (not productos and intencion in INTENCIONES_CON_PRODUCTO and
                contexto_agente["ultimo_producto_id"] and _es_seguimiento_contextual(pregunta)):
            productos = [{"id_producto": contexto_agente["ultimo_producto_id"],
                          "nombre": contexto_agente["ultimo_producto_nombre"]}]
        if not productos:
            return "No encontré un producto con ese nombre en el inventario."
        if len(productos) > 1:
            nombres = ", ".join(p["nombre"] for p in productos)
            return f"Encontré varios productos relacionados: {nombres}. Especifica cuál deseas consultar."
        producto = productos[0]
        contexto_agente.update({"ultimo_producto_id": producto["id_producto"],
                                "ultimo_producto_nombre": producto["nombre"],
                                "ultima_intencion": intencion})
        funciones = {"consultar_stock": consultar_stock_producto,
                     "consultar_ubicacion": consultar_ubicaciones_producto,
                     "stock_minimo": consultar_stock_minimo_producto,
                     "ultimo_retiro": consultar_ultimo_retiro,
                     "ultimo_movimiento": consultar_ultimo_movimiento,
                     "historial_producto": consultar_historial_producto}
        respuesta = funciones[intencion](producto["id_producto"])
        return f"{introduccion} {respuesta}".strip()
    except Exception:
        traceback.print_exc()
        return "Tuve un problema al consultar el inventario. Intenta nuevamente."
