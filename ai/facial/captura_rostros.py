from core.paths import PROJECT_ROOT
pass
import queue
import re
import shutil
import threading
import time
from pathlib import Path

import cv2
import numpy as np

from surveillance.camara_utils import (CamaraUltimoFrame, MedidorRendimiento, cerrar_camara,
                          evento_cierre_opencv)
from ai.facial.dataset_rostros import RUTA_DATASET, preprocesar_region_rostro
from ai.facial.reconocimiento_cnn import _bloqueo_camara, _detector_rostros, _evento_detener_camara
from ai.facial.rostros_empleados import asignar_etiqueta_empleado

BASE_DIR = PROJECT_ROOT
CARPETA_TEMP = BASE_DIR / "rostros_temp"
NUM_IMAGENES_CAPTURA = 30
MIN_IMAGENES_VALIDAS = 20
INTERVALO_ENTRE_FOTOS = 0.35
PROCESAR_CADA_N_FRAMES = 3
ESCALA_DETECCION = 0.5
DIFERENCIA_MINIMA = 2.0
PATRON = re.compile(r"^subject(\d+)", re.IGNORECASE)
INSTRUCCIONES = ("Mira al frente", "Gira ligeramente a la izquierda",
                 "Gira ligeramente a la derecha", "Expresión normal", "Sonríe")
NOMBRE_VENTANA = "Registrar rostro"


def obtener_siguiente_subject():
    RUTA_DATASET.mkdir(parents=True,exist_ok=True)
    numeros = [int(m.group(1)) for a in RUTA_DATASET.iterdir()
               if (m := PATRON.match(a.name))]
    return f"subject{max(numeros, default=0)+1:02d}"


def _detectar_reducido(frame, detector):
    pequeno = cv2.resize(frame, None, fx=ESCALA_DETECCION, fy=ESCALA_DETECCION,
                         interpolation=cv2.INTER_AREA)
    gris = cv2.cvtColor(pequeno, cv2.COLOR_BGR2GRAY)
    rostros = detector.detectMultiScale(gris, 1.2, 5, minSize=(35, 35))
    factor = 1.0 / ESCALA_DETECCION
    return [tuple(int(v * factor) for v in rostro) for rostro in rostros]


def _recortar_con_margen(gris, caja, margen=0.15):
    x, y, ancho, alto = caja
    mx, my = int(ancho * margen), int(alto * margen)
    h, w = gris.shape[:2]
    return gris[max(0, y-my):min(h, y+alto+my), max(0, x-mx):min(w, x+ancho+mx)]


def _worker_guardado(cola, resultados, detener):
    while not detener.is_set() or not cola.empty():
        try:
            ruta, imagen = cola.get(timeout=0.1)
        except queue.Empty:
            continue
        inicio = time.perf_counter()
        try:
            correcto = cv2.imwrite(str(ruta), imagen)
        except cv2.error:
            correcto = False
        resultados.put((correcto, time.perf_counter() - inicio))
        cola.task_done()


def _descartar_pendientes(cola):
    while True:
        try: cola.get_nowait()
        except queue.Empty: break
        else: cola.task_done()


