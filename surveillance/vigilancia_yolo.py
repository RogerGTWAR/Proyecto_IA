"""Personas, tracking, entrada a ROI y evidencia; independiente de los motores faciales."""
from core.paths import PROJECT_ROOT
import json
import logging
import math
import os
import queue
import threading
import time
import uuid
from collections import deque
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path

import cv2
import numpy as np

BASE = PROJECT_ROOT
SALIDA = BASE / 'outputs' / 'intrusiones'
HORA_LOCAL = timezone(timedelta(hours=-6))
LOG = logging.getLogger('vigilancia')


def datos_identidad(d):
    from surveillance.identidad_vigilancia import CAMPOS
    datos={k:d.get(k) for k in CAMPOS}
    datos['estado_identidad']=d.get('estado_identidad') or 'IDENTIDAD_NO_DISPONIBLE'
    datos['identidad_evaluada']=bool(d.get('identidad_evaluada'))
    datos['identidad']={k:datos[k] for k in CAMPOS} if d.get('reconocido') else None
    return datos


def validar_poligono(puntos):
    if not isinstance(puntos, list) or not 3 <= len(puntos) <= 20:
        raise ValueError('La zona necesita entre 3 y 20 vértices.')
    for p in puntos:
        if not isinstance(p, (list, tuple)) or len(p) != 2 or any(
                type(n) not in (int, float) or not math.isfinite(n) or not 0 <= n <= 1 for n in p):
            raise ValueError('Los vértices de la zona deben estar normalizados entre 0 y 1.')
    if len(set(tuple(p) for p in puntos)) != len(puntos):
        raise ValueError('La zona contiene vértices repetidos.')
    def orientacion(a, b, c): return (b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0])
    def sobre(a,b,c): return min(a[0],b[0])<=c[0]<=max(a[0],b[0]) and min(a[1],b[1])<=c[1]<=max(a[1],b[1])
    def cruza(a,b,c,d):
        o=[orientacion(a,b,c),orientacion(a,b,d),orientacion(c,d,a),orientacion(c,d,b)]
        return (o[0]*o[1]<0 and o[2]*o[3]<0) or any(abs(x)<1e-10 and sobre(*v) for x,v in zip(o,[(a,b,c),(a,b,d),(c,d,a),(c,d,b)]))
    for i in range(len(puntos)):
        for j in range(i+1,len(puntos)):
            if j==i+1 or (i==0 and j==len(puntos)-1):continue
            if cruza(puntos[i],puntos[(i+1)%len(puntos)],puntos[j],puntos[(j+1)%len(puntos)]):
                raise ValueError('Los lados de la zona no pueden cruzarse.')
    if abs(cv2.contourArea(np.asarray(puntos,np.float32))) < .0001:
        raise ValueError('La zona no tiene un área suficiente.')
    return puntos


def validar_configuracion(c):
    for k in ('intrusion_enabled','telegram_enabled'):
        if type(c[k]) is not bool:raise ValueError('Vigilancia: se requiere un valor booleano en '+k)
    for k,a,b in [('confidence_threshold',.1,.95),('cooldown_seconds',1,600),
                  ('clip_before_seconds',0,10),('clip_after_seconds',0,15),('track_ttl_seconds',.2,10)]:
        if type(c[k]) not in (int,float) or not math.isfinite(c[k]) or not a<=c[k]<=b:
            raise ValueError(f'Vigilancia: {k} debe estar entre {a} y {b}.')
    for k,a,b in [('clip_fps',2,12),('confirm_frames',2,15),('image_size',320,960)]:
        if type(c[k]) is not int or not a<=c[k]<=b:raise ValueError('Vigilancia: valor inválido en '+k)
    if c['image_size']%32:raise ValueError('El tamaño YOLO debe ser múltiplo de 32.')
    for k in ('camera_name','zone_name','yolo_model'):
        if not isinstance(c[k],str) or not c[k].strip() or len(c[k])>160 or any(ord(x)<32 for x in c[k]):
            raise ValueError('Vigilancia: texto inválido en '+k)
    if Path(c['yolo_model']).suffix.lower()!='.pt':raise ValueError('Vigilancia: seleccione un modelo YOLO .pt local.')
    fuente=c['camera_source']
    if type(fuente) is int:
        if fuente<0:raise ValueError('Vigilancia: índice de cámara inválido.')
    elif isinstance(fuente,str):
        from urllib.parse import urlsplit
        u=urlsplit(fuente)
        if u.scheme not in ('rtsp','http','https') or u.username or u.password or u.query:
            raise ValueError('Vigilancia: use índice USB o URL sin credenciales. Para fuentes privadas use VIGILANCIA_VIDEO_SOURCE.')
    else:raise ValueError('Vigilancia: fuente de vídeo inválida.')
    if c['zone_polygon']:validar_poligono(c['zone_polygon'])
    elif not isinstance(c['zone_polygon'],list):raise ValueError('Vigilancia: polígono inválido.')
    return c


