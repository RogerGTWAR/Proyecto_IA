"""Shared, immutable service observations. No I/O or model initialization."""
from dataclasses import dataclass, field, replace
from datetime import datetime
from enum import Enum
from threading import RLock
from core.system_event import freeze, thaw
from core.event_types import normalizar

class Status(str,Enum):
    ONLINE='ONLINE'
    OFFLINE='OFFLINE'
    STARTING='STARTING'
    DEGRADED='DEGRADED'
    UNVERIFIED='UNVERIFIED'
    DISABLED='DISABLED'
    ERROR='ERROR'

ACTIVITIES=frozenset('IDLE INITIALIZING STREAMING SENDING LISTENING SPEAKING PROCESSING SIMULATION STOPPING'.split())
_UNSET=object()
SERVICES=('SQL','CAMARA','CAMARA_1','CAMARA_2','SFACE','YOLO','TELEGRAM','ARDUINO','JARVIS','TTS','VOSK','PREDICCION','ANOMALIAS','EVENT_BUS','MICROFONO','CNN')
CRITICAL_SERVICES=frozenset({'SQL'})
FEATURE_DEPENDENCIES={'INVENTARIO':('SQL',),'FACIAL':('CAMARA','SFACE'),'VIGILANCIA':('CAMARA','YOLO')}
NAMES={'SQL':'Base de datos','CAMARA':'Cámara','SFACE':'SFace','YOLO':'YOLO','TELEGRAM':'Telegram',
       'CAMARA_1':'Cámara 1 · Intrusión','CAMARA_2':'Cámara 2 · Presencia',
       'ARDUINO':'Arduino','JARVIS':'JARVIS','TTS':'Voz de JARVIS','VOSK':'Vosk',
       'PREDICCION':'Predicción','ANOMALIAS':'Anomalías','EVENT_BUS':'Bus de eventos','MICROFONO':'Micrófono','CNN':'CNN'}
ALIASES={'BASE_DE_DATOS':'SQL','CAMARA_EMPLEADOS':'CAMARA','SFACE_EMPLEADOS':'SFACE',
         'VIGILANCIA':'YOLO','WORKER_TELEGRAM':'TELEGRAM','RECONOCIMIENTO_FACIAL':'SFACE',
         'MOTOR_TTS':'TTS','RECONOCIMIENTO_DE_VOZ':'VOSK'}
CONNECTION_EVENTS={'SQL':('SQL_CONECTADO','SQL_DESCONECTADO'), 'CAMARA':('CAMARA_CONECTADA','CAMARA_DESCONECTADA'),
    'SFACE':('SFACE_DISPONIBLE','SFACE_ERROR'),'YOLO':('YOLO_DISPONIBLE','YOLO_ERROR'),
    'TELEGRAM':('TELEGRAM_CONECTADO','TELEGRAM_ERROR'),'ARDUINO':('ARDUINO_CONECTADO','ARDUINO_DESCONECTADO'),
    'JARVIS':('JARVIS_DISPONIBLE','JARVIS_ERROR')}

def key(service):
    value=normalizar(service)
    return ALIASES.get(value,value)

@dataclass(frozen=True)
class ServiceState:
    service: str
    status: str='UNVERIFIED'
    available: bool=False
    message: str='Aún no verificado.'
    activity: str='IDLE'
    updated_at: object=None
    last_success: object=None
    last_error: object=None
    details: object=field(default_factory=dict)
    error: object=None
    revision: int=0

    def __post_init__(self): object.__setattr__(self,'details',freeze(self.details))

    def to_dict(self):
        return {k:thaw(getattr(self,k)) for k in self.__dataclass_fields__}

