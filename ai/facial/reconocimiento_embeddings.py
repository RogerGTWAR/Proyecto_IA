"""Sesiones de cámara para embeddings; mantiene el contrato facial existente."""
pass

import json
import queue
import threading
import time
import uuid
from pathlib import Path

import cv2
import numpy as np

from surveillance.camara_utils import CamaraUltimoFrame, cerrar_camara, evento_cierre_opencv
from ai.facial.dataset_rostros import RUTA_DATASET
from ai.facial.pipeline_facial import (CALIBRACION, GALERIA, GaleriaEmbeddings, MotorEmbeddings,
                             PipelineFacial, cargar_configuracion, evaluar_calidad, sha256)
from ai.facial.rostros_empleados import asignar_etiqueta_empleado, obtener_cache_empleados_por_subject

INSTRUCCIONES = ("Mira al frente", "Gira ligeramente a la izquierda", "Gira ligeramente a la derecha",
                 "Mira un poco arriba", "Mira un poco abajo", "Aléjate un poco", "Acércate un poco y cambia la expresión")
MUESTRAS_CAPTURA = 15


def ultimo(cola, valor):
    try:
        cola.put_nowait(valor)
    except queue.Full:
        try:
            cola.get_nowait()
        except queue.Empty:
            pass
        try:
            cola.put_nowait(valor)
        except queue.Full:
            pass


def resultado_principal(resultados):
    # Nunca devuelve una identidad única para autenticación si hay varias caras.
    if not resultados:
        return {"estado":"SIN_ROSTRO","reconocido":False,"confianza":0.0}
    if len(resultados) != 1:
        return {"estado":"VARIOS_ROSTROS","reconocido":False,"confianza":0.0,"rostros":resultados}
    return resultados[0]


def dibujar(frame, resultados, debug=False):
    for r in resultados:
        x,y,w,h = r["caja"]
        color = (0,190,0) if r.get('reconocido') else (0,0,220) if r.get('estado')=='DESCONOCIDO' else (0,170,255) if r.get('estado') in ('VERIFICANDO','CALIDAD_ACEPTABLE') else (220,140,60)
        cv2.rectangle(frame,(x,y),(x+w,y+h),color,2)
        etiqueta = r.get("nombre") if r.get("reconocido") else r["estado"]
        from core.formato_numerico import format_score
        lineas = [str(etiqueta or 'VERIFICANDO')]
        if r.get('reconocido'):lineas.extend([('Score CNN: ' if r.get('motor')=='cnn' else 'Sim: ')+format_score(r.get('similitud')), 'RECONOCIDO'])
        elif r.get('similitud') is not None:lineas.append(('Score CNN: ' if r.get('motor')=='cnn' else 'Sim: ')+format_score(r['similitud']))
        # Si no queda espacio fuera del rostro, el panel muestra las etiquetas.
        base=y+h+18 if y+h+len(lineas)*20<frame.shape[0] else y-len(lineas)*20-5
        if base<15:continue
        for i,linea in enumerate(lineas):
            cv2.putText(frame,linea,(max(0,x),base+i*20),cv2.FONT_HERSHEY_SIMPLEX,.48,color,1)


def resumen_debug(r,comparacion=False):
    from core.formato_numerico import format_numero
    texto='Detector: YuNet · Embedding: SFace / '+str(r.get('embedding_estado') or 'sin evaluación')
    texto+='\nBlur: '+format_numero(r.get('blur'))+' · Umbral: '+(format_numero(r.get('threshold')) if r.get('threshold') is not None else 'Motor sin calibrar')
    texto+='\nCandidato: '+str(r.get('candidato') or r.get('mejor_candidato') or '—')+' · Similitud: '+format_numero(r.get('similitud'))+' · Segundo: '+format_numero(r.get('segunda_similitud'))+' · Margen: '+format_numero(r.get('margen'))
    texto+='\nDetector: '+format_numero(r.get('tiempo_deteccion_ms'))+' ms · Embedding: '+format_numero(r.get('tiempo_embedding_ms'))+' ms · Comparación: '+format_numero(r.get('tiempo_comparacion_ms'))+' ms'
    if comparacion:texto+='\nCNN candidato: '+str(r.get('cnn_candidato') or '—')+' · Score CNN: '+format_numero(r.get('cnn_score'))
    return texto