class ControlIntrusion:
    """Debounce por track: una presencia inicial dentro no demuestra una entrada."""
    def __init__(self, poligono, confirmacion=3, cooldown=45, ttl=2):
        validar_poligono(poligono)
        self.poligono=np.asarray(poligono,np.float32)
        self.confirmacion=confirmacion;self.cooldown=cooldown;self.ttl=ttl;self.tracks={}

    def actualizar(self, detecciones, forma, ahora):
        alto,ancho=forma[:2];eventos=[]
        for d in detecciones:
            identificador=int(d['track_id']);x1,y1,x2,y2=d['bbox']
            dentro=cv2.pointPolygonTest(self.poligono,((x1+x2)/2/ancho,y2/alto),False)>=0
            t=self.tracks.setdefault(identificador,dict(estado='FUERA',estable=None,candidato=None,
                cuenta=0,visto_fuera=False,ultima_alerta=-math.inf,ultimo=ahora))
            if ahora-t['ultimo']>self.ttl:
                t.update(estable=None,candidato=None,cuenta=0,visto_fuera=False)
            t['ultimo']=ahora
            if dentro!=t['estable']:
                t['cuenta']=t['cuenta']+1 if t['candidato']==dentro else 1
                t['candidato']=dentro;t['estado']='ENTRANDO' if dentro else 'SALIENDO'
                if t['cuenta']>=self.confirmacion:
                    anterior=t['estable'];t['estable']=dentro;t['cuenta']=0
                    t['estado']='DENTRO' if dentro else 'FUERA'
                    if not dentro:t['visto_fuera']=True
                    elif anterior is False and t['visto_fuera'] and ahora-t['ultima_alerta']>=self.cooldown:
                        t['ultima_alerta']=ahora;eventos.append(dict(d))
            else:
                t['cuenta']=0;t['candidato']=dentro;t['estado']='DENTRO' if dentro else 'FUERA'
            d['estado']=t['estado']
        self.tracks={i:t for i,t in self.tracks.items() if ahora-t['ultimo']<=max(self.cooldown,self.ttl)}
        return eventos