class SystemStateManager:
    def __init__(self):
        self._lock=RLock();self._states={s:ServiceState(s) for s in SERVICES}
        self._resources={}
        self._subscribers={};self.shutting_down=False

    def register(self,service):
        with self._lock:
            name=key(service)
            return self._states.setdefault(name,ServiceState(name))

    def get(self,service):
        with self._lock:return self._states[key(service)]

    def snapshot(self):
        with self._lock:return {k:v.to_dict() for k,v in self._states.items()}

    def get_all(self):return self.snapshot()
    def is_available(self,service):return self.get(service).available

    def subscribe(self,service,callback):
        token=object()
        with self._lock:self._subscribers[token]=(key(service) if service!='*' else '*',callback)
        return token
    def subscribe_all(self,callback):return self.subscribe('*',callback)
    def unsubscribe(self,token):
        with self._lock:self._subscribers.pop(token,None)

    def update(self,service,status=None,message=None,details=None,error=_UNSET,*,activity=None,available=None,expected=False):
        name=key(service)
        if activity is not None and activity not in ACTIVITIES:raise ValueError('Actividad no válida')
        with self._lock:
            old=self.register(name)
            value=Status(status if status is not None else old.status).value
            availability=(value=='ONLINE' if available is None and status is not None else old.available if available is None else bool(available))
            if value in ('OFFLINE','ERROR','UNVERIFIED','STARTING','DISABLED'):availability=False
            now=datetime.now().astimezone()
            from core.event_logger import limpiar
            current_error=(None if value=='ONLINE' and status is not None else old.error) if error is _UNSET else (
                type(error).__name__ if isinstance(error,BaseException) else limpiar(error) if error is not None else None)
            merged=thaw(old.details)
            if details is not None:merged.update(_safe_details(details))
            current=replace(old,status=value,available=availability,message=limpiar(message) if message is not None else old.message,
                activity=activity if activity is not None else old.activity,details=merged,error=current_error,
                updated_at=now,last_success=now if status is not None and availability and current_error is None else old.last_success,
                last_error=now if status is not None and (current_error is not None or value in ('ERROR','OFFLINE') and not expected) else old.last_error,
                revision=old.revision+1)
            self._states[name]=current
            transition=(old.status,old.available)!=(current.status,current.available)
            changed=transition or (old.activity,old.details,old.error)!=(current.activity,current.details,current.error)
            subscribers=list(self._subscribers.values()) if changed else []
            if transition and not self.shutting_down:self._publish(old,current,expected)
        for watched,callback in subscribers:
            if watched in ('*',name):
                try:callback(current)
                except Exception:
                    import logging
                    logging.getLogger('system_state').error('observer_error service=%s',name)
        return current

    def _publish(self,old,current,expected):
        from core.event_bus import emitir
        pair=CONNECTION_EVENTS.get(current.service)
        operational=current.status in ('ONLINE','OFFLINE','ERROR','DEGRADED')
        tipo=pair[0 if current.status=='ONLINE' else 1] if pair and operational and not (current.available and current.status!='ONLINE') else 'SERVICIO_ESTADO_CAMBIADO'
        severity=('INFO' if current.status=='ONLINE' or expected or not operational else
                  'CRITICA' if current.service in CRITICAL_SERVICES and not current.available else
                  'MEDIA' if current.status=='DEGRADED' else 'ALTA')
        emitir(tipo,'ARDUINO' if current.service=='ARDUINO' else 'SISTEMA','system_state',NAMES.get(current.service,current.service),
            current.message,severity,
            current.service+':'+current.status,data={'componente':current.service,'disponible':current.available,
            'anterior':old.status,'estado':current.status},metadata={'esperado':expected})

    def set_activity(self,service,activity):return self.update(service,activity=activity)

    def track_resource(self,service,resource,*,available,details,message):
        """Observe model lifetime without retaining models or loading them again."""
        import weakref
        name=key(service);identity=id(resource)
        def released(reference):
            with self._lock:
                owners=self._resources.get(name,{})
                if identity not in owners or owners[identity][0] is not reference:return
                owners.pop(identity)
                if not owners:
                    if self.get(name).status not in ('ERROR','UNVERIFIED'):
                        self.update(name,'OFFLINE','Recursos de modelo liberados.',details={'model_loaded':False},activity='IDLE',expected=True)
                    else:self.update(name,details={'model_loaded':False})
                else:
                    ready=any(item[1] for item in owners.values())
                    selected=next((item for item in owners.values() if item[1]),next(iter(owners.values())))
                    info=thaw(selected[2]);info['resource_count']=len(owners)
                    self.update(name,'ONLINE' if ready else 'DEGRADED',available=ready,details=info)
        try:reference=weakref.ref(resource,released)
        except TypeError:
            return self.update(name,'ONLINE' if available else 'DEGRADED',message,
                               details=dict(details,lifetime_tracking=False),available=available)
        with self._lock:
            owners=self._resources.setdefault(name,{})
            owners[identity]=(reference,bool(available),freeze(_safe_details(details)))
            ready=any(item[1] for item in owners.values())
            selected=next((item for item in owners.values() if item[1]),owners[identity])
            info=thaw(selected[2]);info['resource_count']=len(owners)
            if ready and not available:message='Existe otra instancia de modelo preparada.'
            return self.update(name,'ONLINE' if ready else 'DEGRADED',message,details=info,available=ready)
    def begin_shutdown(self):
        with self._lock:self.shutting_down=True

    def initialize(self,config):
        with self._lock:self.shutting_down=False
        for name in ('SQL','TELEGRAM','JARVIS','TTS','VOSK'):
            if self.get(name).status=='UNVERIFIED':self.update(name,'STARTING','Pendiente de inicialización.')
        arduino=config['arduino'];simulation=arduino['modo']=='simulacion'
        self.update('ARDUINO','DEGRADED' if simulation else 'OFFLINE','Simulación disponible; sin conexión física.' if simulation else 'Hardware sin conectar.',
            {'mode':'SIMULATION' if simulation else 'HARDWARE','port':arduino.get('puerto')},
            activity='SIMULATION' if simulation else 'IDLE',available=simulation,expected=True)
        if not config['telegram']['habilitado']:self.update('TELEGRAM','DISABLED','Notificaciones deshabilitadas.',expected=True)
        if not config['jarvis']['tts_habilitado']:self.update('TTS','DISABLED','Síntesis deshabilitada.',expected=True)