def _capturar_rostros_cnn_legacy(id_empleado, presentador=None):
    if not _bloqueo_camara.acquire(blocking=False):
        raise RuntimeError("La cámara ya está siendo utilizada.")
    subject = obtener_siguiente_subject()
    temporal = CARPETA_TEMP / subject
    if temporal.exists(): shutil.rmtree(temporal)
    temporal.mkdir(parents=True)
    capturador = None
    cola_guardado = queue.Queue(maxsize=NUM_IMAGENES_CAPTURA)
    resultados = queue.Queue()
    detener_guardado = threading.Event()
    worker = threading.Thread(target=_worker_guardado, args=(cola_guardado, resultados, detener_guardado),
                              name="camara-guardado", daemon=False)
    encoladas = guardadas = procesadas = 0
    ultima_captura = 0.0
    ultimo_rostro = None
    ultima_caja = None
    ultimo_numero = -1
    medidor = MedidorRendimiento()
    frames_mostrados = 0
    cancelado = False
    ventana_creada = False
    try:
        _evento_detener_camara.clear()
        if presentador is not None and presentador.cierre_solicitado:
            _evento_detener_camara.set()
            return {"completado": False, "subject": None, "imagenes_guardadas": 0,
                    "fps_video": 0.0}
        detector = _detector_rostros()
        capturador = CamaraUltimoFrame().iniciar()
        worker.start()
        print(f"Cámara de registro: resolución real {capturador.resolucion[0]}x{capturador.resolucion[1]}")
        while encoladas < NUM_IMAGENES_CAPTURA or procesadas < encoladas:
            numero, frame = capturador.leer()
            if capturador.error: raise capturador.error
            if frame is None or numero == ultimo_numero:
                if (_evento_detener_camara.is_set() if presentador else
                        evento_cierre_opencv(NOMBRE_VENTANA, _evento_detener_camara, ventana_creada)):
                    cancelado = True; break
                continue
            ultimo_numero = numero
            frames_mostrados += 1
            inicio_frame = time.perf_counter()
            medidor.tiempos["Captura"] = capturador.ultima_lectura_ms
            if frames_mostrados % PROCESAR_CADA_N_FRAMES == 0:
                inicio = time.perf_counter()
                rostros = _detectar_reducido(frame, detector)
                ultima_caja = rostros[0] if len(rostros) == 1 else None
                medidor.registrar("Detección", time.perf_counter() - inicio)
            if ultima_caja:
                x, y, ancho, alto = ultima_caja
                ahora = time.monotonic()
                if encoladas < NUM_IMAGENES_CAPTURA and ahora-ultima_captura >= INTERVALO_ENTRE_FOTOS:
                    inicio = time.perf_counter()
                    # Se procesa antes de dibujar para no guardar el rectángulo.
                    gris = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                    rostro = _recortar_con_margen(gris, ultima_caja)
                    imagen = (preprocesar_region_rostro(rostro)[..., 0] * 255).astype("uint8")
                    medidor.registrar("Preproceso", time.perf_counter() - inicio)
                    diferencia = (float(np.mean(cv2.absdiff(imagen, ultimo_rostro)))
                                  if ultimo_rostro is not None else float("inf"))
                    if diferencia >= DIFERENCIA_MINIMA:
                        encoladas += 1
                        cola_guardado.put_nowait((temporal / f"{subject}.capture{encoladas:03d}.png",
                                                 imagen.copy()))
                        ultimo_rostro, ultima_captura = imagen, ahora
                cv2.rectangle(frame, (x, y), (x+ancho, y+alto), (0, 200, 0), 2)
            while True:
                try: correcto, tiempo_guardado = resultados.get_nowait()
                except queue.Empty: break
                procesadas += 1
                if correcto: guardadas += 1
                medidor.registrar("Guardado", tiempo_guardado)
            instruccion = INSTRUCCIONES[min(len(INSTRUCCIONES)-1,
                                            encoladas * len(INSTRUCCIONES) // NUM_IMAGENES_CAPTURA)]
            fps = medidor.nuevo_frame()
            medidor.registrar("Render", time.perf_counter() - inicio_frame)
            if presentador:
                presentador.publicar_frame(frame)
                presentador.publicar_info(
                    contador=f"{guardadas} / {NUM_IMAGENES_CAPTURA}",
                    estado="Rostro válido" if ultima_caja else "Buscando un solo rostro...",
                    instruccion=instruccion)
                if _evento_detener_camara.is_set(): cancelado = True; break
            else:
                cv2.putText(frame, f"{instruccion} | Capturadas: {guardadas}/{NUM_IMAGENES_CAPTURA}",
                            (15,30), cv2.FONT_HERSHEY_SIMPLEX,.65,(0,255,0),2)
                cv2.putText(frame, f"FPS {fps:.0f} | ESC o Q cancela", (15,60),
                            cv2.FONT_HERSHEY_SIMPLEX,.58,(255,255,255),2)
                cv2.imshow(NOMBRE_VENTANA, frame); ventana_creada = True
                if evento_cierre_opencv(NOMBRE_VENTANA, _evento_detener_camara):
                    cancelado = True; break
        if cancelado:
            _descartar_pendientes(cola_guardado)
        detener_guardado.set(); worker.join(timeout=5.0)
        completado = guardadas >= MIN_IMAGENES_VALIDAS
        if completado:
            RUTA_DATASET.mkdir(parents=True, exist_ok=True)
            movidos = []
            for archivo in temporal.iterdir():
                destino = RUTA_DATASET / archivo.name
                shutil.move(str(archivo), str(destino)); movidos.append(destino)
            try:
                inicio_sql = time.perf_counter()
                asignar_etiqueta_empleado(id_empleado, subject)
                medidor.registrar("SQL", time.perf_counter() - inicio_sql)
            except Exception:
                for archivo in movidos: archivo.unlink(missing_ok=True)
                raise
        return {"completado": completado, "subject": subject if completado else None,
                "imagenes_guardadas": guardadas, "fps_video": medidor.fps_suave}
    finally:
        cerrar_camara(eventos=(_evento_detener_camara, detener_guardado),
                      capturador=capturador, workers=(worker,),
                      nombre_ventana=None if presentador else NOMBRE_VENTANA)
        if temporal.exists(): shutil.rmtree(temporal)
        _bloqueo_camara.release()


def capturar_rostros_nuevo_empleado(id_empleado,presentador=None,motor=None):
    from ai.facial.pipeline_facial import cargar_configuracion
    seleccionado=motor or cargar_configuracion()["motor"]
    if seleccionado=='cnn':return _capturar_sesion_cnn(id_empleado,presentador)
    if seleccionado not in ("embeddings","cnn"):
        raise ValueError("Motor facial inválido.")
    from ai.facial.reconocimiento_embeddings import registrar_embeddings
    return registrar_embeddings(id_empleado,presentador)


def _capturar_sesion_cnn(id_empleado,presentador=None):
    """Amplía solo CNN; no modifica galerías SFace ni relaciones SQL."""
    import json
    import uuid
    from datetime import datetime
    from ai.facial.pipeline_facial import MotorEmbeddings,cargar_configuracion,evaluar_calidad,escribir_json_atomico
    from ai.facial.rostros_empleados import obtener_cache_empleados_por_subject
    from ai.facial.cnn_dataset import MUESTRAS_CNN,cercanas,cargar
    from ai.facial.sesiones_cnn import plan_subject,respaldar_imagenes,MIN_IMAGENES,OBJETIVO_IMAGENES
    cache=obtener_cache_empleados_por_subject()
    subject=next((s for s,e in cache.items() if e['id_empleado']==int(id_empleado) and e.get('empleado_activo')),None)
    if subject is None:raise ValueError('Para ampliar CNN seleccione un empleado activo con etiqueta facial vinculada en SQL.')
    plan=getattr(presentador,'plan_cnn',None)
    if not plan or plan['subject']!=subject or not hasattr(presentador,'solicitud_foto'):
        raise ValueError('Abra Capturar sesión CNN y confirme la persona antes de iniciar.')
    if not _bloqueo_camara.acquire(blocking=False):raise RuntimeError('La cámara ya está siendo utilizada.')
    captura=None;registros=[];entradas=[];inicio=time.monotonic();frames=0;anterior=-1;ultima=0.0
    carpeta=MUESTRAS_CNN/subject/uuid.uuid4().hex
    fecha=datetime.now().astimezone().isoformat()
    procedencia={'subject':subject,'session_id':carpeta.name,
        'fecha':fecha,'fecha_hora':fecha,'grupo':f'{subject}:captura:{carpeta.name}',
        'condicion':plan['condicion'],'numero_sesion':plan['numero'],'instrucciones':list(plan['instrucciones'])}
    try:
        _evento_detener_camara.clear()
        if presentador and presentador.cierre_solicitado:return {'completado':False,'imagenes_guardadas':0,'motor':'cnn','subject':subject}
        # Revalida SQL, sesiones y contenido antes de abrir cámara; no entrena.
        datos=cargar()
        actual=plan_subject(subject,datos['reporte_dataset'])
        if actual['numero']!=plan['numero'] or actual.get('condicion')!=plan['condicion']:
            raise ValueError('El plan de sesiones cambió. Vuelva a abrir Capturar sesión CNN.')
        anteriores=[imagen for imagen,meta in zip(datos['X'],datos['metadatos']) if meta['subject']==subject]
        respaldo=respaldar_imagenes()
        cfg=cargar_configuracion();motor=MotorEmbeddings(cfg)
        carpeta.mkdir(parents=True,exist_ok=False)
        captura=CamaraUltimoFrame(cfg['fuente_video'],cfg['resolucion']).iniciar()
        escribir_json_atomico(carpeta/'sesion.json',{**procedencia,'completa':False,'imagenes':0})
        estado='Pulsa Capturar imagen cuando estés listo.'
        while len(registros)<OBJETIVO_IMAGENES and time.monotonic()-inicio<300 and not _evento_detener_camara.is_set():
            if presentador.fin_sesion.is_set() and len(registros)>=MIN_IMAGENES:break
            numero,frame=captura.leer()
            if captura.error:raise captura.error
            if frame is None or numero==anterior:
                _evento_detener_camara.wait(.005);continue
            anterior=numero;frames+=1
            instruccion=plan['instrucciones'][len(registros)%len(plan['instrucciones'])]
            if presentador.solicitud_foto.is_set():
                presentador.solicitud_foto.clear()
                if time.monotonic()-ultima<1:
                    estado='Espera un momento y cambia la pose antes de capturar.'
                    presentador.publicar_info(estado=estado);continue
                caras=motor.detectar(frame)
                if len(caras)==1:
                    cara=caras[0];q=evaluar_calidad(frame,cara,cfg)
                    estado='Imagen descartada: baja calidad. '+q['estado']
                    if q['valida']:
                        alineada=motor.alinear(frame,cara)
                        entrada=preprocesar_region_rostro(cv2.cvtColor(alineada,cv2.COLOR_BGR2GRAY))
                        if any(cercanas(entrada,a) for a in entradas+anteriores):estado='Imagen descartada: casi duplicada. Cambia pose o condiciones.'
                        else:
                            nombre=f'{subject}_{carpeta.name}_{len(registros)+1:03d}.png'
                            if not cv2.imwrite(str(carpeta/nombre),frame):raise OSError('No se pudo guardar la captura CNN.')
                            registros.append({**procedencia,'fecha_hora':datetime.now().astimezone().isoformat(),
                                'original':nombre,'calidad':q,'etapa':instruccion});entradas.append(entrada)
                            # Cada sesión se conserva íntegra; la partición nunca divide sus frames.
                            escribir_json_atomico(carpeta/'registro.json',registros)
                            escribir_json_atomico(carpeta/'sesion.json',{**procedencia,'completa':False,'imagenes':len(registros)})
                            estado='Muestra capturada';ultima=time.monotonic()
                else:estado='Imagen descartada: se requiere exactamente un rostro.'
            if presentador:
                presentador.publicar_frame(frame)
                presentador.publicar_info(contador=f"Sesión {plan['numero']} de 4 · {len(registros)} / 5",
                    guardadas=len(registros),estado=estado,instruccion=instruccion)
                if presentador.cierre_solicitado:break
            else:
                cv2.putText(frame,f'{len(registros)}/5',(10,30),cv2.FONT_HERSHEY_SIMPLEX,.5,(0,200,0),1)
                cv2.imshow('Captura CNN',frame)
                if cv2.waitKey(1)&255 in (27,ord('q')):break
        completa=len(registros)>=MIN_IMAGENES and not _evento_detener_camara.is_set() and not presentador.cierre_solicitado
        escribir_json_atomico(carpeta/'sesion.json',{**procedencia,'completa':completa,'imagenes':len(registros),
            'nota':'Captura supervisada CNN; no modifica embeddings ni verifica identidad humana automáticamente.'})
        return {'completado':completa,
            'subject':subject,'imagenes_guardadas':len(registros),'motor':'cnn','sesion':carpeta.name,
            'numero_sesion':plan['numero'],'respaldo':respaldo,
            'fps_video':frames/max(time.monotonic()-inicio,.001),'requiere_entrenamiento':True}
    finally:
        cerrar_camara(eventos=(_evento_detener_camara,),capturador=captura,nombre_ventana=None if presentador else 'Captura CNN')
        _bloqueo_camara.release()
