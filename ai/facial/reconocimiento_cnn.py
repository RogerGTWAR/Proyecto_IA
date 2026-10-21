from core.paths import PROJECT_ROOT
pass
import json
import queue
import threading
import time
from collections import Counter, deque
from pathlib import Path

import cv2
import numpy as np

from inventory.alertas import registrar_alerta_empleado_no_reconocido
from surveillance.camara_utils import (CamaraUltimoFrame, MedidorRendimiento, cerrar_camara,
                          evento_cierre_opencv)
from ai.facial.dataset_rostros import preprocesar_region_rostro
from ai.facial.rostros_empleados import (obtener_cache_empleados_por_subject,
                               obtener_empleado_por_etiqueta)

BASE_DIR = PROJECT_ROOT
RUTA_MODELO = BASE_DIR / "modelos" / "modelo_rostros.keras"
RUTA_ETIQUETAS = BASE_DIR / "modelos" / "etiquetas_rostros.json"
RUTA_METRICAS = BASE_DIR / "modelos" / "metricas_modelo_rostros.json"
RUTA_CALIBRACION = BASE_DIR / "modelos" / 'ai.facial.calibracion_cnn.json'
_politica_cnn = None
UMBRAL_CONFIANZA = None
VENTANA_PREDICCIONES = 5
MINIMO_COINCIDENCIAS = 3
MODO_DEBUG_RECONOCIMIENTO = False
FRAMES_DESCONOCIDO_MINIMOS = 15
FRAMES_SIN_ROSTRO_REINICIO = 5
COOLDOWN_ALERTA_DESCONOCIDO = 60
PROCESAR_CADA_N_FRAMES = 3
ESCALA_DETECCION = 0.5
MIN_ROSTRO_ANCHO = 90
MIN_ROSTRO_ALTO = 90
UMBRAL_NITIDEZ = 45.0
ILUMINACION_MINIMA = 45.0
ILUMINACION_MAXIMA = 210.0

_bloqueo_camara = threading.Lock()
_evento_detener_camara = threading.Event()
_modelo_cnn = None
_etiquetas_cnn = None
_version_recursos = None
_inferir_cnn = None
_metricas_cnn = {}
ESTADOS_DESCONOCIDOS = {"DESCONOCIDO", "PREDICCION_BAJA", "SUBJECT_SIN_RELACION"}
NOMBRE_VENTANA = "Reconocimiento facial CNN"


def _politica_valida(politica):
    from ai.facial.base_facial import PREPROCESAMIENTO_CNN
    from ai.facial.pipeline_facial import sha256
    from ai.facial.seguridad_cnn import parametros_validos
    particiones=RUTA_MODELO.parent/'particiones_cnn.json'
    return (parametros_validos(politica) and particiones.is_file()
            and politica.get('particiones_sha256')==sha256(particiones)
            and politica.get('preprocesamiento')==PREPROCESAMIENTO_CNN
            and politica.get('modelo_sha256')==sha256(RUTA_MODELO)
            and politica.get('etiquetas_sha256')==sha256(RUTA_ETIQUETAS))


def _resultado_sin_rostro():
    return {"estado": "SIN_ROSTRO", "reconocido": False}


def _resultado_desconocido(confianza=0.0, estado="DESCONOCIDO"):
    return {"estado": estado, "reconocido": False, "id_empleado": None,
            "codigo_empleado": None, "nombre": "Desconocido", "cargo": None,
            "etiqueta": None, "confianza": float(confianza)}


def resolver_etiqueta(etiqueta, confianza, empleados_por_subject=None, margen=None):
    from ai.facial.seguridad_cnn import parametros_validos
    if not parametros_validos(_politica_cnn):
        return _resultado_desconocido(confianza,'CNN_NO_CALIBRADA')
    if (not etiqueta or not np.isfinite(confianza) or margen is None or not np.isfinite(margen)
            or float(confianza)<_politica_cnn['threshold'] or margen<_politica_cnn['margin']):
        return _resultado_desconocido(confianza, "PREDICCION_BAJA")
    empleado = ((empleados_por_subject or {}).get(etiqueta)
                if empleados_por_subject is not None else obtener_empleado_por_etiqueta(etiqueta))
    if empleado is None:
        return _resultado_desconocido(confianza, "SUBJECT_SIN_RELACION")
    if _politica_cnn.get('vinculos_sql',{}).get(etiqueta)!=empleado['id_empleado']:
        return _resultado_desconocido(confianza,'SUBJECT_SIN_RELACION')
    base = {"id_empleado": empleado["id_empleado"], "codigo_empleado": empleado["codigo_empleado"],
            "nombre": empleado["nombre"], "cargo": empleado["cargo"], "etiqueta": etiqueta,
            "confianza": float(confianza)}
    if not empleado["empleado_activo"]:
        return {"estado": "EMPLEADO_INACTIVO", "reconocido": False, **base}
    return {"estado": "RECONOCIDO", "reconocido": True, **base}


