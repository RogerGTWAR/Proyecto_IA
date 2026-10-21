"""Presencia por tracks, sin reglas de intrusión ni dependencia de Telegram."""
from collections import deque
from copy import deepcopy
from datetime import datetime
from pathlib import Path
import json
import math
import threading
import time
from uuid import uuid4

from core.paths import PROJECT_ROOT


def validar_configuracion_presencia(c):
    from urllib.parse import urlsplit
    for key in ('camera_source_employees','camera_source_intrusion'):
        source=c.get(key)
        if source is None and key=='camera_source_intrusion':continue
        if type(source) is int and source>=0:continue
        if isinstance(source,str):
            u=urlsplit(source)
            if u.scheme in ('rtsp','http','https') and u.netloc and not (u.username or u.password or u.query):continue
        raise ValueError('Presencia: use un índice USB o URL sin credenciales; las fuentes privadas se configuran en el entorno.')
    for k,lo,hi in (('presence_confidence',.05,1),('presence_image_size',320,960),
                   ('presence_fps_limit',1,30),('presence_confirm_frames',2,30),
                   ('presence_exit_timeout',1,60),('presence_face_interval',.3,30),
                   ('presence_revalidate_seconds',5,3600),('presence_unknown_frames',2,30)):
        v=c[k]
        if isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) or not lo<=v<=hi:
            raise ValueError(f'Presencia: {k} debe estar entre {lo} y {hi}.')
    for k in ('presence_image_size','presence_confirm_frames','presence_unknown_frames'):
        if type(c[k]) is not int:raise ValueError('Presencia: tamaños y número de muestras deben ser enteros.')
    if c['presence_image_size']%32:raise ValueError('Presencia: resolución YOLO múltiplo de 32.')
    for k in ('camera_name_employees','room_name'):
        if not isinstance(c[k],str) or not c[k].strip() or len(c[k])>120:raise ValueError('Presencia: nombre y habitación obligatorios, máximo 120 caracteres.')
    for k in ('presence_notify_unknown','presence_notify_entries','presence_notify_exits','presence_notify_errors'):
        if type(c[k]) is not bool:raise ValueError('Presencia: notificaciones requieren Sí o No.')
    return c