def reconocer_embeddings(callback_alerta=None,presentador=None,fuente=None,evaluador=None,detener_al_reconocer=False,comparar_cnn=False):
    # El lock/evento siguen siendo los mismos que utilizan los consumidores antiguos.
    from ai.facial.reconocimiento_cnn import _bloqueo_camara, _evento_detener_camara, ControlAlertaDesconocido
    if not _bloqueo_camara.acquire(blocking=False):
        raise RuntimeError("La cámara ya está siendo utilizada.")
    detener = threading.Event(); captura = None; worker = None
    entrada,salida = queue.Queue(maxsize=1),queue.Queue(maxsize=1)
    try:
        _evento_detener_camara.clear()
        if presentador is not None and presentador.cierre_solicitado:
            return resultado_principal([])
        cfg = cargar_configuracion()
        # El escáner siempre acumula evidencia; el diagnóstico básico no identifica.
        pipeline = PipelineFacial(cfg=cfg)
        cache = obtener_cache_empleados_por_subject()
        if not len(pipeline.galeria.vectores):raise RuntimeError('Base facial no cargada. Regenera la base desde las imágenes existentes.')
        if pipeline.politica is None:raise RuntimeError('Motor sin calibrar. Ejecuta Calibrar motores antes de abrir el escáner.')
        if not any(str(s) in cache and cache[str(s)].get('empleado_activo') for s in pipeline.galeria.subjects):raise RuntimeError('La base facial no tiene empleados activos vinculados en SQL Server.')
        from core.eventos_servicios import informar_estado_componente
        informar_estado_componente('SFace Empleados',True,'Motor facial disponible.')
        if comparar_cnn:
            from ai.facial import reconocimiento_cnn as cnn
            _,clases_cnn,inferencia_cnn=cnn._cargar_recursos()
            detector_cnn=cnn._detector_rostros()
        captura = CamaraUltimoFrame(cfg["fuente_video"] if fuente is None else fuente,cfg["resolucion"]).iniciar()
        informar_estado_componente('Cámara Empleados',True,'Captura iniciada.')
        def inferir():
            nonlocal cache
            try:
                print(f"Empleados registrados encontrados: {len(cache)} | Embeddings cargados: {len(pipeline.galeria.vectores)}", flush=True)
                for s in np.unique(pipeline.galeria.subjects):
                    print(f"{cache.get(str(s), {}).get('nombre', str(s))}: {int(np.sum(pipeline.galeria.subjects == s))} embeddings", flush=True)
                if not len(pipeline.galeria.vectores):
                    raise RuntimeError("Base facial vacía. Usa REGENERAR BASE FACIAL o registra los rostros nuevamente porque cambió el modelo facial.")
                proximo_sql = time.monotonic()+5
                alertas = {}
                sesion_alertas=uuid.uuid4().hex
                notificaciones={}
                vueltas=0;datos_cnn={};inicio_inferencia=time.perf_counter()
                while not detener.is_set():
                    try:
                        numero,frame,tomado = entrada.get(timeout=.1)
                    except queue.Empty:
                        continue
                    if time.monotonic()>=proximo_sql:
                        # Nunca mantiene autorización cuando falla la actualización SQL.
                        try:cache = obtener_cache_empleados_por_subject()
                        except Exception:cache={}
                        proximo_sql = time.monotonic()+5
                    from surveillance.identidad_vigilancia import procesar_frame_empleados
                    resultados = procesar_frame_empleados(pipeline,frame,cache)
                    vueltas+=1
                    for r in resultados:r['fps_inferencia']=vueltas/max(time.perf_counter()-inicio_inferencia,.001)
                    if comparar_cnn and (vueltas==1 or vueltas%cfg.get('cnn_interval_frames',3)==0):
                        _,entrada_cnn,_,_,_=cnn._detectar_y_recortar(frame,detector_cnn)
                        datos_cnn={}
                        if entrada_cnn is not None:
                            scores=inferencia_cnn(entrada_cnn[None,...])[0];indice=int(np.argmax(scores))
                            datos_cnn={'cnn_candidato':clases_cnn.get(indice),'cnn_score':float(scores[indice])}
                    if comparar_cnn:
                        for r in resultados:r.update(datos_cnn)
                    if detener.is_set():
                        break
                    if time.monotonic()-tomado>cfg["ttl_identidad_s"]:
                        for r in resultados:
                            r.update(estado="RESULTADO_TARDIO", reconocido=False, etiqueta=None, nombre=None)
                    for r in resultados:
                        track=r['track_id']
                        if r.get('reconocido') and r.get('id_empleado'):
                            from core.eventos_servicios import publicar_reconocimiento_empleado as notificar_reconocimiento_empleado
                            clave=(track,r['id_empleado'])
                            if clave not in notificaciones:
                                aviso=notificar_reconocimiento_empleado(r,frame,
                                    referencia='facial_empleados:'+sesion_alertas+':'+str(track)+':'+str(r['id_empleado']))
                                if aviso:notificaciones[clave]=aviso['id_evento']
                            if clave in notificaciones:r['telegram_referencia']=notificaciones[clave]
                        if r["track_id"] not in alertas:
                            # Solo notificación; se conserva el consenso y la calidad SFace.
                            alertas[r["track_id"]] = ControlAlertaDesconocido(registrar=lambda: {'estado':'PENDIENTE'})
                        estado_alerta=r['estado'] if r['estado']=='DESCONOCIDO' and r.get('calidad_estado') in ('CALIDAD_OK','CALIDAD_ACEPTABLE') else 'VERIFICANDO'
                        alerta = alertas[r["track_id"]].procesar(estado_alerta)
                        if alerta:
                            from core.eventos_servicios import publicar_rostro_desconocido as notificar_rostro_desconocido
                            alerta=notificar_rostro_desconocido(r,frame,referencia='facial:'+sesion_alertas+':'+str(r['track_id']))
                        if alerta and callback_alerta:
                            callback_alerta(alerta)
                        if alerta:notificaciones[(track,None)]=alerta['id_evento']
                        if not r.get('reconocido') and (track,None) in notificaciones:
                            r['telegram_referencia']=notificaciones[(track,None)]
                        r["threshold"] = pipeline.politica["threshold"] if pipeline.politica else None
                        if evaluador is not None:
                            evaluador(r)
                    activos = set(pipeline.tracker.tracks)
                    alertas = {i:a for i,a in alertas.items() if i in activos}
                    ultimo(salida,(numero,resultados,tomado,vueltas/max(time.perf_counter()-inicio_inferencia,.001)))
            except Exception as error:
                ultimo(salida,error)
        worker = threading.Thread(target=inferir,name="facial-inferencia",daemon=True)
        worker.start()
        numero_anterior=-1; resultados=[]; mostrado=resultado_principal([]);fps_worker=0.0
        publicado=0.0; inicio=time.perf_counter(); frames=0; ventana_creada=False
        while not _evento_detener_camara.is_set():
            if presentador is not None and presentador.cierre_solicitado:
                break
            numero,frame = captura.leer()
            if captura.error:
                raise captura.error
            if frame is None or numero==numero_anterior:
                if not presentador and evento_cierre_opencv("Reconocimiento facial",_evento_detener_camara,ventana_creada):
                    break
                detener.wait(.005)
                continue
            numero_anterior=numero; frames+=1
            ultimo(entrada,(numero,frame.copy(),time.monotonic()))
            try:
                dato=salida.get_nowait()
                if isinstance(dato,Exception):
                    raise dato
                _,resultados,publicado,fps_worker=dato
            except queue.Empty:
                pass
            # No muestra ni devuelve una identificación vieja si el worker se retrasa.
            if time.monotonic()-publicado>cfg["ttl_identidad_s"]:
                resultados=[]
            mostrado=resultado_principal(resultados)
            if detener_al_reconocer and mostrado.get("reconocido"):
                return mostrado
            vista=frame.copy()
            dibujar(vista,resultados,cfg["debug"])
            fps=frames/max(time.perf_counter()-inicio,.001)
            mostrado.update(fps_video=fps,fps_inferencia=fps_worker)
            if presentador:
                from core.formato_numerico import format_numero
                from integrations.telegram.telegram_service import texto_estado_entrega
                presentador.publicar_frame(vista)
                presentador.publicar_info(persona=mostrado.get("nombre") or "-",codigo=mostrado.get("codigo_empleado") or "-",
                    cargo=mostrado.get("cargo") or "-",confianza=format_numero(mostrado.get('similitud')),
                    estado=mostrado["estado"],distancia=mostrado.get("distancia","-"),
                    telegram=texto_estado_entrega(mostrado.get('telegram_referencia')),
                    detalle=mostrado.get('calidad_estado','Sin rostro evaluado'),
                    metricas='Video '+format_numero(fps)+' FPS / Procesamiento '+format_numero(fps_worker)+' FPS · '+('Comparación técnica' if comparar_cnn else 'YuNet / SFace'),
                    debug=resumen_debug(mostrado,comparar_cnn))
            else:
                from ui.ventanas_camara import redimensionar_con_aspecto
                cv2.imshow("Reconocimiento facial",redimensionar_con_aspecto(vista,1280,720)); ventana_creada=True
                if evento_cierre_opencv("Reconocimiento facial",_evento_detener_camara):
                    break
        return mostrado
    except Exception as error:
        from core.eventos_servicios import informar_estado_componente
        from integrations.telegram.telegram_service import _error_seguro
        componente='Cámara Empleados' if captura is not None and captura.error else 'SFace Empleados'
        informar_estado_componente(componente,False,'El reconocimiento se interrumpió. '+_error_seguro(error))
        raise
    finally:
        cerrar_camara(eventos=(_evento_detener_camara,detener),capturador=captura,workers=(worker,),
                      nombre_ventana=None if presentador else "Reconocimiento facial")
        if captura is not None:
            from core.system_state import state_manager
            if state_manager.get('CAMARA').status!='ERROR':
                state_manager.update('CAMARA','OFFLINE','Captura facial cerrada.',activity='IDLE',expected=True)
        _bloqueo_camara.release()