def _safe_details(details):
    from core.event_logger import limpiar
    blocked=('token','password','secret','authorization','credential','contrase')
    def clean(value):
        if isinstance(value,dict):return {k:clean(v) for k,v in value.items() if not any(w in str(k).lower() for w in blocked)}
        if isinstance(value,(list,tuple)):return [clean(v) for v in value]
        return limpiar(value) if isinstance(value,str) else value
    return clean(details)

state_manager=SystemStateManager()

def format_service_state(state):
    if isinstance(state,ServiceState):state=state.to_dict()
    status=state['status'];details=state.get('details',{})
    texts={'ONLINE':'En línea','OFFLINE':'Sin conexión','STARTING':'Iniciando','DEGRADED':'Degradado',
           'UNVERIFIED':'Sin verificar','DISABLED':'Deshabilitado','ERROR':'Error'}
    colors={'ONLINE':'#15803d','OFFLINE':'#b91c1c','STARTING':'#2563eb','DEGRADED':'#a16207','UNVERIFIED':'#64748b','DISABLED':'#64748b','ERROR':'#b91c1c'}
    activities={'IDLE':'En espera','INITIALIZING':'Inicializando','STREAMING':'Transmitiendo','SENDING':'Enviando',
        'LISTENING':'Escuchando','SPEAKING':'Hablando','PROCESSING':'Procesando','SIMULATION':'Simulación','STOPPING':'Deteniendo'}
    text=texts[status]
    if details.get('mode')=='SIMULATION':text+=' · Simulación'
    if state.get('activity','IDLE')!='IDLE':
        activity=activities.get(state['activity'],state['activity'])
        if activity not in text:text+=' · '+activity
    if details.get('provider'):text+=' · '+str(details['provider'])
    if details.get('fallback'):text+=' · Respaldo local'
    legacy='Simulación activa' if details.get('mode')=='SIMULATION' else {
        'ONLINE':'Conectado','OFFLINE':'Desconectado','ERROR':'Error'}.get(status,text)
    return {'text':text,'color':colors[status],'icon':'●','status':status,'message':state.get('message',''),'legacy_text':legacy}

def health_summary(snapshot=None):
    data=snapshot if snapshot is not None else state_manager.snapshot()
    if any(data[name]['status'] in ('OFFLINE','ERROR') for name in CRITICAL_SERVICES):return 'CRITICAL'
    return 'HEALTHY' if all(s['status']=='ONLINE' for s in data.values()) else 'DEGRADED'