def verificar_detector_facial():
    try:
        return not _detector_rostros().empty()
    except Exception:
        return False


def _obtener_estado_cnn_legacy():
    modelo_existe = RUTA_MODELO.is_file() and RUTA_ETIQUETAS.is_file()
    modelo_valido = False
    if RUTA_METRICAS.is_file():
        try:
            modelo_valido = bool(json.loads(RUTA_METRICAS.read_text(encoding="utf-8")).get("modelo_valido"))
        except (OSError, ValueError):
            pass
    from ai.facial.base_facial import PREPROCESAMIENTO_CNN
    from ai.facial.pipeline_facial import sha256
    calibrada=False;p={}
    try:
        m=json.loads(RUTA_METRICAS.read_text(encoding='utf-8'))
        modelo_valido=modelo_valido and m.get('preprocesamiento')==PREPROCESAMIENTO_CNN
        p=json.loads(RUTA_CALIBRACION.read_text(encoding='utf-8'))
        calibrada=_politica_valida(p)
    except (OSError,ValueError):pass
    return {"modelo_existe": modelo_existe, "modelo_valido": modelo_valido and calibrada,'entrenada':modelo_valido,
            'calibrada':calibrada,"detector_listo":modelo_existe,'threshold':p.get('threshold') if calibrada else None,
            'margin':p.get('margin') if calibrada else None,'motivo':p.get('motivo','Falta calibración CNN.')}


def _cargar_recursos_impl():
    global _modelo_cnn, _etiquetas_cnn, _version_recursos, _inferir_cnn, _politica_cnn, UMBRAL_CONFIANZA, _metricas_cnn
    if not RUTA_MODELO.is_file() or not RUTA_ETIQUETAS.is_file():
        raise FileNotFoundError("La CNN todavía no ha sido entrenada. Entrene el modelo primero.")
    if not json.loads(RUTA_METRICAS.read_text(encoding='utf-8')).get('modelo_valido'):
        raise RuntimeError("El modelo no tiene métricas válidas. Reentrene la CNN.")
    import tensorflow as tf
    version = (RUTA_MODELO.stat().st_mtime_ns, RUTA_ETIQUETAS.stat().st_mtime_ns)
    if _modelo_cnn is None or version != _version_recursos:
        _modelo_cnn = tf.keras.models.load_model(RUTA_MODELO)
        datos = json.loads(RUTA_ETIQUETAS.read_text(encoding="utf-8"))
        _etiquetas_cnn = {int(i): etiqueta for i, etiqueta in datos.items()}
        if sorted(_etiquetas_cnn)!=list(range(_modelo_cnn.output_shape[-1])):
            raise RuntimeError('El mapeo de clases CNN no corresponde a las salidas del modelo.')
        if len(set(_etiquetas_cnn.values()))!=len(_etiquetas_cnn):
            raise RuntimeError('El mapeo CNN contiene etiquetas repetidas.')
        from ai.facial.base_facial import PREPROCESAMIENTO_CNN
        metricas=json.loads(RUTA_METRICAS.read_text(encoding='utf-8'))
        if metricas.get('preprocesamiento')!=PREPROCESAMIENTO_CNN or tuple(_modelo_cnn.input_shape[1:])!=(100,100,1):
            _modelo_cnn=None
            raise RuntimeError('CNN incompatible con la alineación actual. Ejecuta Entrenar CNN; se conserva el modelo anterior.')
        _version_recursos = version
        dummy = np.zeros((1, *_modelo_cnn.input_shape[1:]), dtype=np.float32)
        # Warm-up y selección medida entre llamada directa y predict.
        _modelo_cnn(dummy, training=False).numpy();_modelo_cnn.predict(dummy,verbose=0)
        directos=[];predicciones=[]
        for _ in range(3):
            inicio=time.perf_counter();_modelo_cnn(dummy,training=False).numpy();directos.append(time.perf_counter()-inicio)
            inicio=time.perf_counter();_modelo_cnn.predict(dummy,verbose=0);predicciones.append(time.perf_counter()-inicio)
        tiempo_directo=float(np.median(directos));tiempo_predict=float(np.median(predicciones))
        _metricas_cnn={'llamada_directa_ms':tiempo_directo*1000,'predict_ms':tiempo_predict*1000}
        _inferir_cnn = ((lambda lote: _modelo_cnn(lote, training=False).numpy())
                        if tiempo_directo <= tiempo_predict
                        else (lambda lote: _modelo_cnn.predict(lote, verbose=0)))
        if MODO_DEBUG_RECONOCIMIENTO:
            print(f"CNN warm-up | directa: {tiempo_directo*1000:.1f} ms | "
                  f"predict: {tiempo_predict*1000:.1f} ms")
    _politica_cnn=None;UMBRAL_CONFIANZA=None
    if RUTA_CALIBRACION.is_file():
        from ai.facial.pipeline_facial import sha256
        politica=json.loads(RUTA_CALIBRACION.read_text(encoding='utf-8'))
        from ai.facial.base_facial import PREPROCESAMIENTO_CNN
        if _politica_valida(politica):
            _politica_cnn=politica;UMBRAL_CONFIANZA=politica['threshold']
    return _modelo_cnn, _etiquetas_cnn, _inferir_cnn


