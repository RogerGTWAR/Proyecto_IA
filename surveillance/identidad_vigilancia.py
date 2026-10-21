"""Adaptación de frames YOLO al pipeline facial compartido, sin cámara propia."""
from copy import copy, deepcopy
import logging
import queue
import threading
import time

from ai.facial.pipeline_facial import PipelineFacial, SeguimientoFacial
from ai.facial.rostros_empleados import obtener_cache_empleados_por_subject

LOG = logging.getLogger('vigilancia')
INTERVALO_FACIAL = .30
CAMPOS = ('estado_identidad', 'subject', 'id_empleado', 'codigo_empleado',
          'nombre', 'cargo', 'similitud_facial', 'empleado_activo', 'identidad_evaluada')


def procesar_frame_empleados(pipeline, frame, empleados):
    """Mismo punto de entrada para el escáner y para las ROI de vigilancia."""
    return pipeline.procesar(frame, empleados)


def reconocer_empleado_en_frame(frame, roi_persona=None, *, pipeline, empleados):
    h, w = frame.shape[:2]
    x1, y1, x2, y2 = (0, 0, w, h) if roi_persona is None else roi_persona
    x1, y1 = max(0, int(x1)), max(0, int(y1))
    x2, y2 = min(w, int(x2)), min(h, int(y2))
    base = dict(reconocido=False, estado_identidad='ROSTRO_NO_VISIBLE',
                identidad_evaluada=False, subject=None, id_empleado=None,
                codigo_empleado=None, nombre=None, cargo=None, similitud_facial=None,
                empleado_activo=None)
    if x2 <= x1 or y2 <= y1:
        return base
    # Identificación biométrica de inactivos, nunca autorización. Se conserva
    # la política, el margen y el consenso; el estado SQL se aplica al resultado.
    comparables = {s: dict(e, empleado_activo=True) for s, e in empleados.items()}
    resultados = procesar_frame_empleados(pipeline, frame[y1:y2, x1:x2], comparables)
    if len(resultados) != 1:
        return dict(base, motivo='Varios rostros en la persona' if resultados else 'Rostro no visible')
    r = resultados[0]
    caja = r.get('caja')
    if caja is not None:
        base['caja_rostro'] = [int(caja[0]+x1), int(caja[1]+y1), int(caja[2]), int(caja[3])]
    estado = r.get('estado')
    if estado not in ('RECONOCIDO', 'DESCONOCIDO', 'VERIFICANDO'):
        return dict(base, motivo=estado or 'Rostro insuficiente')
    # VERIFICANDO también puede significar calidad insuficiente; no se declara
    # desconocida una cara que no superó los controles del motor existente.
    if r.get('calidad_estado') not in (None, 'CALIDAD_OK', 'CALIDAD_ACEPTABLE'):
        return dict(base, motivo=r['calidad_estado'])
    base.update(identidad_evaluada=True, similitud_facial=r.get('similitud'),
                estado_identidad='NO_RECONOCIDO' if estado == 'DESCONOCIDO' else 'VERIFICANDO_IDENTIDAD')
    subject = r.get('etiqueta')
    e = empleados.get(subject)
    if r.get('reconocido') and e and e.get('id_empleado') == r.get('id_empleado'):
        activo = bool(e.get('empleado_activo'))
        base.update(reconocido=True, subject=subject,
                    estado_identidad='EMPLEADO_RECONOCIDO' if activo else 'EMPLEADO_INACTIVO',
                    empleado_activo=activo, **{k: e.get(k) for k in
                        ('id_empleado', 'codigo_empleado', 'nombre', 'cargo')})
    return base


def texto_identidad(e):
    estado = e.get('estado_identidad')
    if estado == 'EMPLEADO_RECONOCIDO': return e.get('nombre') or 'Empleado reconocido'
    if estado == 'EMPLEADO_INACTIVO': return (e.get('nombre') or 'Empleado') + ' (inactivo)'
    if estado == 'NO_RECONOCIDO': return 'NO RECONOCIDA'
    if estado in ('DETECTADO', 'BUSCANDO_ROSTRO', 'VERIFICANDO_IDENTIDAD'): return 'Verificando identidad…'
    return 'No disponible'