def registrar_embeddings(id_empleado,presentador=None):
    from ai.facial.reconocimiento_cnn import _bloqueo_camara,_evento_detener_camara
    if not _bloqueo_camara.acquire(blocking=False):
        raise RuntimeError("La cámara ya está siendo utilizada.")
    captura=None; carpeta=None; completado=False
    try:
        _evento_detener_camara.clear()
        if presentador is not None and presentador.cierre_solicitado:
            return {"completado":False,"subject":None,"imagenes_guardadas":0,"fps_video":0}
        cfg=cargar_configuracion(); motor=MotorEmbeddings(cfg); galeria=GaleriaEmbeddings()
        completa=GALERIA.parent/'base_muestras.npz'
        if completa.is_file():
            base=GaleriaEmbeddings(completa)
            if set(map(str,galeria.archivos)).issubset(set(map(str,base.archivos))):
                base.ruta=GALERIA;galeria=base
        cache=obtener_cache_empleados_por_subject()
        existente=next((s for s,e in cache.items() if e["id_empleado"]==int(id_empleado)),None)
        if existente:
            subject=existente
        else:
            from ai.facial.captura_rostros import obtener_siguiente_subject
            subject=obtener_siguiente_subject()
            ocupados=set(cache)|set(galeria.subjects)
            while subject in ocupados:
                subject=f"subject{int(subject[7:])+1:02d}"
        carpeta=GALERIA.parent/"muestras"/subject/uuid.uuid4().hex
        carpeta.mkdir(parents=True,exist_ok=False)
        captura=CamaraUltimoFrame(cfg["fuente_video"],cfg["resolucion"]).iniciar()
        vectores=[]; archivos=[]; etapas=[]; metadatos=[]
        ultimo_numero=-1; ultima_muestra=0.0; inicio=time.monotonic(); frames=0; ventana_creada=False
        estado="Buscando un solo rostro..."
        while len(vectores)<MUESTRAS_CAPTURA and time.monotonic()-inicio<180 and not _evento_detener_camara.is_set():
            if presentador and presentador.cierre_solicitado:
                break
            numero,frame=captura.leer()
            if captura.error:
                raise captura.error
            if frame is None or numero==ultimo_numero:
                time.sleep(.005)
                continue
            ultimo_numero=numero; frames+=1
            etapa=min(6,len(vectores)//2)
            if time.monotonic()-ultima_muestra>=.6:
                caras=motor.detectar(frame)
                estado="Buscando un solo rostro..." if len(caras)!=1 else "Verificando calidad..."
                if len(caras)==1:
                    cara=caras[0]; calidad=evaluar_calidad(frame,cara,cfg,max(112,cfg["min_rostro"]))
                    estado=calidad["estado"]
                    if calidad["valida"]:
                        vector,alineado=motor.extraer(frame,cara)
                        # Comparar con TODAS las muestras, no solo la anterior.
                        from ai.facial.pipeline_facial import cargar_politica
                        politica=cargar_politica(galeria,cfg)
                        if vectores and politica and float(np.mean(sorted(float(v@vector) for v in vectores)[-3:]))<politica['threshold']:
                            raise RuntimeError("El rostro cambió durante el registro. Reinicia la captura supervisada del empleado.")
                        repetida=bool(vectores and max(float(v@vector) for v in vectores)>.995)
                        if repetida:
                            estado="Cambia ángulo, expresión o distancia; muestra repetida"
                        else:
                            archivo=carpeta/f"{subject}.capture{len(vectores)+1:03d}.png"
                            if not cv2.imwrite(str(archivo),alineado):
                                raise OSError("No se pudo guardar la muestra facial.")
                            original=carpeta/f"original_{len(vectores)+1:03d}.png"
                            if not cv2.imwrite(str(original),frame):
                                raise OSError('No se pudo conservar el original para regeneración.')
                            vectores.append(vector); archivos.append("sha256:"+sha256(archivo)); etapas.append(etapa)
                            metadatos.append({"archivo":archivo.name,"original":original.name,"etapa":INSTRUCCIONES[etapa],"calidad":calidad})
                            ultima_muestra=time.monotonic(); estado="Muestra guardada"
                    x,y,w,h=map(int,cara[:4]); cv2.rectangle(frame,(x,y),(x+w,y+h),(0,190,0),2)
            if presentador:
                presentador.publicar_frame(frame)
                presentador.publicar_info(contador=f"{len(vectores)} / {MUESTRAS_CAPTURA}",estado=estado,instruccion=INSTRUCCIONES[etapa])
            else:
                cv2.putText(frame,f"{len(vectores)}/{MUESTRAS_CAPTURA} | {INSTRUCCIONES[etapa]} | {estado}",(10,30),cv2.FONT_HERSHEY_SIMPLEX,.5,(0,255,0),1)
                from ui.ventanas_camara import redimensionar_con_aspecto
                cv2.imshow("Registro facial",redimensionar_con_aspecto(frame,1280,720)); ventana_creada=True
                if evento_cierre_opencv("Registro facial",_evento_detener_camara):
                    _evento_detener_camara.set(); break
        completado=(not _evento_detener_camara.is_set() and len(vectores)>=MUESTRAS_CAPTURA and len(set(etapas))==7)
        if completado:
            # Preparación local primero; relación SQL existente sigue siendo la autoridad.
            galeria.agregar(subject,int(id_empleado),vectores,archivos)
            staging=carpeta/"galeria_pendiente.npz"
            destino=galeria.ruta; galeria.ruta=staging; galeria.guardar()
            asignar_etiqueta_empleado(id_empleado,subject)
            staging.replace(destino)
            (carpeta/"registro.json").write_text(json.dumps(metadatos,ensure_ascii=False,indent=2),encoding="utf-8")
            # Las mismas capturas permanecen disponibles para comparar la CNN histórica.
            RUTA_DATASET.mkdir(parents=True,exist_ok=True)
            for archivo in carpeta.glob(f"{subject}.capture*.png"):
                imagen=cv2.imread(str(archivo),cv2.IMREAD_GRAYSCALE)
                nombre=f"{subject}.capture{carpeta.name}.{archivo.stem.split('capture')[-1]}.png"
                cv2.imwrite(str(RUTA_DATASET/nombre),cv2.resize(imagen,(100,100),interpolation=cv2.INTER_AREA))
        return {"completado":completado,"subject":subject if completado else None,
                "imagenes_guardadas":len(vectores),"fps_video":frames/max(time.monotonic()-inicio,.001),
                "motor":"embeddings","requiere_calibracion":completado}
    finally:
        cerrar_camara(eventos=(_evento_detener_camara,),capturador=captura,
                      nombre_ventana=None if presentador else "Registro facial")
        # Conserva capturas parciales para diagnóstico; nunca elimina registros históricos.
        _bloqueo_camara.release()