def _cargar_recursos():
    from core.system_state import state_manager
    if state_manager.get('CNN').status=='UNVERIFIED':
        state_manager.update('CNN','STARTING','Cargando CNN.',activity='INITIALIZING')
    try:resources=_cargar_recursos_impl()
    except Exception:
        state_manager.update('CNN','ERROR','No se pudo cargar la CNN.',error='CNN_LOAD_FAILED',activity='IDLE')
        raise
    state_manager.update('CNN','ONLINE','CNN cargada.',activity='IDLE')
    return resources


def _detector_rostros():
    nombre = "haarcascade_frontalface_default.xml"
    candidatos = [Path(cv2.data.haarcascades) / nombre,
                   BASE_DIR / ".venv" / "Lib" / "site-packages" / "cv2" / "data" / nombre]
    for ruta in candidatos:
        if ruta.is_file():
            detector = cv2.CascadeClassifier(str(ruta))
            if not detector.empty():
                return detector
    raise RuntimeError("No se encontró Haar Cascade. Reinstale las dependencias del proyecto.")


class ControlAlertaDesconocido:
    def __init__(self, registrar=registrar_alerta_empleado_no_reconocido, reloj=time.monotonic):
        self.registrar = registrar; self.reloj = reloj
        self.frames_desconocido = 0; self.frames_sin_rostro = 0
        self.alertada = False; self.ultima_alerta = -float("inf")

    def procesar(self, estado):
        if estado == "SIN_ROSTRO":
            self.frames_sin_rostro += 1; self.frames_desconocido = 0
            if self.frames_sin_rostro >= FRAMES_SIN_ROSTRO_REINICIO:
                self.alertada = False
            return None
        self.frames_sin_rostro = 0
        if estado not in ESTADOS_DESCONOCIDOS:
            self.frames_desconocido = 0
            return None
        self.frames_desconocido += 1
        ahora = self.reloj()
        if (self.frames_desconocido >= FRAMES_DESCONOCIDO_MINIMOS and not self.alertada
                and ahora - self.ultima_alerta >= COOLDOWN_ALERTA_DESCONOCIDO):
            resultado = self.registrar(); self.alertada = True; self.ultima_alerta = ahora
            return resultado
        return None


