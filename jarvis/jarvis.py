"""Entrada común de escritorio, voz, API y Telegram; sin otra memoria ni router."""
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class JarvisResult:
    ok: bool
    intent: str
    respuesta: str
    datos: Any = field(default_factory=dict)
    accion_ejecutada: Optional[dict] = None
    requiere_confirmacion: bool = False
    requiere_aclaracion: bool = False
    extras: dict = field(default_factory=dict, repr=False)

    def to_dict(self):
        return dict(self.extras, ok=self.ok, intent=self.intent, intencion=self.intent,
                    respuesta=self.respuesta, datos=self.datos, accion_ejecutada=self.accion_ejecutada,
                    requiere_confirmacion=self.requiere_confirmacion,
                    requiere_aclaracion=self.requiere_aclaracion)


def procesar(mensaje, session_id='desktop', origen='desktop', event_id=None):
    from jarvis import agente_inventario as agente
    from core.audit_service import use_context, operation, capture_context, current_context, audit
    ctx = agente.obtener_contexto(session_id)
    with ctx.lock:
        pending = ctx.get('confirmacion_pendiente') or {}
        trace = pending.get('_audit_context') or ctx.get('_audit_pending_context')
        cached = getattr(ctx,'eventos',{}).get((origen,str(event_id))) if event_id is not None else None
        if cached: trace=cached.extras.get('audit_context') or trace
        if trace:
            trace=dict(trace,origin=current_context().origin if current_context() else origen)
        with use_context(trace, origin=origen, session_id=session_id):
            with operation('JARVIS', 'JARVIS_COMMAND') as record:
                audit.record('JARVIS', 'MESSAGE_RECEIVED', data={'length':len(str(mensaje))})
                result = _procesar(mensaje, session_id, origen, event_id)
                status = 'CONFIRMATION_REQUIRED' if result.requiere_confirmacion else (
                    'CANCELLED' if result.intent in ('cancelar_consulta','reiniciar_contexto') else
                    'REJECTED' if result.intent == 'confirmacion_vencida' else
                    'SUCCESS' if result.ok else 'FAILED')
                if cached: status='SKIPPED'
                record.update(status=status, data={'intent':result.intent, 'executed':result.accion_ejecutada is not None and not bool(cached),
                                                   'duplicate':bool(cached)})
                audit.record('JARVIS', 'JARVIS_INTENT', status, data={'intent':result.intent})
                if not cached and (result.requiere_confirmacion or result.requiere_aclaracion):
                    ctx['_audit_pending_context'] = capture_context()
                    if ctx.get('confirmacion_pendiente'):
                        ctx['confirmacion_pendiente']['_audit_context'] = capture_context()
                elif not cached: ctx.pop('_audit_pending_context', None)
                result.extras['audit_context'] = capture_context()
                return result


def _procesar(mensaje, session_id='desktop', origen='desktop', event_id=None):
    from jarvis import agente_inventario as agente
    from jarvis.tools import instalar
    instalar()
    from core.system_state import state_manager
    state_manager.update('JARVIS','ONLINE','Núcleo, router y herramientas cargados.')
    ctx = agente.obtener_contexto(session_id)
    with ctx.lock:
        # Un evento repetido devuelve su resultado sin volver a invocar herramientas.
        eventos = getattr(ctx, 'eventos', None)
        if eventos is None:
            ctx.eventos = eventos = OrderedDict()
        clave = (origen, str(event_id)) if event_id is not None else None
        if clave in eventos:
            from copy import deepcopy
            return deepcopy(eventos[clave])
        state_manager.set_activity('JARVIS','PROCESSING')
        try:
            r = agente.procesar_consulta(mensaje, estructurada=True,
                                        sesion='escritorio' if session_id == 'desktop' else session_id)
        except Exception:
            raise
        finally:
            state_manager.set_activity('JARVIS','IDLE')
        intent = r.get('intencion', 'desconocida')
        confirmacion = bool(r.get('confirmation') or ctx.get('confirmacion_pendiente'))
        aclaracion = bool(r.get('clarification') or intent == 'aclaracion' or
                          ctx.get('estado_dialogo', '').startswith('WAITING_FOR_') and not confirmacion)
        ejecutada = r.get('accion_ejecutada')
        if intent == 'accion_confirmada' and not ejecutada:
            ejecutada = ctx.get('ultima_accion')
        resultado = JarvisResult(intent not in ('error', 'accion_no_permitida', 'accion_no_disponible'),
            intent, r.get('respuesta', ''), r.get('datos', {}), ejecutada, confirmacion, aclaracion,
            dict(r, session_id='escritorio' if session_id == 'desktop' else session_id, canal=origen))
        if clave is not None:
            from copy import deepcopy
            eventos[clave] = deepcopy(resultado)
            while len(eventos) > 128:
                eventos.popitem(last=False)
        import logging
        logging.getLogger('jarvis').debug('[JARVIS] session=%s origin=%s intent=%s confirmation=%s clarification=%s action=%s',
            session_id, origen, intent, confirmacion, aclaracion,
            ejecutada.get('accion') if isinstance(ejecutada,dict) else None)
        return resultado


def procesar_consulta(pregunta, estructurada=False, sesion='escritorio', origen='desktop'):
    """Adaptador de firma histórica; todas las entradas pasan por procesar()."""
    r = procesar(pregunta, sesion, origen).to_dict()
    return r if estructurada else r['respuesta']
