"""Single background health scheduler. Camera/models are explicit checks only."""
import threading
import time
from core.system_state import state_manager

class HealthMonitor:
    def __init__(self):
        self.stop_event=threading.Event();self.thread=None
        self._lock=threading.RLock();self._checks={};self._due={};self._checklocks={}

    def register(self,name,callback,interval):
        with self._lock:
            self._checks[name]=(callback,interval);self._due.setdefault(name,0)
            self._checklocks.setdefault(name,threading.Lock())

    def check(self,name,force=False):
        with self._lock:callback,interval=self._checks[name];lock=self._checklocks[name]
        with lock:
            if not force and time.monotonic()<self._due[name]:return state_manager.get(name)
            try:callback()
            finally:
                with self._lock:self._due[name]=time.monotonic()+interval
        return state_manager.get(name)

    def start(self):
        with self._lock:
            if self.thread and self.thread.is_alive():return
            self.stop_event.clear()
            self.thread=threading.Thread(target=self._run,name='health-monitor',daemon=True);self.thread.start()

    def _run(self):
        while not self.stop_event.is_set():
            with self._lock:names=list(self._checks)
            for name in names:
                if self.stop_event.is_set():break
                try:self.check(name)
                except Exception:
                    state_manager.update(name,'ERROR','No se pudo completar la comprobación.',error='HEALTH_CHECK_FAILED')
            self.stop_event.wait(1)

    def close(self):
        self.stop_event.set()
        if self.thread and self.thread is not threading.current_thread():self.thread.join(30)

health_monitor=HealthMonitor()

def check_sql(force=False):
    return health_monitor.check('SQL',force)

def _sql():
    from core.database import conectar
    try:
        connection=conectar()
        try:connection.cursor().execute('SELECT 1').fetchone()
        finally:connection.close()
        state_manager.update('SQL','ONLINE','Consulta SQL comprobada.')
    except Exception:
        state_manager.update('SQL','OFFLINE','No se pudo conectar con SQL Server.',error='SQL_CONNECTION_FAILED')

def _telegram():
    from core.config_manager import obtener
    from integrations.telegram.telegram_service import comprobar_conexion,_credenciales,servicio_telegram
    if not obtener('telegram','habilitado'):
        state_manager.update('TELEGRAM','DISABLED','Notificaciones deshabilitadas.',expected=True);return
    token,chat=_credenciales()
    if not token or not chat:
        state_manager.update('TELEGRAM','OFFLINE','Telegram no configurado.',details={'chat_configured':bool(chat)},expected=True);return
    # A successful delivery is already a health observation; avoid another getChat.
    current=state_manager.get('TELEGRAM')
    if current.last_success and (time.time()-current.last_success.timestamp())<300:return
    comprobar_conexion()
    state_manager.update('TELEGRAM',details={'worker_running':bool(servicio_telegram.hilo and servicio_telegram.hilo.is_alive())})

health_monitor.register('SQL',_sql,30)
health_monitor.register('TELEGRAM',_telegram,300)

def check_telegram(force=False):return health_monitor.check('TELEGRAM',force)

def apply_configuration(config):
    """Configuration changes invalidate observations, never prove connectivity."""
    from integrations.arduino.led_service import servicio_led
    servicio_led.estado_conexion()  # Synchronize its existing hardware configuration.
    if not config['telegram']['habilitado']:
        state_manager.update('TELEGRAM','DISABLED','Notificaciones deshabilitadas.',expected=True)
    elif state_manager.get('TELEGRAM').status=='DISABLED':
        state_manager.update('TELEGRAM','UNVERIFIED','Pendiente de comprobar configuración nueva.',expected=True)
        with health_monitor._lock:health_monitor._due['TELEGRAM']=0
    if not config['jarvis']['tts_habilitado']:
        state_manager.update('TTS','DISABLED','Voz deshabilitada.',expected=True)
    elif state_manager.get('TTS').status=='DISABLED':
        state_manager.update('TTS','UNVERIFIED','Pendiente de reproducción.',expected=True)