def _detectar_y_recortar(frame, detector,cfg=None):
    from ai.facial.pipeline_facial import cargar_configuracion,medir_nitidez
    cfg=cfg or cargar_configuracion()
    inicio = time.perf_counter()
    caras=detector.detectar(frame)
    tiempo_deteccion=time.perf_counter()-inicio
    if len(caras)!=1:
        return None,None,tiempo_deteccion,0.0,'SIN_ROSTRO' if not caras else 'VARIOS_ROSTROS'
    from ai.facial.pipeline_facial import evaluar_calidad
    cara=caras[0];caja=tuple(map(int,cara[:4]))
    calidad=evaluar_calidad(frame,cara,cfg)
    if not calidad['valida']:
        return caja,None,tiempo_deteccion,0.0,calidad['estado']
    inicio=time.perf_counter()
    alineada=detector.alinear(frame,cara)
    from ai.facial.cnn_dataset import entrada_alineada_cnn
    entrada=entrada_alineada_cnn(alineada)
    return caja,entrada,tiempo_deteccion,time.perf_counter()-inicio,calidad['estado']


def _reemplazar_ultimo(cola, elemento):
    try:
        cola.put_nowait(elemento)
    except queue.Full:
        try: cola.get_nowait()
        except queue.Empty: pass
        try: cola.put_nowait(elemento)
        except queue.Full: pass


def _worker_inferencia(cola_frames, resultados, detener, detector, inferir, etiquetas,
                       empleados_por_subject, callback_alerta,modo_dataset=False,politica_provisional=None):
    from ai.facial.seguridad_cnn import EvidenciaCNN,ranking
    if modo_dataset:
        from ai.facial.cnn_dataset_actual import politica_valida
    evidencia=EvidenciaCNN(ventana=VENTANA_PREDICCIONES,minimo=4,ttl=2.0,
        validador=politica_valida if modo_dataset else None)
    politica=politica_provisional if modo_dataset else _politica_cnn
    control_alerta = ControlAlertaDesconocido()
    inicio_metricas = time.perf_counter(); detecciones = inferencias = 0;total_cnn_ms=0.0
    inicio_rostro = None
    subject_confirmado = None
    proximo_sql=time.monotonic()+5
    caja_anterior=None
    from ai.facial.pipeline_facial import cargar_configuracion
    cfg=cargar_configuracion()
    while not detener.is_set():
        try:
            dato=cola_frames.get(timeout=0.1)
            numero,frame=dato[:2];tomado=dato[2] if len(dato)>2 else time.monotonic()
        except queue.Empty: continue
        if time.monotonic()-tomado>cfg['ttl_identidad_s']:
            evidencia.limpiar();subject_confirmado=None;continue
        if not modo_dataset and time.monotonic()>=proximo_sql:
            try:empleados_por_subject=obtener_cache_empleados_por_subject()
            except Exception:empleados_por_subject={}
            proximo_sql=time.monotonic()+5
        caja, entrada, t_deteccion, t_preproceso, estado_calidad = _detectar_y_recortar(frame, detector,cfg)
        if caja is not None and caja_anterior is not None:
            from ai.facial.pipeline_facial import iou
            if iou(caja,caja_anterior)<.35:evidencia.limpiar();subject_confirmado=None;inicio_rostro=None
        caja_anterior=caja
        detecciones += 1
        if entrada is None:
            evidencia.limpiar()
            inicio_rostro = None
            subject_confirmado = None
            resultado = (_resultado_sin_rostro() if estado_calidad == "SIN_ROSTRO"
                         else _resultado_desconocido(0.0, estado_calidad))
            t_cnn = 0.0
        else:
            if inicio_rostro is None: inicio_rostro = time.perf_counter()
            inicio = time.perf_counter()
            probabilidades = inferir(entrada[None, ...])[0]
            if not np.isfinite(probabilidades).all():
                raise RuntimeError('La CNN produjo valores no finitos.')
            inferencias += 1
            t_cnn = time.perf_counter() - inicio
            total_cnn_ms+=t_cnn*1000
            fila=ranking(probabilidades,etiquetas)
            estado,candidata=evidencia.actualizar(fila,politica,time.monotonic())
            if modo_dataset:
                resultado=({'estado':'RECONOCIDO','reconocido':True,'nombre':candidata,
                    'etiqueta':candidata,'confianza':fila['best_score'],'modo':'Dataset actual'}
                    if candidata else _resultado_desconocido(fila['best_score'],estado if estado!='CNN_NO_CALIBRADA' else 'DESCONOCIDO'))
            else:resultado=(resolver_etiqueta(candidata,fila['best_score'],empleados_por_subject,margen=fila['margin'])
                       if candidata else _resultado_desconocido(fila['best_score'],estado))
            if (resultado['estado']=='RECONOCIDO' and inicio_rostro is not None
                    and candidata!=subject_confirmado):
                resultado['latencia_reconocimiento']=time.perf_counter()-inicio_rostro
                subject_confirmado=candidata
            resultado.update(fila)
            resultado.update(candidato=fila['best_class'],confianza_frame=fila['best_score'],
                estable=resultado['estado']=='RECONOCIDO',
                threshold=politica['threshold'] if politica else None,
                margen_minimo=politica['margin'] if politica else None)
            import logging
            logging.getLogger('facial').debug('[FACIAL CNN] input=100x100x1 inference_ms=%.2f best=%s score=%.2f second=%s second_score=%.2f margin=%.2f threshold=%s decision=%s',
                t_cnn*1000,fila['best_class'],fila['best_score'],fila['second_class'],fila['second_score'],fila['margin'],resultado['threshold'],resultado['estado'])
        alerta = control_alerta.procesar(resultado["estado"]) if not modo_dataset else None
        if alerta and callback_alerta: callback_alerta(alerta)
        resultado.update({"caja": caja, "numero_frame": numero, "tomado_en":tomado,"tiempo_deteccion": t_deteccion,
                          "tiempo_preproceso": t_preproceso, "tiempo_cnn": t_cnn,
                          "fps_deteccion": detecciones / max(time.perf_counter()-inicio_metricas, .001),
                          "fps_cnn": inferencias / max(time.perf_counter()-inicio_metricas, .001)})
        resultado['latencia_cnn_ms_promedio']=total_cnn_ms/inferencias if inferencias else None
        _reemplazar_ultimo(resultados, resultado)