class IdentidadPorTrack:
    """Un worker, una cola de último lote, consenso aislado por track YOLO."""
    def __init__(self, ttl=2, pipeline_factory=PipelineFacial,
                 cache_factory=obtener_cache_empleados_por_subject, intervalo=INTERVALO_FACIAL,
                 revalidar=None):
        self.ttl=ttl; self.pipeline_factory=pipeline_factory; self.cache_factory=cache_factory
        self.intervalo=intervalo;self.revalidar=revalidar
        self.lock=threading.RLock(); self.cola=queue.Queue(1); self.detener=threading.Event()
        self.tracks={}; self.secuencia=0; self.detalle='Cargando SFace…';self.disponible=None;self.ultimo_lote=0
        self.hilo=threading.Thread(target=self._trabajar,daemon=True,name='vigilancia-sface')
        self.hilo.start()

    def actualizar(self, frame, detecciones, ahora):
        trabajos=[]
        with self.lock:
            self.tracks={i:t for i,t in self.tracks.items() if ahora-t['visto']<=self.ttl}
            for d in detecciones:
                i=d['track_id']
                if i not in self.tracks:
                    self.secuencia+=1
                    self.tracks[i]=dict(generacion=self.secuencia,visto=ahora,pedido=-float('inf'),
                        resultado=dict(estado_identidad='BUSCANDO_ROSTRO',identidad_evaluada=False))
                t=self.tracks[i]
                if self.revalidar is not None and ahora-t['visto']>max(.5,self.intervalo*2):
                    t['pedido']=-float('inf')
                t['visto']=ahora
                if self.disponible is False:
                    t['resultado']=dict(estado_identidad='IDENTIDAD_NO_DISPONIBLE',identidad_evaluada=False)
                d.update(deepcopy(t['resultado']),track_generacion=t['generacion'])
            # Prioridad a quien lleva más tiempo esperando; no más de dos ROI
            # por lote. Una cola ocupada se descarta sin bloquear YOLO.
            candidatos=sorted(detecciones,key=lambda d:self.tracks[d['track_id']]['pedido'])
            if self.cola.empty():
                for d in candidatos:
                    t=self.tracks[d['track_id']];x1,y1,x2,y2=d['bbox']
                    espera=self.revalidar if t['resultado'].get('reconocido') else self.intervalo
                    if espera is None or ahora-t['pedido']<espera:continue
                    if min(x2-x1,y2-y1)<48:
                        t['resultado']=dict(estado_identidad='ROSTRO_NO_VISIBLE',identidad_evaluada=False)
                        d.update(t['resultado']);continue
                    # Una ROI que contiene a varias personas no aporta identidad
                    # inequívoca. No heredar la cara del vecino durante cruces.
                    if any(o is not d and _solapadas(d['bbox'],o['bbox']) for o in detecciones):
                        # Borrar consenso previo: una cara de otro track no puede
                        # completar votos acumulados antes del cruce.
                        if not t.get('ambiguo'):
                            self.secuencia+=1;t['generacion']=self.secuencia
                        t['ambiguo']=True
                        t['resultado']=dict(estado_identidad='IDENTIDAD_NO_DISPONIBLE',identidad_evaluada=False)
                        d.update(t['resultado'],track_generacion=t['generacion']);continue
                    t['ambiguo']=False
                    t['pedido']=ahora
                    trabajos.append((d['track_id'],t['generacion'],list(d['bbox'])))
                    if len(trabajos)==2:break
                if trabajos or ahora-self.ultimo_lote>=INTERVALO_FACIAL:
                    try:
                        self.cola.put_nowait((frame.copy() if trabajos else None,trabajos,ahora))
                        self.ultimo_lote=ahora
                    except queue.Full:pass
        return detecciones

    def cerrar(self):
        self.detener.set()
        if self.hilo is not threading.current_thread():self.hilo.join(timeout=.5)

    def reiniciar_tracks(self):
        """Descarta evidencia al cambiar el stream sin crear otro worker."""
        with self.lock:
            self.tracks.clear();self.secuencia+=1

    def _trabajar(self):
        pipelines={}; cache={}; proximo=0
        try:
            base=self.pipeline_factory()
            if not len(base.galeria.vectores) or base.politica is None:
                raise ValueError('Base SFace vacía o sin calibración vigente.')
            self.detalle='SFace activo';self.disponible=True
            from core.eventos_servicios import informar_estado_componente
            informar_estado_componente('SFace',True,'Motor facial disponible.')
        except Exception:
            self.detalle='SFace no disponible; la vigilancia y las alertas continúan.';self.disponible=False
            LOG.warning('[VIGILANCIA] SFace no disponible; se conserva la detección de intrusiones.')
            from core.eventos_servicios import informar_estado_componente
            informar_estado_componente('SFace',False,'No se pudo iniciar SFace o falta una galería con calibración vigente; YOLO continúa sin atribuir identidades.')
            return
        while not self.detener.is_set():
            try:frame,trabajos,tomado=self.cola.get(timeout=.1)
            except queue.Empty:continue
            try:
                ahora=time.monotonic()
                if ahora>=proximo:
                    try:cache=self.cache_factory()
                    except Exception:cache={}
                    proximo=ahora+5
                    with self.lock:
                        for t in self.tracks.values():
                            r=t['resultado'];e=cache.get(r.get('subject'))
                            if r.get('reconocido'):
                                if not e or e.get('id_empleado')!=r.get('id_empleado'):
                                    t['resultado']=dict(estado_identidad='IDENTIDAD_NO_DISPONIBLE',identidad_evaluada=False)
                                    pipelines.pop(t['generacion'],None)
                                else:
                                    r.update({k:e.get(k) for k in ('nombre','codigo_empleado','cargo')})
                                    r.update(empleado_activo=bool(e['empleado_activo']),estado_identidad=
                                        'EMPLEADO_RECONOCIDO' if e['empleado_activo'] else 'EMPLEADO_INACTIVO')
                for i,g,roi in trabajos:
                    if self.detener.is_set():break
                    with self.lock:
                        t=self.tracks.get(i)
                        if not t or t['generacion']!=g or (t['resultado'].get('reconocido') and self.revalidar is None):continue
                    if time.monotonic()-tomado>self.ttl:continue
                    if g not in pipelines:
                        p=copy(base);p.tracker=SeguimientoFacial(base.cfg)
                        p.frames=0;p.ultima_deteccion=-float('inf');pipelines[g]=p
                    r=reconocer_empleado_en_frame(frame,roi,pipeline=pipelines[g],empleados=cache)
                    with self.lock:
                        t=self.tracks.get(i)
                        if t and t['generacion']==g and time.monotonic()-tomado<=self.ttl:
                            previo=t['resultado'].get('estado_identidad')
                            t['evaluaciones']=t.get('evaluaciones',0)+1
                            t['resultado']=dict(r,face_sample=t['evaluaciones'])
                            if previo!=r['estado_identidad']:
                                LOG.info('[VIGILANCIA] track=%s employee=%s face_similarity=%s identity=%s',
                                         i,r.get('codigo_empleado'),r.get('similitud_facial'),r['estado_identidad'])
                with self.lock:vigentes={t['generacion'] for t in self.tracks.values()}
                pipelines={g:p for g,p in pipelines.items() if g in vigentes}
            except Exception:
                LOG.warning('[VIGILANCIA] Evaluación facial no disponible para el lote actual.')
                with self.lock:
                    for i,g,_ in trabajos:
                        t=self.tracks.get(i)
                        if t and t['generacion']==g and not t['resultado'].get('reconocido'):
                            t['resultado']=dict(estado_identidad='IDENTIDAD_NO_DISPONIBLE',identidad_evaluada=False)
            finally:self.cola.task_done()


def _solapadas(a,b):
    inter=max(0,min(a[2],b[2])-max(a[0],b[0]))*max(0,min(a[3],b[3])-max(a[1],b[1]))
    menor=min((a[2]-a[0])*(a[3]-a[1]),(b[2]-b[0])*(b[3]-b[1]))
    return inter/max(1,menor)>.35
