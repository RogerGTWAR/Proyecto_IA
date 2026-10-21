"""Domain publishers. They do not import Telegram, UI or alert persistence."""
from datetime import datetime
from uuid import uuid4
from core.event_bus import emitir
from core.event_types import normalizar


def _emisor(bus):
    if bus is None:return emitir
    def publicar(*args,**kwargs):
        from core.system_event import SystemEvent
        opciones={k:kwargs.pop(k) for k in ('transition','state','deduplicate') if k in kwargs}
        evento=SystemEvent(*args,**kwargs);bus.publish(evento,**opciones);return evento
    return publicar


def publicar_stock(producto, stock, minimo, nombre='', codigo='', nivel=None, alertas_actualizadas=False,bus=None):
    emitir=_emisor(bus)
    estado = 'AGOTADO' if stock == 0 else 'BAJO' if stock <= minimo else 'NORMAL'
    tipo = {'AGOTADO': 'STOCK_AGOTADO', 'BAJO': 'STOCK_BAJO', 'NORMAL': 'STOCK_NORMALIZADO'}[estado]
    gravedad = nivel or ('CRITICA' if stock == 0 or stock <= minimo/2 else 'ALTA' if estado == 'BAJO' else 'INFO')
    return emitir(tipo, 'INVENTARIO', 'stock', 'Stock '+estado.lower(),
                  f'{nombre or codigo or producto}: {stock} disponibles; mínimo {minimo}.', gravedad,
                  tipo+':'+str(producto), dict(id_producto=producto, producto=nombre, codigo=codigo,
                  stock_actual=stock, stock_minimo=minimo,alertas_actualizadas=alertas_actualizadas),
                  transition='stock:'+str(producto), state=estado)


def publicar_prediccion(producto, resultado, notificar=True,bus=None):
    emitir=_emisor(bus)
    from core.system_state import state_manager
    state_manager.update('PREDICCION','ONLINE','Motor de predicción consultado.',
        details={'datos_suficientes':bool(resultado.get('datos_suficientes'))})
    # A successful calculation is factual; insufficient history remains explicitly marked.
    datos = {k: v for k, v in resultado.items() if k != 'consumo_diario'}
    datos['id_producto'] = producto
    datos['notificar'] = bool(notificar)
    emitir('PREDICCION_GENERADA', 'PREDICCION', 'prediccion_stock',
           'Predicción calculada' if resultado.get('datos_suficientes') else 'Predicción sin datos suficientes',
           resultado.get('explicacion') or resultado.get('mensaje') or 'Cálculo completado.', data=datos)
    riesgo = normalizar(resultado.get('riesgo', 'SIN DATOS'))
    if not notificar:
        if bus is not None:bus.seed_state('riesgo:'+str(producto)+':operativo',riesgo)
        return
    tipo = {'MEDIO': 'RIESGO_MEDIO', 'ALTO': 'RIESGO_ALTO', 'CRITICO': 'RIESGO_CRITICO'}.get(riesgo, 'RIESGO_AGOTAMIENTO')
    emitir(tipo, 'PREDICCION', 'prediccion_stock', 'Riesgo '+riesgo.lower(),
           resultado.get('explicacion') or resultado.get('mensaje') or 'Sin riesgo estimable.',
           {'MEDIO': 'MEDIA', 'ALTO': 'ALTA', 'CRITICO': 'CRITICA'}.get(riesgo, 'INFO'),
           'RIESGO:'+str(producto)+':'+riesgo, datos,
           transition='riesgo:'+str(producto)+':'+('operativo' if notificar else 'consulta'), state=riesgo)


def publicar_anomalia(datos):
    referencia = 'anomalia:'+str(datos['id_anomalia']) if datos.get('id_anomalia') else 'anomalia:'+str(datos['id_detalle'])+':'+str(datos['tipo_anomalia'])
    return emitir('ANOMALIA_DETECTADA', 'ANOMALIAS', 'deteccion_anomalias', 'Anomalía detectada',
                  datos.get('motivo', 'Movimiento inusual registrado.'), datos.get('nivel', 'ALTA'),
                  referencia, datos, deduplicate=True)