def _reconocer_cnn_legacy(callback_alerta=None, presentador=None, fuente=None,modo_cnn='Validación estricta'):
    if not _bloqueo_camara.acquire(blocking=False):
        raise RuntimeError("La cámara ya está siendo utilizada.")
    capturador = None
    detener_inferencia = threading.Event()
    hilo_inferencia = None
    try:
        _evento_detener_camara.clear()
        if presentador is not None and presentador.cierre_solicitado:
            _evento_detener_camara.set()
            return _resultado_sin_rostro()
        modo_dataset=modo_cnn=='Dataset actual'
        politica_provisional=None
        if modo_dataset:
            from ai.facial.cnn_dataset_actual import recursos
            _modelo,etiquetas,inferir,politica_provisional=recursos()
        else:_modelo, etiquetas, inferir = _cargar_recursos()
        inicio_sql = time.perf_counter()
        empleados_por_subject = {} if modo_dataset else obtener_cache_empleados_por_subject()
        tiempo_sql = time.perf_counter() - inicio_sql
        from ai.facial.pipeline_facial import MotorEmbeddings
        detector = MotorEmbeddings()
        from ai.facial.pipeline_facial import cargar_configuracion
        cfg=cargar_configuracion()
        if modo_dataset:cfg={**cfg,'cnn_interval_frames':max(3,min(5,int(cfg.get('cnn_interval_frames',3))))}
        capturador = CamaraUltimoFrame(cfg['fuente_video'] if fuente is None else fuente,cfg['resolucion']).iniciar()
        cola_frames, resultados = queue.Queue(maxsize=1), queue.Queue(maxsize=1)
        def ejecutar_worker():
            try:
                _worker_inferencia(cola_frames,resultados,detener_inferencia,detector,inferir,etiquetas,
                                   empleados_por_subject,callback_alerta,modo_dataset,politica_provisional)
            except Exception as error:
                _reemplazar_ultimo(resultados,error)
        hilo_inferencia = threading.Thread(
            target=ejecutar_worker,
            name="camara-inferencia", daemon=False)
        hilo_inferencia.start()
        print(f"Escáner: resolución real {capturador.resolucion[0]}x{capturador.resolucion[1]} | "
              f"Cache SQL: {len(empleados_por_subject)} subjects en {tiempo_sql*1000:.1f} ms")
        ultimo = _resultado_sin_rostro()
        ultimo_numero = -1
        frames_mostrados = 0
        medidor = MedidorRendimiento()
        ventana_creada = False
        while not _evento_detener_camara.is_set():
            numero, frame = capturador.leer()
            if capturador.error: raise capturador.error
            if frame is None or numero == ultimo_numero:
                if (_evento_detener_camara.is_set() if presentador else
                        evento_cierre_opencv(NOMBRE_VENTANA, _evento_detener_camara, ventana_creada)):
                    return ultimo
                _evento_detener_camara.wait(.005)
                continue
            ultimo_numero = numero
            frames_mostrados += 1
            medidor.tiempos["Captura"] = capturador.ultima_lectura_ms
            if frames_mostrados % cfg.get('cnn_interval_frames',PROCESAR_CADA_N_FRAMES) == 0:
                # La copia es necesaria: la UI dibuja sobre su frame mientras la IA trabaja.
                _reemplazar_ultimo(cola_frames, (numero, frame.copy(),time.monotonic()))
            try:
                nuevo=resultados.get_nowait()
                if isinstance(nuevo,Exception):raise nuevo
                ultimo=nuevo
            except queue.Empty: pass
            if time.monotonic()-ultimo.get('tomado_en',time.monotonic())>cfg['ttl_identidad_s']:
                ultimo={'estado':'VERIFICANDO','reconocido':False}
            caja = ultimo.get("caja")
            if caja and modo_dataset:
                x,y,w,h=map(int,caja);color=(0,190,80) if ultimo.get('reconocido') else (0,180,230)
                cv2.rectangle(frame,(x,y),(x+w,y+h),color,2)
                textos=([ultimo['nombre'],f"Confianza: {ultimo.get('confianza',0):.2f}",'RECONOCIDO']
                    if ultimo.get('reconocido') else ['DESCONOCIDO' if ultimo['estado']=='DESCONOCIDO' else 'VERIFICANDO...'])
                for i,texto in enumerate(textos):
                    cv2.putText(frame,texto,(max(0,x),max(22,y-55)+i*22),cv2.FONT_HERSHEY_SIMPLEX,.6,color,2)
            elif caja:
                from ai.facial.reconocimiento_embeddings import dibujar
                estado_visual={'CNN_NO_CALIBRADA':'CNN sin calibracion segura','SIN_ROSTRO':'BUSCANDO',
                    'ANGULO_O_OCLUSION':'Ajuste el angulo','IMAGEN_BORROSA':'Calidad baja',
                    'ILUMINACION_DEFICIENTE':'Mejore la iluminacion','ROSTRO_MUY_PEQUENO':'Acerquese'}.get(ultimo['estado'],ultimo['estado'])
                dibujar(frame,[dict(ultimo,caja=caja,track_id=1,motor='cnn',similitud=ultimo.get('confianza'),estado=estado_visual)])
            fps = medidor.nuevo_frame()
            ultimo['fps_video']=fps
            medidor.registrar("Detección", ultimo.get("tiempo_deteccion", 0.0))
            medidor.registrar("Preproceso", ultimo.get("tiempo_preproceso", 0.0))
            medidor.registrar("CNN", ultimo.get("tiempo_cnn", 0.0))
            medidor.registrar("SQL inicial", tiempo_sql)
            medidor.registrar_valor("FPS detección", ultimo.get("fps_deteccion", 0.0))
            medidor.registrar_valor("FPS CNN", ultimo.get("fps_cnn", 0.0))
            if "latencia_reconocimiento" in ultimo:
                medidor.registrar("Latencia", ultimo["latencia_reconocimiento"])
            if presentador:
                from core.formato_numerico import format_numero
                estados = {"SIN_ROSTRO": "Buscando rostro...", "RECONOCIDO": "Reconocido",
                           "EMPLEADO_INACTIVO": "Empleado inactivo", "PREDICCION_BAJA": "Analizando...",
                           "DESCONOCIDO": "Desconocido", "SUBJECT_SIN_RELACION": "Desconocido",
                           "ROSTRO_PEQUENO": "Acérquese a la cámara",
                           "IMAGEN_BORROSA": "Imagen borrosa",
                           "ILUMINACION_DEFICIENTE": "Mejore la iluminación",
                           "VARIOS_ROSTROS": "Se detectaron varios rostros",
                           'CNN_NO_CALIBRADA':'CNN sin calibración segura',
                           'VERIFICANDO':'Verificando...',
                           'ANGULO_O_OCLUSION':'Ajuste el ángulo del rostro',
                           'ROSTRO_MUY_PEQUENO':'Acérquese a la cámara'}
                presentador.publicar_frame(frame)
                presentador.publicar_info(
                    persona=ultimo.get("nombre", "-") if ultimo.get("reconocido") or
                            ultimo.get("estado") == "EMPLEADO_INACTIVO" else "-",
                    codigo=ultimo.get("codigo_empleado") or "-",
                    cargo=ultimo.get("cargo") or "-",
                    confianza=format_numero(ultimo.get('confianza')) if caja else '-',
                    metricas='Video '+format_numero(fps)+' FPS / CNN '+format_numero(ultimo.get('fps_cnn'))+' FPS',
                    debug='CNN '+str(ultimo.get('best_class') or '—')+' / segundo '+str(ultimo.get('second_class') or '—')+
                          ' · Score '+format_numero(ultimo.get('best_score'))+' / '+format_numero(ultimo.get('second_score'))+
                          ' · Margen '+format_numero(ultimo.get('margin'))+' · Umbral '+format_numero(ultimo.get('threshold'))+
                          ' · Margen mínimo '+format_numero(ultimo.get('margen_minimo'))+
                          ' · CNN '+format_numero(ultimo.get('tiempo_cnn',0)*1000)+' ms',
                    estado=estados.get(ultimo["estado"], ultimo["estado"]))
                if _evento_detener_camara.is_set(): return ultimo
            else:
                if not modo_dataset:cv2.putText(frame, f"Video {fps:.2f} FPS | CNN {ultimo.get('fps_cnn',0):.2f}/s | ESC o Q", (15,28), cv2.FONT_HERSHEY_SIMPLEX,.65,(255,255,255),2)
                cv2.imshow(NOMBRE_VENTANA, frame); ventana_creada = True
                if evento_cierre_opencv(NOMBRE_VENTANA, _evento_detener_camara): return ultimo
        return ultimo
    finally:
        cerrar_camara(eventos=(_evento_detener_camara, detener_inferencia),
                      capturador=capturador, workers=(hilo_inferencia,),
                      nombre_ventana=None if presentador else NOMBRE_VENTANA)
        _bloqueo_camara.release()