class RegistroPresencia:
    """Conteos de tracks confirmados; pérdidas breves no crean entradas/salidas."""
    def __init__(self,cfg,publicar=None,directory=None):
        from core.event_bus import emitir
        self.cfg=deepcopy(cfg);self.publicar=publicar or emitir
        self.directory=Path(directory) if directory else PROJECT_ROOT/'outputs'/'presencia'
        self.lock=threading.RLock();self.tracks={};self.historial=deque(maxlen=200)
        self.session=uuid4().hex;self.conteo=None
        try:
            with (self.directory/'historial.jsonl').open(encoding='utf-8') as f:lines=deque(f,maxlen=200)
            self.historial.extend(reversed([json.loads(line) for line in lines if line.strip()]))
        except (OSError,ValueError):pass

    def _emitir(self,tipo,t,frame=None,duracion=None):
        from core.audit_service import audit
        now=datetime.now().astimezone().isoformat();ident=uuid4().hex
        data={k:deepcopy(t.get(k)) for k in ('track_id','id_empleado','codigo_empleado','nombre','similitud_facial','estado_identidad')}
        data.update(empleado_id=t.get('id_empleado'),codigo=t.get('codigo_empleado'),
            camera=2,camera_id=2,camara=self.cfg['camera_name_employees'],zona=self.cfg['room_name'],
            timestamp=now,fecha_hora=now,id_evento=ident,tipo_evento=tipo,categoria='Presencia',
            identidad_texto=t.get('nombre') or t.get('estado_identidad','IDENTIDAD PENDIENTE'),
            descripcion=tipo.replace('_',' ').capitalize(),duracion=duracion,motor_facial='SFace')
        if tipo=='PERSONA_DESCONOCIDA_HABITACION':
            data['descripcion']='No pude asociar esta persona con ningún empleado registrado.'
        data['notificar']=(self.cfg['presence_notify_unknown'] if tipo=='PERSONA_DESCONOCIDA_HABITACION' else
            self.cfg['presence_notify_entries'] if tipo=='EMPLEADO_ENTRO_HABITACION' else
            self.cfg['presence_notify_exits'] if tipo=='EMPLEADO_SALIO_HABITACION' else False)
        snapshot=None
        if frame is not None and tipo=='PERSONA_DESCONOCIDA_HABITACION':
            import cv2
            try:
                self.directory.mkdir(parents=True,exist_ok=True)
                path=self.directory/(ident+'.jpg')
                if cv2.imwrite(str(path),frame):snapshot=str(path)
            except (OSError,cv2.error) as error:
                audit.record('VIGILANCIA','PRESENCE_SNAPSHOT','FAILED',error=error)
        self.historial.appendleft(data)
        # Un archivo por sesión, acotado con el mismo mecanismo rotativo de logs.
        self._guardar(data)
        audit.record('VIGILANCIA',tipo,data=data)
        if tipo=='EMPLEADO_ENTRO_HABITACION':audit.record('VIGILANCIA','EMPLEADO_IDENTIFICADO',data=data)
        self.publicar(tipo,'VIGILANCIA','presencia_empleados',tipo.replace('_',' '),data['descripcion'],
            severity='MEDIA' if tipo=='PERSONA_DESCONOCIDA_HABITACION' else 'INFO',
            reference='presencia:'+ident,data=data,image=snapshot)

    def _guardar(self,data):
        from logging.handlers import RotatingFileHandler
        import logging
        try:
            self.directory.mkdir(parents=True,exist_ok=True)
            # Se abre y cierra por evento; no queda un descriptor por sesión.
            handler=RotatingFileHandler(self.directory/'historial.jsonl',maxBytes=2_000_000,backupCount=3,encoding='utf-8')
            try:handler.emit(logging.LogRecord('presencia',logging.INFO,'',0,json.dumps(data,ensure_ascii=False),(),None))
            finally:handler.close()
        except OSError:
            logging.getLogger('vigilancia').exception('No se pudo conservar el historial de presencia.')

    def actualizar(self,detecciones,ahora,frame=None):
        with self.lock:
            vistos=set()
            for d in detecciones:
                i=d['track_id']
                if i in vistos:continue
                vistos.add(i)
                t=self.tracks.get(i)
                if t is None or ahora-t['visto']>self.cfg['presence_exit_timeout']:
                    if t and t['confirmado']:self._salir(t,ahora)
                    t=self.tracks[i]=dict(track_id=i,inicio=ahora,visto=ahora,frames=0,confirmado=False,
                        presente_desde=datetime.now().astimezone().isoformat(),estado_identidad='SIN EVIDENCIA FACIAL',
                        desconocidos=0,candidato=None,votos=0,entrada_empleado=False,unknown_notified=False)
                t['visto']=ahora;t['frames']+=1;t['bbox']=d['bbox'];t['confianza']=d.get('confianza')
                if not t.get('id_empleado') and d.get('estado_identidad')=='IDENTIDAD_NO_DISPONIBLE':
                    t['estado_identidad']='IDENTIFICACIÓN NO DISPONIBLE'
                # Solo cuentan resultados faciales nuevos, nunca copias repetidas en UI/YOLO.
                sample=(d.get('track_generacion'),d.get('face_sample'))
                if d.get('face_sample') is not None and sample!=t.get('sample'):
                    t['sample']=sample
                    if d.get('reconocido') and d.get('empleado_activo') and d.get('id_empleado'):
                        candidate=d['id_empleado']
                        t['votos']=t['votos']+1 if candidate==t['candidato'] else 1;t['candidato']=candidate
                        t['desconocidos']=0
                        # SFace ya exige consenso. Otra identidad requiere evidencia repetida.
                        if not t.get('id_empleado') or candidate==t['id_empleado'] or t['votos']>=3:
                            for k in ('id_empleado','codigo_empleado','nombre','similitud_facial'):t[k]=d.get(k)
                            t['estado_identidad']='EMPLEADO IDENTIFICADO'
                    elif d.get('identidad_evaluada') and d.get('estado_identidad')=='NO_RECONOCIDO':
                        t['desconocidos']+=1;t['votos']=0
                        if t['desconocidos']>=self.cfg['presence_unknown_frames']:
                            for k in ('id_empleado','codigo_empleado','nombre'):t.pop(k,None)
                            t['estado_identidad']='DESCONOCIDO'
                    elif not t.get('id_empleado'):
                        t['desconocidos']=0;t['votos']=0
                        t['estado_identidad']='IDENTIDAD PENDIENTE' if d.get('identidad_evaluada') else 'SIN EVIDENCIA FACIAL'
                if not t['confirmado'] and t['frames']>=self.cfg['presence_confirm_frames']:
                    t['confirmado']=True
                    if not t.get('id_empleado'):self._emitir('PERSONA_ENTRO_HABITACION',t)
                if t['confirmado'] and t.get('id_empleado') and not t['entrada_empleado']:
                    t['entrada_empleado']=True;self._emitir('EMPLEADO_ENTRO_HABITACION',t)
                if t['confirmado'] and t['estado_identidad']=='DESCONOCIDO' and not t['unknown_notified']:
                    t['unknown_notified']=True;self._emitir('PERSONA_DESCONOCIDA_HABITACION',t,frame)
            for i,t in list(self.tracks.items()):
                if ahora-t['visto']>self.cfg['presence_exit_timeout']:
                    if t['confirmado']:self._salir(t,ahora)
                    del self.tracks[i]
            count=self.conteos()
            signature=tuple(count.values())
            if signature!=self.conteo:
                self.conteo=signature
                self.publicar('OCUPACION_CAMBIO','VIGILANCIA','presencia_empleados','Ocupación actualizada',
                    data=dict(count,camera_id=2,camara=self.cfg['camera_name_employees'],notificar=False))

    def _salir(self,t,ahora):
        self._emitir('EMPLEADO_SALIO_HABITACION' if t.get('id_empleado') else 'PERSONA_SALIO_HABITACION',
                     t,duracion=round(max(0,t['visto']-t['inicio']),1))

    def presentes(self):
        with self.lock:return [deepcopy(t) for t in self.tracks.values() if t['confirmado']]

    def conteos(self):
        p=self.presentes()
        return dict(personas=len(p),identificados=sum(bool(t.get('id_empleado')) for t in p),
                    desconocidos=sum(t['estado_identidad']=='DESCONOCIDO' for t in p),
                    pendientes=sum(not t.get('id_empleado') and t['estado_identidad']!='DESCONOCIDO' for t in p))

    def invalidar(self):
        # Una caída de cámara no demuestra que las personas hayan salido.
        with self.lock:self.tracks.clear();self.conteo=None


