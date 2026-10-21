"""YuNet + SFace local, calidad original, galería múltiple y evidencia por track.
No autoriza identidades hasta cargar una calibración vinculada a esta galería.
"""
from core.paths import PROJECT_ROOT
import hashlib
import json
import math
import os
import time
from collections import Counter, deque
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np

BASE_DIR = PROJECT_ROOT
CONFIG = BASE_DIR / "reconocimiento_facial_config.json"
DIRECTORIO = BASE_DIR / "modelos" / "facial_embeddings"
GALERIA = DIRECTORIO / "galeria.npz"
CALIBRACION = DIRECTORIO / "calibracion.json"
MODELOS = {
    "detector": ("face_detection_yunet_2023mar.onnx", "8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4"),
    "reconocedor": ("face_recognition_sface_2021dec.onnx", "0ba9fbfa01b5270c96627c4ef784da859931e02f04419c829e83484087c34e79"),
}
VERSION_PIPELINE = "yunet-sface-bgr-align-v1-top3"


def cargar_configuracion():
    from core.config_manager import cargar_configuracion as configuracion_central
    datos = configuracion_central()['facial']
    fuente = os.getenv("INVENTARIO_VIDEO_SOURCE")
    if fuente is not None:
        datos["fuente_video"] = int(fuente) if fuente.isdigit() else fuente
    motor = os.getenv("INVENTARIO_FACE_ENGINE")
    if motor:
        datos["motor"] = motor
    if datos["motor"] not in {"embeddings", "cnn", "comparacion"}:
        raise ValueError("Motor facial inválido: use embeddings o cnn.")
    if datos["min_rostro"] < 32 or datos["detectar_cada"] < 1 or datos["tile"] < 128:
        raise ValueError("Configuración facial inválida.")
    return datos


def sha256(ruta):
    h = hashlib.sha256()
    with Path(ruta).open("rb") as archivo:
        for bloque in iter(lambda: archivo.read(1024 * 1024), b""):
            h.update(bloque)
    return h.hexdigest()


def firma_configuracion(cfg):
    claves = ("blur_min", "iluminacion_min", "iluminacion_max", "roll_max", "yaw_max",
              "resolucion", "fuente_video", "roi", "lado_deteccion", "tile")
    datos = {k: cfg[k] for k in claves}
    datos['blur_lado']=cfg.get('blur_lado',160)
    datos['blur_rechazo']=cfg.get('blur_rechazo',cfg['blur_min'])
    datos["pipeline"] = VERSION_PIPELINE
    return hashlib.sha256(json.dumps(datos, sort_keys=True).encode()).hexdigest()


