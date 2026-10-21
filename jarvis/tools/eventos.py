"""Queries over events actually emitted in this process; no invented history."""
from core.event_bus import event_store


def obtener_eventos_recientes(limite=10):
    return [e.to_dict() for e in event_store.get_recent_events(limite)]


def obtener_eventos_criticos(limite=10):
    return [e.to_dict() for e in event_store.get_events_by_severity('CRITICA', limite)]


def obtener_ultimo_evento(tipo=None):
    rows = event_store.get_recent_events(1, type=tipo)
    return rows[0].to_dict() if rows else None


def obtener_eventos_categoria(categoria, limite=10):
    return [e.to_dict() for e in event_store.get_events_by_category(categoria, limite)]


def responder_eventos(texto):
    import re
    if re.search(r'\b(?:que (?:acaba de pasar|paso recientemente|ha pasado|ocurrio recientemente)|eventos recientes|actividad reciente del sistema)\b', texto):
        rows = obtener_eventos_recientes(); vacio = 'No hay eventos registrados recientemente en esta sesión.'
    elif re.search(r'\b(?:hubo|hay|ocurrio|detectaste)\b.*\bintrusion(?:es)?\b', texto):
        rows = [e.to_dict() for e in event_store.get_events_by_type('INTRUSION_DETECTADA', 10)]
        vacio = 'No hay intrusiones registradas recientemente en esta sesión.'
    elif re.search(r'\balgo (?:critico|urgente)\b', texto):
        rows = obtener_eventos_criticos(); vacio = 'No hay eventos críticos registrados recientemente en esta sesión.'
    else: return None
    return rows, ('Eventos recientes de esta sesión:\n'+'\n'.join(
        e['timestamp'][11:19]+' · '+e['title']+': '+e['message'] for e in rows[:5])) if rows else vacio