class PresenciaEmpleados:
    def __init__(self):
        self.lock=threading.RLock();self.detener=threading.Event();self.hilo=None
        self.registro=None;self.facial=None;self.frame=None;self.fps=0.;self.estado='Inactivo';self.detalle='Sin observación actual.'

    def iniciar(self,cfg,detector_factory=None,captura_factory=None,facial_factory=None):
        validar_configuracion_presencia(cfg)
        from surveillance.vigilancia_yolo import cargar_detector
        from surveillance.identidad_vigilancia import IdentidadPorTrack
        with self.lock:
            if self.hilo and self.hilo.is_alive():raise ValueError('La cámara de presencia ya está en uso.')
            worker=getattr(self.facial,'hilo',None)
            if isinstance(worker,threading.Thread) and worker.is_alive():raise ValueError('SFace aún está cerrando. Espere un momento antes de iniciar otra sesión.')
            self.detener=threading.Event();self.registro=RegistroPresencia(cfg)
            self.estado='Iniciando';self.detalle='Abriendo cámara de presencia…';self.frame=None;self.fps=0
            from core.audit_service import capture_context,run_in_context
            self.hilo=threading.Thread(target=run_in_context,args=(capture_context(),self._ejecutar,
                deepcopy(cfg),detector_factory or cargar_detector,captura_factory,facial_factory or IdentidadPorTrack),
                name='presencia-yolo',daemon=True)
            self.hilo.start()

    def parar(self):self.detener.set()

    def obtener_estado(self):
        with self.lock:
            detalle=self.detalle
            if self.estado=='ONLINE' and getattr(self.facial,'disponible',None) is False:
                detalle+=' SFace no disponible; las identidades no se pueden confirmar.'
            return dict(estado=self.estado,detalle=detalle,fps=self.fps,frame=self.frame,
                activo=bool(self.hilo and self.hilo.is_alive()),disponible=self.estado=='ONLINE')

    def _ejecutar(self,cfg,detector_factory,captura_factory,facial_factory):
        from core.audit_service import audit
        from core.system_state import state_manager
        from core.event_bus import emitir
        from surveillance.camara_utils import CamaraUltimoFrame
        from surveillance.fuentes_camara import resolver_fuente,reservar,liberar
        import cv2
        source=resolver_fuente(cfg,2);reservada=False;facial=None;detector=None
        try:
            reservar(source,self);reservada=True
            detector=detector_factory(dict(cfg,image_size=cfg['presence_image_size']))
            facial=facial_factory(ttl=cfg['presence_exit_timeout'],intervalo=cfg['presence_face_interval'],
                                  revalidar=cfg['presence_revalidate_seconds'])
            self.facial=facial
            audit.record('VIGILANCIA','CAMARA_2_INICIADA',data={'camera_id':2})
            fallo_notificado=False
            while not self.detener.is_set():
                captura=None
                try:
                    captura=(captura_factory(source,[1280,720]) if captura_factory else
                             CamaraUltimoFrame(source,[1280,720],servicio='CAMARA_2')).iniciar()
                    # Un tracker nuevo tras reconexión no debe heredar identidades anteriores.
                    if fallo_notificado and getattr(detector,'predictor',None) is not None:
                        for tracker in getattr(detector.predictor,'trackers',[]):tracker.reset()
                    self.registro.invalidar()
                    state_manager.update('CAMARA_2','STARTING','Esperando imágenes de presencia.',activity='INITIALIZING',expected=True)
                    anterior=-1;ultimo=time.monotonic();conectada_desde=ultimo;marcas=deque(maxlen=30)
                    while not self.detener.is_set():
                        inicio=time.monotonic();numero,frame=captura.leer()
                        if captura.error:raise RuntimeError('Lectura de cámara interrumpida.')
                        if frame is None or numero==anterior:
                            if inicio-ultimo>8:raise RuntimeError('La cámara no entrega imágenes.')
                            self.detener.wait(.02);continue
                        anterior=numero;ultimo=inicio
                        if inicio-conectada_desde>=max(8,cfg['cooldown_seconds']):fallo_notificado=False
                        boxes=detector.track(frame,persist=True,tracker='bytetrack.yaml',classes=[0],
                            conf=cfg['presence_confidence'],device='cpu',imgsz=cfg['presence_image_size'],max_det=20,verbose=False)[0].boxes
                        detecciones=[]
                        if boxes is not None and boxes.id is not None:
                            for box,i,score in zip(boxes.xyxy.cpu().tolist(),boxes.id.int().cpu().tolist(),boxes.conf.cpu().tolist()):
                                detecciones.append(dict(track_id=int(i),bbox=box,confianza=float(score)))
                        facial.actualizar(frame,detecciones,inicio)
                        self.registro.actualizar(detecciones,inicio,frame)
                        if self.estado!='ONLINE':
                            state_manager.update('CAMARA_2','ONLINE','Cámara de presencia entregando vídeo.',activity='STREAMING',details={'name':cfg['camera_name_employees']})
                            emitir('CAMARA_2_CONECTADA','SISTEMA','presencia_empleados','Cámara de presencia conectada',data={'camera_id':2,'notificar':False})
                            with self.lock:self.estado='ONLINE';self.detalle='Presencia en vivo.'
                        imagen=frame.copy()
                        for t in self.registro.presentes():
                            x1,y1,x2,y2=map(int,t['bbox']);color=(80,180,80) if t.get('id_empleado') else (0,180,230)
                            cv2.rectangle(imagen,(x1,y1),(x2,y2),color,2)
                            label=(t.get('nombre') or t['estado_identidad'])+' · T'+str(t['track_id'])
                            cv2.putText(imagen,label,(max(0,x1),max(18,y1-8)),cv2.FONT_HERSHEY_SIMPLEX,.45,color,1)
                        marcas.append(time.monotonic())
                        fps=(len(marcas)-1)/max(.001,marcas[-1]-marcas[0]) if len(marcas)>1 else 0.
                        with self.lock:self.frame=imagen;self.fps=fps
                        self.detener.wait(max(0,1/cfg['presence_fps_limit']-(time.monotonic()-inicio)))
                except Exception as error:
                    if self.detener.is_set():break
                    with self.lock:self.estado='OFFLINE';self.detalle='Cámara sin conexión. Reconectando…';self.frame=None;self.fps=0
                    self.registro.invalidar()
                    state_manager.update('CAMARA_2','OFFLINE',self.detalle,error='CAMERA_2_READ_FAILED',activity='IDLE')
                    if not fallo_notificado:
                        audit.record('VIGILANCIA','ERROR_CAMARA','FAILED',error=error,data={'camera_id':2})
                        emitir('CAMARA_2_DESCONECTADA','SISTEMA','presencia_empleados','Cámara de presencia desconectada',
                            'No se puede comprobar quién está presente. La cámara de intrusión continúa independiente.',severity='MEDIA',
                            data={'camera_id':2,'camara':cfg['camera_name_employees'],'notificar':cfg['presence_notify_errors']})
                        fallo_notificado=True
                    # Descartar también el consenso facial; IDs pueden reutilizarse tras caída.
                    facial.reiniciar_tracks()
                finally:
                    if captura:captura.cerrar()
                self.detener.wait(3)
        except Exception as error:
            audit.record('VIGILANCIA','ERROR_CAMARA','FAILED',error=error,data={'camera_id':2})
            with self.lock:self.estado='Error';self.detalle=str(error) if isinstance(error,ValueError) else 'No se pudo iniciar presencia; revise cámara y dependencias.'
            state_manager.update('CAMARA_2','ERROR',self.detalle,error='CAMERA_2_START_FAILED',activity='IDLE')
            emitir('CAMARA_2_DESCONECTADA','SISTEMA','presencia_empleados','No se pudo iniciar presencia',self.detalle,severity='MEDIA',
                data={'camera_id':2,'notificar':cfg['presence_notify_errors']})
        finally:
            if facial:facial.cerrar()
            if reservada:liberar(source,self)
            if self.registro:self.registro.invalidar()
            with self.lock:
                self.frame=None;self.fps=0
                if self.detener.is_set():self.estado='Inactivo';self.detalle='Presencia detenida.'
            if self.detener.is_set():state_manager.update('CAMARA_2','OFFLINE','Presencia detenida.',activity='IDLE',expected=True)
            audit.record('VIGILANCIA','CAMARA_2_DETENIDA',data={'camera_id':2})