def _guardar_json(ruta, datos):
    temporal=ruta.with_suffix('.tmp')
    temporal.write_text(json.dumps(datos,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    os.replace(temporal,ruta)


def listar_eventos(fecha=None, limite=100):
    if fecha is not None:
        if datetime.strptime(fecha,'%Y-%m-%d').strftime('%Y-%m-%d')!=fecha:raise ValueError('Fecha inválida.')
    carpetas=[SALIDA/fecha] if fecha else sorted(SALIDA.glob('*'),reverse=True)
    filas=[]
    for carpeta in carpetas:
        for ruta in sorted(carpeta.glob('*.json'),reverse=True):
            try:
                evento=json.loads(ruta.read_text(encoding='utf-8'));evento['metadata']=str(ruta.resolve());filas.append(evento)
            except (OSError,ValueError):continue
            if len(filas)>=limite:return filas
    return filas


class EvidenciaIntrusion:
    """Dos colas acotadas: disco y red no frenan la captura ni la inferencia."""
    def __init__(self, cfg, salida=SALIDA, registrar_sql=None, notificar=None):
        self.cfg=cfg;self.salida=Path(salida);self.buffer=deque(maxlen=1+math.ceil(cfg['clip_before_seconds']*cfg['clip_fps']))
        self.activos=[];self.ultimo_frame=-math.inf;self.disco=queue.Queue(32);self.red=queue.Queue(32)
        self.cierre=threading.Event();self.lock=threading.RLock();self.recientes=deque(maxlen=100)
        self.registrar_sql=registrar_sql;self.notificar=notificar
        self.identidades_notificadas=set()
        self.hilos=[threading.Thread(target=self._consumir_disco,daemon=True,name='intrusion-disco'),
                    threading.Thread(target=self._consumir_red,daemon=True,name='intrusion-red')]
        for h in self.hilos:h.start()

    def _actualizar(self,e,**cambios):
        with self.lock:
            e.update(cambios);_guardar_json(Path(e['metadata']),e)

    def _encolar(self,cola,datos,e):
        try:cola.put_nowait(datos);return True
        except queue.Full:
            self._actualizar(e,error='Cola de evidencia saturada; revise el registro local.',pendiente=True)
            return False

    def frame(self,frame,ahora):
        if ahora-self.ultimo_frame<1/self.cfg['clip_fps']:return
        self.ultimo_frame=ahora
        alto,ancho=frame.shape[:2];ancho_nuevo=min(640,ancho)//2*2
        pequeno=cv2.resize(frame,(ancho_nuevo,max(2,int(alto*ancho_nuevo/ancho)//2*2)))
        self.buffer.append((ahora,pequeno))
        while self.buffer and ahora-self.buffer[0][0]>self.cfg['clip_before_seconds']:
            self.buffer.popleft()
        for evento in list(self.activos):
            evento['frames'].append((ahora,pequeno))
            if ahora>=evento['fin']:self._finalizar_clip(evento,False)

    def registrar(self,deteccion,frame,ahora):
        from core.audit_service import AuditContext, use_context, capture_context, audit
        from core.audit_service import operation
        with use_context(AuditContext(origin='automatic')):
            with operation('VIGILANCIA','INCIDENT_CONFIRMED',data={'track_id':deteccion['track_id']}):
                trace=capture_context()
        fecha=datetime.now(HORA_LOCAL);identificador=uuid.uuid4().hex
        carpeta=self.salida/fecha.strftime('%Y-%m-%d');carpeta.mkdir(parents=True,exist_ok=True)
        base=carpeta/(fecha.strftime('%H%M%S_%f')+'_'+identificador)
        evento=dict(_audit_context=trace,id_evento=identificador,fecha_hora=fecha.isoformat(),camara=self.cfg['camera_name'],
            zona=self.cfg['zone_name'],track_id=int(deteccion['track_id']),confianza=float(deteccion['confianza']),
            bbox=[float(x) for x in deteccion['bbox']],identidad=None,identidad_evaluada=False,
            metadata=str(base.with_suffix('.json')),captura=None,recorte=None,clip=None,
            sql_estado='pendiente',telegram_foto='pendiente',telegram_video='sin clip',pendiente=False)
        evento.update(tipo_evento=deteccion.get('tipo_evento','INTRUSIÓN'),categoria='Vigilancia',modulo='Vigilancia',
            fuente_camara='índice '+str(self.cfg['camera_source']) if isinstance(self.cfg['camera_source'],int) else 'fuente IP/RTSP configurada',
            zone_polygon=self.cfg['zone_polygon'],nivel='INFO' if deteccion.get('tipo_evento')=='EMPLEADO RECONOCIDO' else 'ALTA')
        if deteccion.get('estado'):evento['estado_zona']=deteccion['estado']
        evento.update(datos_identidad(deteccion),track_generacion=deteccion.get('track_generacion'))
        LOG.info('[VIGILANCIA] track=%s yolo=%.2f zone=%s face_status=%s',
                 evento['track_id'],evento['confianza'],evento['zona'],evento['estado_identidad'])
        with self.lock:self.recientes.appendleft(evento)
        self._actualizar(evento)
        if not self._encolar(self.disco,('foto',evento,frame.copy()),evento):
            self._encolar(self.red,('foto',evento),evento)
        if evento['tipo_evento']=='INTRUSIÓN' and self.cfg['clip_before_seconds']+self.cfg['clip_after_seconds']>0:
            if len(self.activos)<4:
                clip=dict(evento=evento,frames=list(self.buffer),inicio=ahora,fin=ahora+self.cfg['clip_after_seconds'])
                self.activos.append(clip)
                if self.cfg['clip_after_seconds']==0:self._finalizar_clip(clip,False)
            else:self._actualizar(evento,clip_estado='Sin clip: límite de cuatro grabaciones simultáneas.')
        return evento

    def registrar_identidades(self,detecciones,frame,ahora):
        eventos=[]
        for d in detecciones:
            estado=d.get('estado_identidad')
            if not d.get('identidad_evaluada') or estado not in ('NO_RECONOCIDO','EMPLEADO_RECONOCIDO'):continue
            if estado=='EMPLEADO_RECONOCIDO' and not d.get('reconocido'):continue
            clave=(d['track_id'],d.get('track_generacion'),estado,d.get('id_empleado'))
            if clave in self.identidades_notificadas:continue
            tipo='DESCONOCIDO' if estado=='NO_RECONOCIDO' else 'EMPLEADO RECONOCIDO'
            eventos.append(self.registrar(dict(d,tipo_evento=tipo),frame,ahora))
            self.identidades_notificadas.add(clave)
        return eventos

    def actualizar_identidades(self, detecciones):
        """Enriquecer el mismo UUID; una actualización facial nunca envía Telegram."""
        por_track={(d['track_id'],d.get('track_generacion')):d for d in detecciones}
        with self.lock:
            for e in self.recientes:
                d=por_track.get((e['track_id'],e.get('track_generacion')))
                if d is None:continue
                datos=datos_identidad(d)
                if all(e.get(k)==v for k,v in datos.items()):continue
                cambios_sql=any(e.get(k)!=datos.get(k) for k in (
                    'estado_identidad','subject','id_empleado','codigo_empleado','nombre','cargo','empleado_activo'))
                self._actualizar(e,**datos)
                if cambios_sql:self._encolar(self.red,('identidad',e),e)

    def _finalizar_clip(self,clip,parcial):
        self.activos.remove(clip)
        self._encolar(self.disco,('clip',clip['evento'],(clip['frames'],clip['inicio'],parcial)),clip['evento'])

    def cerrar(self):
        for clip in list(self.activos):self._finalizar_clip(clip,True)
        self.cierre.set()

    def _consumir_disco(self):
        while not self.cierre.is_set() or not self.disco.empty():
            try:tipo,e,contenido=self.disco.get(timeout=.2)
            except queue.Empty:continue
            try:
                base=Path(e['metadata']).with_suffix('')
                if tipo=='foto':
                    foto=base.with_suffix('.jpg');recorte=base.with_name(base.name+'_persona').with_suffix('.jpg')
                    from integrations.telegram.telegram_service import generar_snapshot_evento
                    generar_snapshot_evento(contenido,e,foto)
                    alto,ancho=contenido.shape[:2];x1,y1,x2,y2=e['bbox']
                    x1,y1=max(0,int(x1)),max(0,int(y1));x2,y2=min(ancho,int(x2)),min(alto,int(y2))
                    if x2>x1 and y2>y1 and cv2.imwrite(str(recorte),contenido[y1:y2,x1:x2]):
                        self._actualizar(e,captura=str(foto),recorte=str(recorte))
                    else:self._actualizar(e,captura=str(foto),recorte_estado='Recorte no disponible.')
                    from core.audit_service import use_context, audit
                    with use_context(e.get('_audit_context'),origin='automatic'):
                        audit.record('VIGILANCIA','SNAPSHOT_GENERATED',data={'id_evento':e['id_evento'],'path':str(foto)})
                    self._encolar(self.red,('foto',e),e)
                else:
                    frames,inicio,parcial=contenido
                    if len(frames)<2:
                        self._actualizar(e,clip_estado='Sin suficientes fotogramas para guardar un clip.');continue
                    ruta=base.with_suffix('.mp4');h,w=frames[0][1].shape[:2]
                    duracion=frames[-1][0]-frames[0][0]
                    fps=max(.1,(len(frames)-1)/duracion) if duracion>0 else self.cfg['clip_fps']
                    writer=cv2.VideoWriter(str(ruta),cv2.VideoWriter_fourcc(*'mp4v'),fps,(w,h))
                    if not writer.isOpened():raise OSError('El códec MP4 no está disponible.')
                    try:
                        for _,f in frames:writer.write(f)
                    finally:writer.release()
                    self._actualizar(e,clip=str(ruta),clip_estado='Parcial por cierre' if parcial else 'Guardado',
                        clip_antes_real=max(0,inicio-frames[0][0]),clip_despues_real=max(0,frames[-1][0]-inicio),clip_fps_real=fps)
                    self._encolar(self.red,('video',e),e)
                    from core.audit_service import use_context, audit
                    with use_context(e.get('_audit_context'),origin='automatic'):
                        audit.record('VIGILANCIA','CLIP_GENERATED',data={'id_evento':e['id_evento'],'path':str(ruta)})
            except Exception as error:
                from integrations.telegram.telegram_service import _error_seguro,LOG as LOG_TELEGRAM
                from core.audit_service import use_context, audit
                with use_context(e.get('_audit_context'),origin='automatic'):
                    audit.record('VIGILANCIA','EVIDENCE_WRITE','FAILED',error=error,level='ERROR',data={'id_evento':e['id_evento'],'part':tipo})
                detalle=_error_seguro(error)
                LOG_TELEGRAM.error('[SNAPSHOT/CLIP ERROR] evento=%s excepcion=%s',e['id_evento'],detalle)
                self._actualizar(e,error='No se pudo completar la evidencia: '+detalle,pendiente=True)
                if tipo=='foto':self._encolar(self.red,('foto',e),e)
            finally:self.disco.task_done()

    def _consumir_red(self):
        while not self.cierre.is_set() or not self.red.empty() or any(h.is_alive() for h in self.hilos[:1]):
            try:tipo,e=self.red.get(timeout=.2)
            except queue.Empty:continue
            try:
                if self.registrar_sql is None and self.notificar is None:
                    from core.eventos_servicios import publicar_vigilancia
                    with self.lock:instantanea=deepcopy(e)
                    self._actualizar(e,**{'telegram_'+tipo:'Publicado en el bus central.',
                                         'sql_estado':'Gestionado por el suscriptor de alertas'})
                    publicar_vigilancia(instantanea,tipo)
                    continue
                if tipo in ('foto','identidad') and e.get('tipo_evento','INTRUSIÓN')=='INTRUSIÓN':
                    try:
                        if self.registrar_sql is None:
                            from inventory.alertas import registrar_alerta_intrusion
                            registrar=registrar_alerta_intrusion
                        else:registrar=self.registrar_sql
                        with self.lock:instantanea=deepcopy(e)
                        resultado=registrar(instantanea)
                        self._actualizar(e,sql_estado='registrado',id_alerta=resultado['id_alerta'])
                    except Exception:self._actualizar(e,sql_estado='pendiente',sql_detalle='No se pudo registrar en SQL; evidencia local conservada.')
                elif tipo=='foto':
                    self._actualizar(e,sql_estado='Pendiente del registro central de notificaciones')
                if tipo=='identidad':continue
                from core.config_manager import obtener
                categoria='vigilancia' if e.get('tipo_evento','INTRUSIÓN')=='INTRUSIÓN' else 'facial'
                if self.notificar is not None and (not obtener('telegram','habilitado') or not obtener('telegram',categoria)):
                    self._actualizar(e,**{'telegram_'+tipo:'Telegram desactivado.'});continue
                if self.notificar is None:
                    from integrations.telegram.telegram_service import enviar_evento
                    notificar=enviar_evento
                else:notificar=self.notificar
                with self.lock:instantanea=deepcopy(e)
                resultado=notificar(instantanea,instantanea['clip'] if tipo=='video' else instantanea['captura'],video=tipo=='video')
                self._actualizar(e,**{'telegram_'+tipo:resultado['detalle'],'telegram_'+tipo+'_enviado':resultado.get('enviado',False)})
            except Exception as error:
                from integrations.telegram.telegram_service import _error_seguro,LOG as LOG_TELEGRAM
                detalle=_error_seguro(error)
                LOG_TELEGRAM.error('[TELEGRAM ERROR] evento=%s parte=%s excepcion=%s',e['id_evento'],tipo,detalle)
                self._actualizar(e,**{'telegram_'+tipo:'Telegram: '+detalle})
            finally:self.red.task_done()


def cargar_detector(cfg):
    ruta=Path(cfg['yolo_model']);ruta=ruta if ruta.is_absolute() else BASE/ruta
    if not ruta.is_file():raise ValueError('No se encontró el modelo YOLO. Revise la ruta en Vigilancia.')
    directorio=BASE/'outputs'/'config_yolo';directorio.mkdir(parents=True,exist_ok=True)
    os.environ.setdefault('YOLO_CONFIG_DIR',str(directorio))
    os.environ.setdefault('YOLO_AUTOINSTALL','false')
    try:from ultralytics import YOLO
    except ImportError as exc:
        dependencia=getattr(exc,'name',None) or 'Ultralytics o una de sus dependencias'
        raise ValueError(
            f'No se pudo cargar {dependencia}. Abra el sistema con main.py usando el entorno .venv. '
            'Si persiste, ejecute .venv\\Scripts\\python.exe herramientas\\preparar_vigilancia.py --instalar.'
        ) from exc
    modelo=YOLO(str(ruta))
    if modelo.names.get(0)!='person':raise ValueError('El modelo debe tener person como clase 0.')
    return modelo


class Vigilancia:
    def __init__(self):
        self.hilo=None;self.detener=threading.Event();self.lock=threading.Lock()
        self.preview=False;self.facial=None
        self.estado='Inactivo';self.detalle='Vigilancia detenida.';self.frame=None;self.fps=0.0;self.evidencia=None

    def iniciar(self,cfg,preview=False,detector_factory=cargar_detector,captura_factory=None):
        from core.audit_service import operation
        with operation('VIGILANCIA','SURVEILLANCE_START_REQUEST',origin='desktop'):
            return self._iniciar(cfg,preview,detector_factory,captura_factory)

    def _iniciar(self,cfg,preview=False,detector_factory=cargar_detector,captura_factory=None):
        validar_configuracion(cfg)
        if not preview:
            if not cfg['intrusion_enabled']:raise ValueError('La vigilancia está deshabilitada.')
            validar_poligono(cfg['zone_polygon'])
        with self.lock:
            if self.hilo and self.hilo.is_alive():raise ValueError('La cámara de vigilancia ya está en uso.')
            self.detener=threading.Event();self.estado='Iniciando';self.detalle='Abriendo cámara…';self.frame=None;self.fps=0
            self.preview=preview
            self.facial=None
            from core.audit_service import capture_context, run_in_context
            self.hilo=threading.Thread(target=run_in_context,args=(capture_context(),self._ejecutar,deepcopy(cfg),preview,detector_factory,captura_factory),daemon=True,name='vigilancia-yolo')
            self.hilo.start()

    def parar(self):
        from core.audit_service import operation
        with operation('VIGILANCIA','SURVEILLANCE_STOP_REQUEST',origin='desktop'):
            self.detener.set()

    def pendiente_disco(self):
        return bool(self.evidencia and self.evidencia.hilos[0].is_alive())

    def obtener_estado(self):
        with self.lock:
            return dict(estado=self.estado,detalle=self.detalle,fps=self.fps,frame=self.frame,
                        facial=self.facial.detalle if self.facial else 'Sin evaluación facial',
                        preview=self.preview,
                        activo=bool(self.hilo and self.hilo.is_alive()))

    def _ejecutar(self,cfg,preview,detector_factory,captura_factory):
        while not self.detener.is_set():
            self._ejecutar_sesion(cfg,preview,detector_factory,captura_factory)
            if preview or self.estado!='Error' or self.detener.is_set():break
            # El reintento pertenece solo a esta cámara; no detiene presencia.
            worker=getattr(self.facial,'hilo',None)
            while isinstance(worker,threading.Thread) and worker.is_alive() and not self.detener.is_set():
                self.detener.wait(.1)
            self.detener.wait(3)

    def _ejecutar_sesion(self,cfg,preview,detector_factory,captura_factory):
        from ai.facial.reconocimiento_cnn import _bloqueo_camara
        from surveillance.camara_utils import CamaraUltimoFrame
        captura=None;adquirido=False;grabador=None;facial=None;detector=None;reservada=False;fuente=None
        try:
            adquirido=_bloqueo_camara.acquire(blocking=False)
            if not adquirido:raise ValueError('La cámara está ocupada por otra función. Cierre primero esa sesión.')
            detector=None if preview else detector_factory(cfg)
            if not preview:
                from core.system_state import state_manager
                state_manager.track_resource('YOLO',detector,available=True,message='Detector cargado para vigilancia.',
                    details={'model_loaded':True,'model':cfg['yolo_model'],'device':'cpu','confidence':cfg['confidence_threshold']})
            if self.detener.is_set():return
            from surveillance.fuentes_camara import resolver_fuente,reservar
            fuente=resolver_fuente(cfg,1)
            reservar(fuente,self);reservada=True
            captura=(captura_factory(fuente,[1280,720]) if captura_factory else
                     CamaraUltimoFrame(fuente,[1280,720],servicio='CAMARA_1')).iniciar()
            control=None if preview else ControlIntrusion(cfg['zone_polygon'],cfg['confirm_frames'],cfg['cooldown_seconds'],cfg['track_ttl_seconds'])
            grabador=None if preview else EvidenciaIntrusion(cfg)
            if not preview:
                from surveillance.identidad_vigilancia import IdentidadPorTrack
                facial=IdentidadPorTrack(ttl=cfg['track_ttl_seconds'])
                self.facial=facial
            self.evidencia=grabador
            anterior=-1;inicio=time.monotonic();marcas=deque(maxlen=30);ultima_imagen=inicio
            personas_vistas={}
            from core.eventos_servicios import informar_estado_componente
            informar_estado_componente('Cámara',True,'Captura de vigilancia iniciada.')
            from core.system_state import state_manager
            state_manager.update('CAMARA_1','ONLINE','Intrusión en vivo.',activity='STREAMING',details={'name':cfg['camera_name']})
            with self.lock:self.estado='Vista previa' if preview else 'Activo';self.detalle='Cámara abierta.'
            while not self.detener.is_set():
                numero,frame=captura.leer()
                if captura.error:raise RuntimeError('No se pudo leer la cámara. Revise la conexión.')
                if frame is None or numero==anterior:
                    if time.monotonic()-ultima_imagen>8:raise RuntimeError('La cámara no entregó imágenes.')
                    self.detener.wait(.01);continue
                anterior=numero;ultima_imagen=time.monotonic();imagen=frame.copy();detecciones=[]
                if detector is not None:
                    resultados=detector.track(frame,persist=True,tracker='bytetrack.yaml',classes=[0],
                        conf=cfg['confidence_threshold'],device='cpu',imgsz=cfg['image_size'],max_det=20,verbose=False)[0]
                    cajas=resultados.boxes
                    if cajas is not None and cajas.id is not None:
                        for caja,identidad,confianza in zip(cajas.xyxy.cpu().tolist(),cajas.id.int().cpu().tolist(),cajas.conf.cpu().tolist()):
                            detecciones.append(dict(track_id=int(identidad),bbox=caja,confianza=float(confianza)))
                    ahora=time.monotonic();entradas=control.actualizar(detecciones,frame.shape,ahora)
                    from core.event_bus import emitir
                    for d in detecciones:
                        track=d['track_id']
                        if track not in personas_vistas or ahora-personas_vistas[track]>cfg['track_ttl_seconds']:
                            emitir('PERSONA_DETECTADA','VIGILANCIA','vigilancia_yolo','Persona detectada',
                                   'Detección de persona confirmada por YOLO.',
                                   data=dict(d,camara=cfg['camera_name'],zona=cfg['zone_name']))
                        personas_vistas[track]=ahora
                    personas_vistas={k:v for k,v in personas_vistas.items() if ahora-v<=cfg['track_ttl_seconds']}
                    facial.actualizar(frame,detecciones,ahora)
                    # ControlIntrusion devuelve copias previas al enriquecimiento.
                    por_id={d['track_id']:d for d in detecciones}
                    entradas=[por_id[d['track_id']] for d in entradas]
                    grabador.actualizar_identidades(detecciones)
                    poligono=(np.asarray(cfg['zone_polygon'])*[frame.shape[1],frame.shape[0]]).astype(np.int32)
                    capa=imagen.copy();cv2.fillPoly(capa,[poligono],(80,100,220));cv2.addWeighted(capa,.22,imagen,.78,0,imagen)
                    cv2.polylines(imagen,[poligono],True,(80,100,220),2)
                    for d in detecciones:
                        x1,y1,x2,y2=map(int,d['bbox']);color=(40,60,230) if d['estado'] in ('ENTRANDO','DENTRO') else (60,200,80)
                        cv2.rectangle(imagen,(x1,y1),(x2,y2),color,2)
                        from surveillance.identidad_vigilancia import texto_identidad
                        lineas=[f"Track {d['track_id']} - YOLO {d['confianza']:.2f}",texto_identidad(d)]
                        if d.get('reconocido'):
                            lineas.append(f"{d.get('codigo_empleado') or ''} - Face {d['similitud_facial']:.2f}")
                        elif d.get('estado_identidad')=='ROSTRO_NO_VISIBLE':lineas[1]='Rostro no visible'
                        for n,linea in enumerate(lineas):
                            cv2.putText(imagen,linea,(max(0,x1),max(20,y1-8)+n*20),cv2.FONT_HERSHEY_SIMPLEX,.5,color,1)
                    grabador.frame(imagen,ahora)
                    for d in entradas:grabador.registrar(d,imagen,ahora)
                    # Una transición facial confirmada es un evento propio, nunca una decisión CNN.
                    grabador.registrar_identidades(detecciones,imagen,ahora)
                marcas.append(time.monotonic())
                fps=(len(marcas)-1)/max(.001,marcas[-1]-marcas[0]) if len(marcas)>1 else 0.0
                with self.lock:self.frame=imagen;self.fps=fps
            with self.lock:self.estado='Inactivo';self.detalle='Vigilancia detenida; evidencias pendientes se completan en segundo plano.'
        except Exception as exc:
            from core.audit_service import audit
            audit.record('VIGILANCIA','SURVEILLANCE_WORKER','FAILED',error=exc,level='ERROR')
            from core.system_state import state_manager
            state_manager.update('CAMARA_1','ERROR','No se pudo mantener la captura de intrusión.',error='CAMERA_1_FAILED',activity='IDLE')
            with self.lock:
                self.estado='Error';self.detalle=str(exc) if isinstance(exc,ValueError) else 'Error en vigilancia. Revise cámara, modelo y dependencias.'
            if adquirido and not self.detener.is_set() and not preview:
                from core.system_state import state_manager
                if detector is None:
                    state_manager.update('YOLO','ERROR','No se pudo cargar YOLO.',error='YOLO_LOAD_FAILED')
                else:state_manager.update('CAMARA','ERROR','La captura de vigilancia falló.',activity='IDLE',error='CAMERA_CAPTURE_FAILED')
        finally:
            if captura is not None:
                captura.cerrar()
                from core.system_state import state_manager
                if state_manager.get('CAMARA').status!='ERROR':
                    state_manager.update('CAMARA','OFFLINE','Captura de vigilancia cerrada.',activity='IDLE',expected=True)
            if reservada:
                from surveillance.fuentes_camara import liberar
                liberar(fuente,self)
            if captura is not None and state_manager.get('CAMARA_1').status!='ERROR':
                state_manager.update('CAMARA_1','OFFLINE','Intrusión detenida.',activity='IDLE',expected=True)
            if grabador is not None:grabador.cerrar()
            if facial is not None:facial.cerrar()
            if adquirido:_bloqueo_camara.release()
            if self.detener.is_set():
                with self.lock:self.estado='Inactivo';self.detalle='Vigilancia detenida.'


servicio_vigilancia=Vigilancia()