def escribir_json_atomico(ruta, datos):
    ruta = Path(ruta)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    temporal = ruta.with_suffix(ruta.suffix + ".tmp")
    temporal.write_text(json.dumps(datos, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    temporal.replace(ruta)


def normalizar(vector):
    vector = np.asarray(vector, np.float32).reshape(-1)
    norma = np.linalg.norm(vector)
    if not np.isfinite(vector).all() or norma < 1e-8:
        raise ValueError("Embedding inválido.")
    return vector / norma


def iou(a, b):
    x1, y1 = max(a[0], b[0]), max(a[1], b[1])
    x2, y2 = min(a[0]+a[2], b[0]+b[2]), min(a[1]+a[3], b[1]+b[3])
    inter = max(0, x2-x1)*max(0, y2-y1)
    return inter / max(a[2]*a[3]+b[2]*b[3]-inter, 1)


def distancia_relativa(ancho, alto):
    # Categoría de tamaño aparente, nunca estimación física en metros.
    lado = min(ancho, alto)
    return "LEJOS" if lado < 120 else "MEDIA" if lado < 240 else "CERCA"


def medir_nitidez(gris,lado=160):
    escala=min(1.0,lado/max(gris.shape[:2]))
    referencia=cv2.resize(gris,(max(1,round(gris.shape[1]*escala)),max(1,round(gris.shape[0]*escala))),interpolation=cv2.INTER_AREA) if escala<1 else gris
    return float(cv2.Laplacian(referencia,cv2.CV_64F).var())


def evaluar_calidad(frame, cara, cfg, minimo=None):
    cara=np.asarray(cara)
    if cara.shape != (15,) or not np.isfinite(cara).all():
        return {"ancho_rostro":0,"alto_rostro":0,"distancia":"-","blur":0,"iluminacion":0,
                "roll":0,"yaw":1,"visible":0,"calidad":0,"estado":"BAJA_CALIDAD","valida":False}
    x, y, w, h = map(float, cara[:4])
    alto, ancho = frame.shape[:2]
    x1, y1, x2, y2 = max(0, int(x)), max(0, int(y)), min(ancho, int(x+w)), min(alto, int(y+h))
    region = frame[y1:y2, x1:x2]
    datos = {"ancho_rostro": w, "alto_rostro": h,
             "distancia": distancia_relativa(w, h), "blur": 0.0, "iluminacion": 0.0,
             "roll": 0.0, "yaw": 1.0, "visible": 0.0, "calidad": 0.0}
    if region.size == 0 or w <= 0 or h <= 0 or not np.isfinite(cara).all():
        return {**datos, "estado": "BAJA_CALIDAD", "valida": False}
    gris = cv2.cvtColor(region, cv2.COLOR_BGR2GRAY)
    datos["visible"] = min(1.0,float(region.shape[0]*region.shape[1]/(w*h)))
    # Comparar nitidez a escala constante; conservar también la métrica nativa.
    datos['blur_original']=float(cv2.Laplacian(gris,cv2.CV_64F).var())
    datos["blur"] = medir_nitidez(gris,cfg.get('blur_lado',160))
    datos["iluminacion"] = float(gris.mean())
    ojos = np.asarray(cara[4:8], np.float32).reshape(2, 2)
    izquierda, derecha = ojos[np.argsort(ojos[:, 0])]
    vector = derecha-izquierda
    separacion = float(np.linalg.norm(vector))
    datos["roll"] = abs(math.degrees(math.atan2(float(vector[1]), float(vector[0]))))
    nariz = np.asarray(cara[8:10])
    datos["yaw"] = abs(float(nariz[0]-(izquierda[0]+derecha[0])/2)) / max(separacion, 1)
    landmarks = np.asarray(cara[4:14]).reshape(5, 2)
    landmarks_validos = (separacion >= .12*w and
                        np.all(landmarks[:, 0] >= x) and np.all(landmarks[:, 0] <= x+w) and
                        np.all(landmarks[:, 1] >= y) and np.all(landmarks[:, 1] <= y+h))
    minimo = cfg["min_rostro"] if minimo is None else minimo
    if min(w, h) < minimo:
        estado = "ROSTRO_MUY_PEQUENO"
    elif (datos["visible"] < .9 or not landmarks_validos or datos["roll"] > cfg["roll_max"] or datos["yaw"] > cfg["yaw_max"]):
        estado = "ANGULO_O_OCLUSION"
    elif datos["blur"] < cfg.get('blur_rechazo',cfg['blur_min']):
        estado = "IMAGEN_BORROSA"
    elif not cfg["iluminacion_min"] <= datos["iluminacion"] <= cfg["iluminacion_max"]:
        estado = "ILUMINACION_DEFICIENTE"
    elif datos['blur'] < cfg['blur_min']:
        estado='CALIDAD_ACEPTABLE'
    else:
        estado = "CALIDAD_OK"
    datos["calidad"] = float(min(1, min(w,h)/160) * min(1, datos["blur"]/max(cfg["blur_min"]*3, 1)) * min(1,datos["visible"]))
    return {**datos, "estado": estado, "valida": estado in ("CALIDAD_OK","CALIDAD_ACEPTABLE")}


class MotorEmbeddings:
    def __init__(self, cfg=None):
        self.cfg = cfg or cargar_configuracion()
        for nombre, digest in MODELOS.values():
            ruta = DIRECTORIO / nombre
            if not ruta.is_file():
                raise FileNotFoundError('Faltan modelos faciales. Ejecute: python tools/evaluar_reconocimiento_facial.py instalar-modelos')
            if sha256(ruta) != digest:
                raise RuntimeError(f"Modelo facial dañado o incompatible: {nombre}")
        backend, target = cv2.dnn.DNN_BACKEND_OPENCV, cv2.dnn.DNN_TARGET_CPU
        if self.cfg.get("backend") == "cuda" and cv2.cuda.getCudaEnabledDeviceCount() > 0:
            backend, target = cv2.dnn.DNN_BACKEND_CUDA, cv2.dnn.DNN_TARGET_CUDA
        self.detector = cv2.FaceDetectorYN.create(str(DIRECTORIO/MODELOS["detector"][0]), "", (320,320), self.cfg.get('detector_score',.9), self.cfg.get('detector_nms',.3), 5000, backend, target)
        self.reconocedor = cv2.FaceRecognizerSF.create(str(DIRECTORIO/MODELOS["reconocedor"][0]), "", backend, target)
        self._tile = 0

    def _detectar_region(self, frame, origen=(0, 0), lado=None):
        h, w = frame.shape[:2]
        escala = min(1.0, (lado or self.cfg["lado_deteccion"])/max(h,w))
        entrada = cv2.resize(frame, (max(32,round(w*escala)),max(32,round(h*escala)))) if escala < 1 else frame
        self.detector.setInputSize((entrada.shape[1], entrada.shape[0]))
        _, caras = self.detector.detect(entrada)
        if caras is None:
            return []
        sx, sy = w/entrada.shape[1], h/entrada.shape[0]
        caras = caras.copy()
        caras[:, [0,2,4,6,8,10,12]] *= sx
        caras[:, [1,3,5,7,9,11,13]] *= sy
        caras[:, [0,4,6,8,10,12]] += origen[0]
        caras[:, [1,5,7,9,11,13]] += origen[1]
        return list(caras)

    def detectar(self, frame, exhaustivo=False, regiones=None):
        h, w = frame.shape[:2]
        roi = self.cfg.get("roi")
        if roi:
            x,y,rw,rh = map(int, roi)
            if x < 0 or y < 0 or rw < 32 or rh < 32 or x+rw > w or y+rh > h:
                raise ValueError("ROI fuera de la resolución de cámara.")
        else:
            x,y,rw,rh = 0,0,w,h
        region = frame[y:y+rh,x:x+rw]
        caras = self._detectar_region(region, (x,y))
        tile = self.cfg["tile"]
        if max(rw,rh) > self.cfg["lado_deteccion"]:
            paso = int(tile*.75)
            xs = sorted(set(range(0,max(1,rw-tile+1),paso)) | {max(0,rw-tile)})
            ys = sorted(set(range(0,max(1,rh-tile+1),paso)) | {max(0,rh-tile)})
            posiciones = [(tx,ty) for ty in ys for tx in xs]
            seleccion = posiciones if exhaustivo else [posiciones[self._tile % len(posiciones)]]
            self._tile += 1
            for tx,ty in seleccion:
                caras += self._detectar_region(region[ty:ty+tile,tx:tx+tile],(x+tx,y+ty),tile)
        # Reobtiene landmarks en ROIs de tracks para caras que solo aparecieron en un tile.
        for caja in (regiones or [])[:4]:
            rx,ry,rw2,rh2=map(float,caja)
            rx1,ry1=max(x,int(rx-rw2*.5)),max(y,int(ry-rh2*.5))
            rx2,ry2=min(x+rw,int(rx+rw2*1.5)),min(y+rh,int(ry+rh2*1.5))
            if rx2-rx1>=32 and ry2-ry1>=32:
                caras+=self._detectar_region(frame[ry1:ry2,rx1:rx2],(rx1,ry1),tile)
        seleccionadas = []
        for cara in sorted(caras,key=lambda c:c[14],reverse=True):
            if not any(iou(cara[:4], otra[:4]) > .35 for otra in seleccionadas):
                seleccionadas.append(cara)
        return seleccionadas[:self.cfg["max_rostros"]]

    def alinear(self, frame, cara):
        # Recorte con margen, landmarks locales y transformación de similitud.
        x,y,w,h = cara[:4]
        alto, ancho = frame.shape[:2]
        x1,y1 = max(0,int(x-w*.2)),max(0,int(y-h*.2))
        x2,y2 = min(ancho,int(x+w*1.2)),min(alto,int(y+h*1.2))
        local = cara.copy()
        local[[0,4,6,8,10,12]] -= x1
        local[[1,5,7,9,11,13]] -= y1
        recorte = frame[y1:y2,x1:x2]
        return self.reconocedor.alignCrop(recorte, local)

    def extraer(self, frame, cara):
        alineado = self.alinear(frame,cara)
        # SFace aplica su normalización de entrada. No CLAHE agresivo ni SR generativa.
        return normalizar(self.reconocedor.feature(alineado).copy()), alineado


class GaleriaEmbeddings:
    def __init__(self, ruta=GALERIA, cargar=True):
        self.ruta = Path(ruta)
        self.vectores = np.empty((0,128), np.float32)
        self.subjects = np.array([], dtype="U40")
        self.empleados = np.array([], dtype=np.int64)
        self.archivos = np.array([], dtype="U300")
        if cargar and self.ruta.is_file():
            with np.load(self.ruta, allow_pickle=False) as datos:
                if str(datos["version"]) != VERSION_PIPELINE:
                    raise ValueError("Base facial incompatible. Es necesario regenerarla desde las imágenes originales.")
                for campo in ("vectores","subjects","empleados","archivos"):
                    setattr(self,campo,datos[campo].copy())
            if (self.vectores.ndim != 2 or self.vectores.shape[1] != 128 or len(self.vectores) != len(self.subjects) or
                    len(self.empleados) != len(self.subjects) or len(self.archivos) != len(self.subjects)):
                raise ValueError("Base facial incompatible. Es necesario regenerarla desde las imágenes originales.")
            try:self.vectores = np.stack([normalizar(v) for v in self.vectores]) if len(self.vectores) else self.vectores
            except ValueError:raise ValueError("Base facial incompatible: contiene vectores inválidos. Regenera la base desde las imágenes originales.") from None

    @property
    def firma(self):
        return sha256(self.ruta) if self.ruta.is_file() else "vacia"

    def guardar(self):
        self.ruta.parent.mkdir(parents=True,exist_ok=True)
        temporal = self.ruta.with_suffix(".tmp.npz")
        np.savez_compressed(temporal,version=np.array(VERSION_PIPELINE),vectores=self.vectores,
                            subjects=self.subjects,empleados=self.empleados,archivos=self.archivos)
        temporal.replace(self.ruta)

    def agregar(self, subject, empleado, vectores, archivos):
        if len(vectores) < 5:
            raise ValueError("Se requieren al menos cinco muestras faciales variadas.")
        vectores = np.stack([normalizar(v) for v in vectores])
        conservar = self.subjects != subject
        anteriores = self.vectores[conservar]
        self.vectores = np.concatenate([anteriores,vectores]) if len(anteriores) else vectores
        self.subjects = np.concatenate([self.subjects[conservar],np.array([subject]*len(vectores))])
        self.empleados = np.concatenate([self.empleados[conservar],np.array([empleado]*len(vectores),np.int64)])
        self.archivos = np.concatenate([self.archivos[conservar],np.array(archivos,dtype="U300")])

    def comparar(self, vector, permitidos=None):
        self.ultima_comparacion = {}
        if not len(self.vectores):
            return None,0.0,0.0
        similitudes = self.vectores @ normalizar(vector)
        puntajes = []
        for subject in np.unique(self.subjects):
            indices = np.flatnonzero(self.subjects == subject)
            # Promedio de las tres mejores muestras: un único parecido no basta.
            if len(indices) < 5:
                continue
            score = float(np.mean(np.sort(similitudes[indices])[-3:]))
            puntajes.append((score,str(subject)))
        if not puntajes:
            return None,0.0,0.0
        puntajes.sort(reverse=True)
        score, subject = puntajes[0]
        segundo = puntajes[1][0] if len(puntajes)>1 else -1.0
        self.ultima_comparacion = {'mejor_candidato':subject,'mejor_similitud':score,
            'segundo_candidato':puntajes[1][1] if len(puntajes)>1 else None,
            'segunda_similitud':segundo if len(puntajes)>1 else None}
        if permitidos is not None:
            empleado=permitidos.get(subject)
            indices=np.flatnonzero(self.subjects==subject)
            if not empleado or not empleado.get("empleado_activo") or any(self.empleados[indices]!=empleado["id_empleado"]):
                # No reasigna al segundo candidato al desactivar una identidad.
                return None,score,score-segundo
        return subject,score,score-segundo


def cargar_politica(galeria, cfg, ruta=CALIBRACION):
    ruta = Path(ruta)
    if not ruta.is_file():
        return None
    datos = json.loads(ruta.read_text(encoding="utf-8"))
    if (datos.get("galeria_sha256") != galeria.firma or datos.get("config_sha256") != firma_configuracion(cfg)
            or datos.get("pipeline") != VERSION_PIPELINE):
        return None
    if (not datos.get("calibrada") or not -1 <= datos.get("threshold",2) <= 1 or
            not 0 <= datos.get("margen",-1) <= 2 or datos.get("min_rostro",0) < 32):
        return None
    return datos


@dataclass
class TrackFacial:
    numero: int
    cara: np.ndarray
    visto: float
    evidencia: deque = field(default_factory=lambda: deque(maxlen=7))
    resultado: dict = field(default_factory=dict)
    confirmado: float = 0.0


class SeguimientoFacial:
    def __init__(self, cfg):
        self.cfg = cfg
        self.tracks = {}
        self.siguiente = 1
        self.gris_anterior = None

    def actualizar(self, frame, caras, ahora):
        self.tracks = {i:t for i,t in self.tracks.items() if ahora-t.visto <= self.cfg["timeout_track_s"]}
        asociaciones = []
        usados = set()
        for cara in caras:
            candidatos = sorted(((iou(t.cara[:4],cara[:4]),i) for i,t in self.tracks.items() if i not in usados),reverse=True)
            # Asociaciones ambiguas durante cruces invalidan toda evidencia.
            ambiguo = len(candidatos)>1 and candidatos[1][0]>.2 and candidatos[0][0]-candidatos[1][0]<.15
            if candidatos and candidatos[0][0] >= .3 and not ambiguo:
                track = self.tracks[candidatos[0][1]]
                # La identidad nunca se arrastra a una cara que salta de posición.
            else:
                if ambiguo:
                    for _,i in candidatos[:2]:
                        self.tracks[i].evidencia.clear()
                        self.tracks[i].resultado = {}
                        self.tracks[i].confirmado = 0
                track = TrackFacial(self.siguiente,cara.copy(),ahora,deque(maxlen=self.cfg["ventana_temporal"]))
                self.tracks[self.siguiente] = track
                self.siguiente += 1
            track.cara,track.visto = cara.copy(),ahora
            usados.add(track.numero)
            asociaciones.append(track)
        # Una detección ausente invalida inmediatamente la identificación mostrada.
        for i,t in self.tracks.items():
            if i not in usados:
                t.resultado = {}; t.evidencia.clear(); t.confirmado = 0
        self.gris_anterior = cv2.cvtColor(frame,cv2.COLOR_BGR2GRAY)
        return asociaciones

    def seguir(self, frame, ahora):
        gris = cv2.cvtColor(frame,cv2.COLOR_BGR2GRAY)
        visibles = []
        for t in list(self.tracks.values()):
            if ahora-t.visto > self.cfg["timeout_track_s"]:
                del self.tracks[t.numero]
                continue
            if self.gris_anterior is None or self.gris_anterior.shape != gris.shape:
                continue
            puntos = t.cara[4:14].reshape(-1,1,2).astype(np.float32)
            nuevos,ok,_ = cv2.calcOpticalFlowPyrLK(self.gris_anterior,gris,puntos,None)
            if nuevos is None or ok is None or int(ok.sum()) < 4:
                t.resultado = {}; t.evidencia.clear(); t.confirmado = 0
                continue
            buenos = ok.ravel().astype(bool)
            desplazamiento = np.median((nuevos-puntos)[buenos],axis=0).ravel()
            if np.linalg.norm(desplazamiento) > min(t.cara[2:4])*.35:
                t.resultado = {}; t.evidencia.clear(); t.confirmado = 0
                continue
            t.cara[[0,4,6,8,10,12]] += desplazamiento[0]
            t.cara[[1,5,7,9,11,13]] += desplazamiento[1]
            visibles.append(t)
        self.gris_anterior = gris
        return visibles


def decision_temporal(track, subject, score, margen, calidad, politica, cfg, ahora):
    base = {"estado": "VERIFICANDO", "reconocido": False, "etiqueta": None,
            "candidato": subject, "confianza": float(score), "similitud": float(score),
            "margen": float(margen), "track_id": track.numero, **calidad}
    base['threshold']=politica['threshold'] if politica else None
    base["estado"] = "VERIFICANDO"
    if not calidad["valida"]:
        track.evidencia.clear(); track.confirmado = 0
        return {**base,"estado":calidad["estado"]}
    if politica is None:
        track.evidencia.clear(); track.confirmado = 0
        return {**base,"estado":"SIN_CALIBRAR"}
    valido = subject is not None and score >= politica["threshold"] and margen >= politica["margen"]
    track.evidencia.append((ahora,subject if valido else None,score,calidad.get("calidad",0)))
    while track.evidencia and ahora-track.evidencia[0][0]>cfg["ttl_evidencia_s"]:
        track.evidencia.popleft()
    votos = Counter(s for _,s,_,_ in track.evidencia if s is not None)
    candidata, cantidad = votos.most_common(1)[0] if votos else (None,0)
    requeridas=cfg['muestras_temporales']+(2 if calidad['estado']=='CALIDAD_ACEPTABLE' else 0)
    suficiente = (len(track.evidencia)>=requeridas and cantidad>=requeridas and
                  cantidad/len(track.evidencia)>=cfg["fraccion_consenso"] and subject==candidata and valido)
    if suficiente:
        track.confirmado = ahora
        mejores=sorted((e for e in track.evidencia if e[1]==candidata),key=lambda e:e[3],reverse=True)[:cfg["muestras_temporales"]]
        score_estable = float(np.average([e[2] for e in mejores],weights=[max(e[3],.01) for e in mejores]))
        return {**base,"estado":"RECONOCIDO","reconocido":True,"etiqueta":candidata,"confianza":score_estable}
    track.confirmado = 0
    return {**base,"estado":"DESCONOCIDO" if len(track.evidencia)>=cfg["muestras_temporales"] and not valido else "VERIFICANDO"}


class PipelineFacial:
    def __init__(self, motor=None, galeria=None, cfg=None):
        self.cfg = cfg or cargar_configuracion()
        self.motor = motor or MotorEmbeddings(self.cfg)
        self.galeria = galeria or GaleriaEmbeddings()
        self.politica = cargar_politica(self.galeria,self.cfg)
        from core.system_state import state_manager
        ready=bool(len(self.galeria.vectores)) and self.politica is not None
        state_manager.track_resource('SFACE',self,available=ready,
            message='Modelo y galería preparados.' if ready else 'Modelo cargado; falta galería o calibración válida.',
            details={'model_loaded':True,'embeddings':len(self.galeria.vectores),'calibrated':self.politica is not None})
        self.tracker = SeguimientoFacial(self.cfg)
        self.frames = 0
        self.ultima_deteccion = -float("inf")

    def procesar(self, frame, empleados=None):
        inicio = time.perf_counter(); ahora = time.monotonic(); self.frames += 1
        detectar = (self.frames == 1 or self.frames % self.cfg["detectar_cada"] == 0 or
                    ahora-self.ultima_deteccion>=self.cfg["intervalo_deteccion_s"])
        if detectar:
            inicio_deteccion=time.perf_counter()
            regiones=[t.cara[:4] for t in sorted(self.tracker.tracks.values(),key=lambda t:t.cara[2]*t.cara[3])
                      if ahora-t.visto<=self.cfg["timeout_track_s"]]
            caras = self.motor.detectar(frame,regiones=regiones)
            tiempo_deteccion=(time.perf_counter()-inicio_deteccion)*1000
            tracks = self.tracker.actualizar(frame,caras,ahora)
            self.ultima_deteccion = ahora
            for track in tracks:
                minimo = self.politica["min_rostro"] if self.politica else self.cfg["min_rostro"]
                calidad = evaluar_calidad(frame,track.cara,self.cfg,minimo)
                subject,score,margen = None,0.0,0.0
                vector=None;tiempo_embedding=tiempo_comparacion=0.0
                # Una comparación diagnóstica no implica aceptar una identidad.
                if calidad['estado'] not in ('ROSTRO_MUY_PEQUENO','ANGULO_O_OCLUSION','BAJA_CALIDAD'):
                    inicio_embedding=time.perf_counter()
                    vector,_ = self.motor.extraer(frame,track.cara)
                    tiempo_embedding=(time.perf_counter()-inicio_embedding)*1000
                    inicio_comparacion=time.perf_counter()
                    subject,score,margen = self.galeria.comparar(vector,empleados)
                    tiempo_comparacion=(time.perf_counter()-inicio_comparacion)*1000
                track.resultado = decision_temporal(track,subject,score,margen,calidad,self.politica,self.cfg,ahora)
                track.resultado.update(tiempo_deteccion_ms=tiempo_deteccion,tiempo_embedding_ms=tiempo_embedding,
                    tiempo_comparacion_ms=tiempo_comparacion,embedding_estado='OK' if vector is not None else 'DESCARTADO_CALIDAD',
                    embedding_dimension=len(vector) if vector is not None else None,calidad_estado=calidad['estado'])
                if vector is None:track.resultado.update(similitud=None,candidato=None)
                if subject is not None or score != 0:
                    track.resultado.update(getattr(self.galeria,'ultima_comparacion',{}))
                import logging
                logging.getLogger('facial').debug('[FACIAL] motor=embeddings track=%s face=%.0fx%.0f quality=%s samples=%s best=%s best_score=%.2f second=%s threshold=%s decision=%s',
                    track.numero,track.cara[2],track.cara[3],calidad['estado'],len(self.galeria.vectores),subject,score,
                    self.galeria.ultima_comparacion.get('segunda_similitud') if vector is not None else None,
                    self.politica['threshold'] if self.politica else None,track.resultado['estado'])
        else:
            tracks = self.tracker.seguir(frame,ahora)
        resultados = []
        for track in tracks:
            resultado = dict(track.resultado)
            if not resultado:
                resultado = {"estado":"VERIFICANDO","reconocido":False,"etiqueta":None,"confianza":0.0}
            if resultado.get("reconocido") and ahora-track.confirmado>self.cfg["ttl_identidad_s"]:
                resultado.update(estado="VERIFICANDO",reconocido=False,etiqueta=None)
            if resultado.get("reconocido") and empleados is not None:
                empleado = empleados.get(resultado["etiqueta"])
                if not empleado or not empleado.get("empleado_activo"):
                    resultado.update(estado="EMPLEADO_INACTIVO",reconocido=False,etiqueta=None)
                else:
                    resultado.update({k:empleado.get(k) for k in ("id_empleado","codigo_empleado","nombre","cargo")})
            resultado.update(caja=tuple(map(int,track.cara[:4])),track_id=track.numero,
                             tiempo_inferencia_ms=(time.perf_counter()-inicio)*1000,
                             resolucion=f"{frame.shape[1]}x{frame.shape[0]}")
            resultados.append(resultado)
        return resultados
