"""Production consumers, installed once. Each slow destination has its own queue."""
from threading import RLock
from core.event_bus import event_bus, emitir
from core.system_event import thaw, FrameSnapshot
from core.event_logger import EventLogger

_lock = RLock()
_logger = None
PRESENCIA_NOTIFICABLES=('PERSONA_DESCONOCIDA_HABITACION','EMPLEADO_ENTRO_HABITACION',
                      'EMPLEADO_SALIO_HABITACION','CAMARA_2_DESCONECTADA')

ALERTABLES = ('STOCK_BAJO', 'STOCK_AGOTADO', 'STOCK_NORMALIZADO', 'INTRUSION_DETECTADA',
              'ROSTRO_NO_RECONOCIDO', 'PERSONA_DESCONOCIDA', 'ANOMALIA_DETECTADA', 'MOVIMIENTO_INUSUAL',
              'EVIDENCIA_ACTUALIZADA','PREDICCION_GENERADA')
NOTIFICABLES = ('STOCK_BAJO', 'STOCK_AGOTADO', 'ANOMALIA_DETECTADA', 'MOVIMIENTO_INUSUAL',
                'INTRUSION_DETECTADA', 'PERSONA_DESCONOCIDA', 'PERSONA_RECONOCIDA',
                'ROSTRO_RECONOCIDO', 'ROSTRO_NO_RECONOCIDO', 'RIESGO_ALTO', 'RIESGO_CRITICO',
                'SQL_DESCONECTADO', 'CAMARA_DESCONECTADA', 'JARVIS_ERROR', 'YOLO_ERROR',
                'SFACE_ERROR', 'ARDUINO_DESCONECTADO', 'EVIDENCIA_ACTUALIZADA', 'ALERTA_CREADA')+PRESENCIA_NOTIFICABLES


def consumir_alerta(event):
    from inventory import alertas
    data = thaw(event.data)
    result = None
    if event.type=='PREDICCION_GENERADA':
        from ai.prediction.prediccion_stock import _actualizar_alerta
        dias=data.get('dias_restantes_promedio')
        _actualizar_alerta(data['id_producto'],data['producto'],dias,
                          resolver=not data.get('datos_suficientes') or dias is None)
        return
    if event.type in ('STOCK_BAJO', 'STOCK_AGOTADO', 'STOCK_NORMALIZADO'):
        # SQL stock alerts remain part of the stock transaction. This also supports
        # external SQL changes detected by the observer, using the same idempotent rule.
        if not data.get('alertas_actualizadas'):
            alertas.verificar_alertas_stock(data['id_producto'], publicar_stock_evento=False)
        return
    if event.type == 'INTRUSION_DETECTADA' or (event.type == 'EVIDENCIA_ACTUALIZADA' and event.metadata.get('parte') == 'identidad' and data.get('tipo_evento') in ('INTRUSIÓN', 'INTRUSION')):
        result = alertas.registrar_alerta_intrusion(data)
    elif event.type in ('ROSTRO_NO_RECONOCIDO', 'PERSONA_DESCONOCIDA'):
        result = alertas.registrar_alerta_empleado_no_reconocido()
    elif event.type in ('ANOMALIA_DETECTADA','MOVIMIENTO_INUSUAL'):
        result = alertas.registrar_alerta_anomalia_evento(data)
    if result:
        emitir('ALERTA_CREADA' if result.get('creada',True) else 'ALERTA_ACTUALIZADA', 'ALERTAS', 'alertas', 'Alerta registrada', event.message,
               event.severity, 'alerta:'+str(result['id_alerta']),
               dict(result, evento_origen=event.id,id_evento=data.get('id_evento')), metadata={'derivada': True})


def consumir_estado_vigilancia(event):
    """Acknowledge SQL persistence to the evidence service, never to Tk widgets."""
    if not event.data.get('id_evento'): return
    from surveillance.vigilancia_yolo import servicio_vigilancia
    evidencia=servicio_vigilancia.evidencia
    if evidencia is None: return
    with evidencia.lock:
        original=next((e for e in evidencia.recientes if e['id_evento']==event.data['id_evento']),None)
        if original is not None:
            evidencia._actualizar(original,sql_estado='registrado',id_alerta=event.data['id_alerta'])


def consumir_telegram(event):
    from integrations.telegram import telegram_service as telegram
    data = thaw(event.data)
    if event.metadata.get('esperado'): return
    if event.type in PRESENCIA_NOTIFICABLES:
        if not data.get('notificar',False):return
        from jarvis.jarvis_personality import mensaje_presencia
        return telegram.servicio_telegram.notificar('vigilancia',event.title,mensaje_presencia(data),
            event.severity,datos=data,imagen=event.image,referencia=event.reference)
    # Derived SQL alert events are internal, never a second Telegram notification.
    if event.type == 'ALERTA_CREADA' and not event.metadata.get('externa'): return
    if event.type.startswith('RIESGO_') and not data.get('notificar', True): return
    if event.type == 'EVIDENCIA_ACTUALIZADA' and event.metadata.get('parte') != 'video': return
    if event.category == 'VIGILANCIA':
        video = event.metadata.get('parte') == 'video'
        data['alerta_por_event_bus'] = True
        return telegram.enviar_evento(data, event.video if video else event.image, video=video)
    if event.type in ('ROSTRO_RECONOCIDO', 'ROSTRO_NO_RECONOCIDO'):
        frame = event.image.array() if isinstance(event.image, FrameSnapshot) else None
        if event.type == 'ROSTRO_RECONOCIDO':
            return telegram.notificar_reconocimiento_empleado(data, frame, event.reference, camara=data.get('camara', 'Cámara facial'))
        return telegram.notificar_rostro_desconocido(data, frame, camara=data.get('camara', 'Cámara facial'),
                    zona=data.get('zona', 'Sin zona configurada'), referencia=event.reference, crear_alerta=False)
    categoria = {'INVENTARIO': 'inventario', 'ANOMALIAS': 'anomalias', 'PREDICCION': 'prediccion'}.get(event.category, 'sistema' if event.category in ('SISTEMA', 'ARDUINO') else 'alertas')
    # Each recurrence transition has a new UUID, while immutable incidents retain
    # their stable SQL/evidence reference for the existing persistent deduplicator.
    referencia = event.reference if event.type in ('ANOMALIA_DETECTADA', 'ALERTA_CREADA') else event.reference+':'+event.id
    return telegram.servicio_telegram.notificar(categoria, event.title, event.message, event.severity,
                datos=data, imagen=event.image, video=event.video, referencia=referencia)


def iniciar_eventos(bus=None, logger=None):
    global _logger
    bus = bus if bus is not None else event_bus
    with _lock:
        if logger is None:
            if _logger is None: _logger = EventLogger()
            logger = _logger
        bus.subscribe('*', logger, name='log', asynchronous=True)
        bus.subscribe(ALERTABLES, consumir_alerta, name='alertas', asynchronous=True)
        bus.subscribe(NOTIFICABLES, consumir_telegram, name='telegram', asynchronous=True)
        bus.subscribe(('ALERTA_CREADA','ALERTA_ACTUALIZADA'),consumir_estado_vigilancia,
                      name='evidencia-estado',asynchronous=True)
    return bus


def cerrar_eventos():
    global _logger
    from core.automatizacion_inventario import automatizacion
    automatizacion.cerrar()
    event_bus.flush(timeout=2)
    event_bus.close()
    if _logger: _logger.close(); _logger = None
