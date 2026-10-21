"""Comprobaciones reales; no inferir disponibilidad solo por una configuración."""
from datetime import datetime
from core.system_state import state_manager, NAMES
_modelo_facial=None

def probar_base():
    from core.health_monitor import check_sql
    value=check_sql(force=True)
    return {'estado':value.status,'detalle':value.message}


def probar_camara():
    from ai.facial.reconocimiento_cnn import _bloqueo_camara
    from ai.facial.pipeline_facial import cargar_configuracion
    from surveillance.camara_utils import abrir_camara
    if not _bloqueo_camara.acquire(blocking=False): return {'estado':'NO DISPONIBLE','detalle':'La cámara está en uso. Espere a que termine el reconocimiento.'}
    try:
        cfg=cargar_configuracion(); cam=abrir_camara(cfg['fuente_video'],cfg['resolucion'])
        try:
            ok,frame=cam.read()
            if not ok: raise RuntimeError('No se pudo leer el dispositivo seleccionado.')
            return {'estado':'DISPONIBLE','detalle':f'Lectura comprobada · {frame.shape[1]}x{frame.shape[0]} · fuente '+('USB '+str(cfg['fuente_video']) if isinstance(cfg['fuente_video'],int) else 'IP / RTSP')}
        finally: cam.release()
    finally: _bloqueo_camara.release()

def probar_microfono():
    import sounddevice as sd
    from jarvis import asistente_voz as voz
    if not voz._bloqueo_microfono.acquire(blocking=False): return {'estado':'NO DISPONIBLE','detalle':'Audio ocupado por escucha o reproducción.'}
    try:
        m=voz.obtener_microfono_predeterminado()
        with sd.RawInputStream(device=m['indice'],samplerate=voz.FRECUENCIA_MUESTREO,channels=1,dtype='int16') as s: s.read(800)
        return {'estado':'DISPONIBLE','detalle':m['nombre']+' · apertura y lectura comprobadas; audio descartado'}
    finally: voz._bloqueo_microfono.release()

def probar_jarvis():
    from jarvis.agente_inventario import procesar_consulta
    r=procesar_consulta('¿Quién eres?',True)
    if not r.get('respuesta'): raise RuntimeError('El agente no devolvió respuesta.')
    return {'estado':'DISPONIBLE','detalle':'Procesador consultado correctamente. La conexión SQL se comprueba por separado.'}

def probar_tts():
    from jarvis.asistente_voz import hablar
    motor=hablar('Prueba de voz del sistema.')
    return {'estado':'DISPONIBLE','detalle':'Reproducción completada con '+motor if motor else 'Reproducción cancelada.'}

def recargar_facial():
    global _modelo_facial
    from ai.facial.pipeline_facial import MotorEmbeddings,cargar_configuracion
    _modelo_facial=MotorEmbeddings()
    from ai.facial.pipeline_facial import cargar_politica,GaleriaEmbeddings,cargar_configuracion
    galeria=GaleriaEmbeddings();politica=cargar_politica(galeria,cargar_configuracion())
    ready=bool(len(galeria.vectores)) and politica is not None
    state_manager.track_resource('SFACE',_modelo_facial,available=ready,message='Modelo facial cargado para diagnóstico.',
        details={'model_loaded':True,'embeddings':len(galeria.vectores),'calibrated':politica is not None})
    return {'estado':'CARGADO' if ready else 'SIN CONFIGURAR','detalle':'YuNet + SFace cargados para diagnóstico. '+('Calibración y galería válidas.' if ready else 'Falta galería o calibración válida para confirmar identidades.')}

def recargar_cnn():
    from ai.facial.reconocimiento_cnn import _cargar_recursos
    _cargar_recursos()
    return {'estado':'CARGADO','detalle':'CNN cargada; independiente de SFace.'}

def recargar_voz():
    from jarvis import asistente_voz as v
    if v._bloqueo_microfono.locked(): raise RuntimeError('Espere a que termine la operación de audio.')
    with v._bloqueo_modelo: v._modelo_voz=None
    v.cargar_modelo_voz()
    return {'estado':'CARGADO','detalle':str(v.obtener_ruta_modelo())}

ACCIONES={'Base de datos':probar_base,'Cámara':probar_camara,'Micrófono':probar_microfono,
          'JARVIS':probar_jarvis,'Reconocimiento facial':recargar_facial,'Reconocimiento de voz':recargar_voz,'Motor TTS':probar_tts,'CNN':recargar_cnn}
def comprobar(nombre):
    """Explicit diagnostics run only on demand, never while rendering a view."""
    from core.system_state import key
    service=key(nombre)
    if service=='CAMARA' and state_manager.get(service).activity=='STREAMING':
        current=state_manager.get(service)
        return {'estado':current.status,'detalle':current.message,'comprobado':current.updated_at}
    if state_manager.get(service).status in ('UNVERIFIED','STARTING'):
        state_manager.update(service,'STARTING','Comprobando componente.',activity='INITIALIZING',expected=True)
    else:state_manager.set_activity(service,'PROCESSING')
    try:
        result=ACCIONES[nombre]()
        status=result['estado']
        if service=='SQL':
            state_manager.set_activity(service,'IDLE')
            return result
        value='ONLINE' if status in ('DISPONIBLE','CARGADO','ONLINE') else 'DEGRADED' if status=='SIN CONFIGURAR' else 'ERROR'
        if service in ('TTS','VOSK','SFACE','CNN'):
            state_manager.set_activity(service,'IDLE')
        else:state_manager.update(service,value,result['detalle'],activity='IDLE',available=value=='ONLINE')
    except Exception:
        if service in ('TTS','VOSK','SFACE','CNN') and state_manager.get(service).status in ('OFFLINE','ERROR','DEGRADED'):
            state_manager.set_activity(service,'IDLE')
        else:state_manager.update(service,'ERROR','No se pudo comprobar el componente.',activity='IDLE',error='DIAGNOSTIC_FAILED')
    value=state_manager.get(service)
    return {'estado':value.status,'detalle':value.message,'comprobado':value.updated_at}


def obtener_estado_sistema():
    snapshot=state_manager.snapshot()
    return {'componentes':{NAMES.get(name,name):dict(value,estado=value['status'],detalle=value['message'])
            for name,value in snapshot.items()},'snapshot':snapshot,'actualizado':datetime.now().astimezone()}