def informar_estado_componente(nombre, correcto, detalle, esperado=False):
    """Compatibility producer; only the state manager publishes transitions."""
    from core.system_state import state_manager,key
    service=key(nombre)
    if service not in state_manager.snapshot():return
    activity='STREAMING' if service=='CAMARA' and correcto else 'IDLE'
    status='ONLINE' if correcto else 'OFFLINE' if service in ('SQL','CAMARA','ARDUINO') else 'ERROR'
    if not correcto and service=='SFACE' and state_manager.get(service).details.get('model_loaded'):status='DEGRADED'
    return state_manager.update(service,status,detalle,available=bool(correcto),
        activity=activity,expected=esperado,error=None if correcto or esperado else 'SERVICE_FAILED')


def publicar_rostro_desconocido(resultado, frame, camara='Cámara facial', zona='Sin zona configurada', referencia=None):
    estado = resultado.get('estado_identidad', resultado.get('estado'))
    if str(resultado.get('motor', 'sface')).lower() not in ('sface', 'embeddings'): return None
    if estado not in ('DESCONOCIDO', 'NO_RECONOCIDO') or resultado.get('reconocido'): return None
    if resultado.get('calidad_estado') not in (None, 'CALIDAD_OK', 'CALIDAD_ACEPTABLE'): return None
    if estado == 'NO_RECONOCIDO' and not resultado.get('identidad_evaluada'): return None
    referencia = referencia or 'facial:'+uuid4().hex
    data = dict(resultado, camara=camara, zona=zona, fecha_hora=datetime.now().astimezone().isoformat())
    emitir('ROSTRO_NO_RECONOCIDO', 'FACIAL', 'reconocimiento_embeddings', 'Persona no reconocida',
           'Rostro evaluado sin coincidencia válida.', 'ALTA', referencia, data, image=frame, deduplicate=True)
    return dict(encolado=True, estado='PENDIENTE', id_evento=referencia)


def publicar_reconocimiento_empleado(resultado, frame, referencia, camara='Cámara facial'):
    if str(resultado.get('motor', 'sface')).lower() not in ('sface', 'embeddings'): return None
    if not resultado.get('reconocido') or not resultado.get('id_empleado') or frame is None: return None
    emitir('ROSTRO_RECONOCIDO', 'FACIAL', 'reconocimiento_embeddings', 'Empleado reconocido',
           str(resultado.get('nombre') or 'Identidad confirmada por el motor facial.'), 'INFO', referencia,
           dict(resultado, camara=camara, fecha_hora=datetime.now().astimezone().isoformat()), image=frame, deduplicate=True)
    return dict(encolado=True, estado='PENDIENTE', id_evento=referencia)


def publicar_vigilancia(datos, parte='foto'):
    from core.audit_service import use_context
    with use_context(datos.get('_audit_context'),origin='automatic'):
        return _publicar_vigilancia(datos,parte)

def _publicar_vigilancia(datos, parte='foto'):
    tipo = {'INTRUSIÓN': 'INTRUSION_DETECTADA', 'INTRUSION': 'INTRUSION_DETECTADA',
            'DESCONOCIDO': 'PERSONA_DESCONOCIDA', 'EMPLEADO RECONOCIDO': 'PERSONA_RECONOCIDA'}.get(datos.get('tipo_evento'), 'PERSONA_DETECTADA')
    if parte == 'identidad' or parte == 'video': tipo = 'EVIDENCIA_ACTUALIZADA'
    referencia = 'vigilancia:'+str(datos['id_evento'])+':'+parte
    emitir(tipo, 'VIGILANCIA', 'vigilancia_yolo', datos.get('tipo_evento', 'Persona detectada'),
           'Evento de cámara '+str(datos.get('camara', ''))+' en '+str(datos.get('zona', '')),
           datos.get('nivel', 'ALTA'), referencia, datos, image=datos.get('captura'), video=datos.get('clip'),
           metadata={'parte': parte}, deduplicate=parte != 'identidad')
    return dict(enviado=False, estado='PENDIENTE', detalle='Evento publicado en el bus central.')