def obtener_estado_cnn(motor=None,modo_cnn='Validación estricta'):
    """Nombre conservado para compatibilidad; informa el motor seleccionado."""
    from ai.facial.pipeline_facial import (DIRECTORIO,MODELOS,GaleriaEmbeddings,cargar_configuracion,cargar_politica)
    cfg=cargar_configuracion()
    motor=motor or cfg["motor"]
    if motor=="cnn":
        if modo_cnn=='Dataset actual':
            from ai.facial.cnn_dataset_actual import estado
            return estado()
        return {**_obtener_estado_cnn_legacy(),"motor":"cnn"}
    if motor not in ('embeddings','comparacion'):
        raise ValueError("Motor facial inválido.")
    existe=all((DIRECTORIO/n).is_file() for n,_ in MODELOS.values())
    galeria=GaleriaEmbeddings()
    politica=cargar_politica(galeria,cfg)
    return {"modelo_existe":existe,"modelo_valido":existe and politica is not None,
            "detector_listo":existe,"motor":motor,"muestras":len(galeria.vectores),
            "subjects":sorted(set(map(str,galeria.subjects))),"calibrada":politica is not None}


def reconocer_con_camara(callback_alerta=None,presentador=None,motor=None,fuente=None,modo_cnn='Validación estricta'):
    from ai.facial.pipeline_facial import cargar_configuracion
    seleccionado=motor or cargar_configuracion()["motor"]
    if seleccionado=="cnn":
        if modo_cnn not in ('Dataset actual','Validación estricta'):raise ValueError('Modo CNN inválido.')
        return _reconocer_cnn_legacy(callback_alerta,presentador,fuente,modo_cnn)
    if seleccionado not in ('embeddings','comparacion'):
        raise ValueError("Motor facial inválido.")
    from ai.facial.reconocimiento_embeddings import reconocer_embeddings
    return reconocer_embeddings(callback_alerta,presentador,fuente,comparar_cnn=seleccionado=='comparacion')


def detener_reconocimiento():
    _evento_detener_camara.set()


if __name__ == "__main__":
    try:
        print(reconocer_con_camara())
    except (RuntimeError, FileNotFoundError, ValueError) as error:
        print(f"ERROR: {error}")