servicio_presencia=PresenciaEmpleados()


def obtener_personas_presentes():
    return servicio_presencia.registro.presentes() if servicio_presencia.registro and servicio_presencia.obtener_estado()['disponible'] else []


def obtener_empleados_presentes():return [p for p in obtener_personas_presentes() if p.get('id_empleado')]
def obtener_desconocidos_presentes():return [p for p in obtener_personas_presentes() if p['estado_identidad']=='DESCONOCIDO']


def obtener_conteo_actual():
    state=servicio_presencia.obtener_estado()
    counts=servicio_presencia.registro.conteos() if servicio_presencia.registro and state['disponible'] else dict(personas=None,identificados=None,desconocidos=None,pendientes=None)
    return dict(counts,disponible=state['disponible'],estado=state['estado'])


def obtener_historial():
    if servicio_presencia.registro:
        with servicio_presencia.registro.lock:return deepcopy(list(servicio_presencia.registro.historial))
    path=PROJECT_ROOT/'outputs'/'presencia'/'historial.jsonl'
    try:
        with path.open(encoding='utf-8') as f:lines=deque(f,maxlen=200)
        return list(reversed([json.loads(line) for line in lines if line.strip()]))
    except (OSError,ValueError):return []


def estado_camara(camera=2):
    if int(camera)==2:return {k:v for k,v in servicio_presencia.obtener_estado().items() if k!='frame'}
    from surveillance.vigilancia_yolo import servicio_vigilancia
    return {k:v for k,v in servicio_vigilancia.obtener_estado().items() if k!='frame'}


obtener_ocupacion=obtener_conteo_actual
obtener_presentes=obtener_personas_presentes
obtener_desconocidos=obtener_desconocidos_presentes


def resumen_presencia():
    c=obtener_conteo_actual()
    if not c['disponible']:return 'La cámara de presencia no está en línea. No puedo confirmar quién está dentro.'
    text=f"Hay {c['personas']} personas; {c['identificados']} empleados identificados y {c['desconocidos']} desconocidos."
    p=obtener_empleados_presentes()
    if p:text+=' Empleados: '+', '.join(t['nombre'] for t in p)+'.'
    if c['pendientes']:text+=f" {c['pendientes']} personas siguen sin identidad confirmada."
    return text
