"""Cliente opcional para interpretación estructurada mediante Ollama local."""

import json
import os
import time
import urllib.error
import urllib.request

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434/api/chat")
MODELO_OLLAMA = os.getenv("OLLAMA_MODEL", "qwen2.5:3b")
TIMEOUT_LLM = float(os.getenv("JARVIS_LLM_TIMEOUT", "3.0"))

ACCIONES_PERMITIDAS = {
    "consultar_stock", "consultar_ubicacion", "ultimo_movimiento", "ultimo_retiro",
    "stock_bajo", "productos_agotados", "prediccion_agotamiento", "consultar_alertas",
    "consultar_empleado", "historial_producto", "consultar_movimientos",
    "movimientos_empleado", "consultar_anomalias", "resumen_inventario", "stock_minimo",
    "consultar_producto", "listar_productos", "consultar_subject",
    "consultar_rostro_empleado", "listar_rostros", "empleados_sin_rostro",
    "consultar_reabastecimiento", "empleados_activos", "movimientos_hoy",
    "alertas_reconocimiento", "rostro_y_movimientos", "ayuda",
    "producto_menor_stock",
}

PROMPT_SISTEMA = """Eres el intérprete de Jarvis, asistente de inventario. Selecciona una o hasta
tres acciones permitidas y extrae texto de producto, empleado o subject. Nunca inventes datos,
nunca generes SQL y nunca solicites modificar información. Para una acción devuelve:
{"intencion":"accion", "entidades":{"producto":null,"empleado":null,"subject":null}}.
Para una consulta combinada agrega "acciones":[{"herramienta":"accion"}, ...].
Acciones: """ + ", ".join(sorted(ACCIONES_PERMITIDAS))

_no_disponible_hasta = 0.0


def _extraer_json(texto):
    inicio, fin = texto.find("{"), texto.rfind("}")
    if inicio < 0 or fin <= inicio:
        return None
    try:
        return json.loads(texto[inicio:fin+1])
    except (ValueError, TypeError):
        return None


def validar_decision(datos):
    if not isinstance(datos, dict):
        return None
    acciones = []
    candidatas = datos.get("acciones", [])
    if isinstance(candidatas, list):
        for accion in candidatas[:3]:
            nombre = accion.get("herramienta") if isinstance(accion, dict) else None
            if nombre in ACCIONES_PERMITIDAS and nombre not in acciones:
                acciones.append(nombre)
    intencion = datos.get("intencion") or (acciones[0] if acciones else None)
    if intencion not in ACCIONES_PERMITIDAS:
        return None
    entidades = datos.get("entidades") if isinstance(datos.get("entidades"), dict) else {}
    limpias = {}
    for clave in ("producto", "empleado", "subject"):
        valor = entidades.get(clave)
        limpias[clave] = str(valor).strip()[:120] if valor else None
    return {"intencion": intencion, "entidades": limpias,
            "acciones": acciones or [intencion]}


def interpretar_con_llm(mensaje, contexto=None):
    """Devuelve decisión, latencia y error. Nunca lanza si Ollama no está disponible."""
    global _no_disponible_hasta
    ahora = time.monotonic()
    if ahora < _no_disponible_hasta:
        return None, 0.0, "Ollama no disponible (cache)"
    contexto_minimo = {
        "ultimo_producto": (contexto or {}).get("ultimo_producto_nombre"),
        "ultimo_empleado": (contexto or {}).get("ultimo_empleado_nombre"),
        "ultima_intencion": (contexto or {}).get("ultima_intencion"),
        "intencion_pendiente": (contexto or {}).get("intencion_pendiente"),
        "tipo_entidad_pendiente": (contexto or {}).get("tipo_entidad_pendiente"),
        "estado_dialogo": (contexto or {}).get("estado_dialogo"),
        "ultimo_tema": (contexto or {}).get("ultimo_tema"),
        "candidatos": [{"codigo": p.get("codigo", p.get("codigo_ubicacion")), "nombre": p.get("nombre")}
                       for p in (contexto or {}).get("candidatos_ambiguos", [])[:10]],
    }
    from jarvis.herramientas_jarvis import obtener_descripciones
    prompt = PROMPT_SISTEMA + "\nDescripciones autorizadas: " + json.dumps(
        obtener_descripciones(), ensure_ascii=False, default=list
    )
    cuerpo = {"model": MODELO_OLLAMA, "stream": False, "format": "json",
              "options": {"temperature": 0},
              "messages": [{"role": "system", "content": prompt},
                           {"role": "user", "content": json.dumps(
                               {"mensaje": mensaje, "contexto": contexto_minimo}, ensure_ascii=False)}]}
    peticion = urllib.request.Request(OLLAMA_URL, data=json.dumps(cuerpo).encode("utf-8"),
                                     headers={"Content-Type": "application/json"}, method="POST")
    inicio = time.perf_counter()
    try:
        with urllib.request.urlopen(peticion, timeout=TIMEOUT_LLM) as respuesta:
            datos = json.loads(respuesta.read().decode("utf-8"))
        contenido = datos.get("message", {}).get("content", "")
        decision = validar_decision(_extraer_json(contenido))
        return decision, time.perf_counter()-inicio, None if decision else "JSON LLM inválido"
    except (OSError, ValueError, urllib.error.URLError) as error:
        _no_disponible_hasta = time.monotonic() + 30.0
        return None, time.perf_counter()-inicio, str(error)


def estado_llm():
    return {"modelo": MODELO_OLLAMA, "url": OLLAMA_URL,
            "disponible_en_cache": time.monotonic() >= _no_disponible_hasta}
