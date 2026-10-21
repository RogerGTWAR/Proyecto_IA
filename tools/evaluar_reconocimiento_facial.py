
import sys
from pathlib import Path as _RutaProyecto
_RAIZ_PROYECTO = _RutaProyecto(__file__).resolve().parents[1]
if str(_RAIZ_PROYECTO) not in sys.path:
    sys.path.insert(0, str(_RAIZ_PROYECTO))

from ai.facial.pipeline_facial import escribir_json_atomico
"""Instalación, evaluación abierta y calibración reproducible de datos reales.
CSV: archivo,identidad_real,distancia_m,subset (calibracion/prueba),sesion.
Identidad real: subjectXX registrado o DESCONOCIDO. Metros medidos manualmente.
"""
pass

import argparse
import csv
import json
import math
import time
import urllib.request
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

from ai.facial.pipeline_facial import (BASE_DIR,CALIBRACION,DIRECTORIO,GALERIA,MODELOS,VERSION_PIPELINE,
                             GaleriaEmbeddings,MotorEmbeddings,cargar_configuracion,cargar_politica,
                             escribir_json_atomico,evaluar_calidad,firma_configuracion,sha256)

CAMPOS = ("archivo","subset","sesion","distancia_m","identidad_real","candidato","similitud","margen",
          "identidad_predicha","estado","correcto","apto_identificar","resolucion","ancho_rostro","alto_rostro",
          "blur","iluminacion","roll","yaw","visible","calidad","calidad_estado","tiempo_inferencia_ms","fps_inferencia")


def instalar_modelos():
    DIRECTORIO.mkdir(parents=True,exist_ok=True)
    for rol,(nombre,digest) in MODELOS.items():
        destino=DIRECTORIO/nombre
        if destino.is_file() and sha256(destino)==digest:
            print(f"Verificado: {nombre}"); continue
        carpeta="face_detection_yunet" if rol=="detector" else "face_recognition_sface"
        url=f"https://media.githubusercontent.com/media/opencv/opencv_zoo/main/models/{carpeta}/{nombre}"
        temporal=destino.with_suffix(".download")
        try:
            with urllib.request.urlopen(url,timeout=30) as remoto,temporal.open("wb") as archivo:
                while True:
                    bloque=remoto.read(1024*1024)
                    if not bloque: break
                    archivo.write(bloque)
            if sha256(temporal)!=digest:
                raise RuntimeError(f"SHA-256 inválido: {nombre}. No se instaló.")
            temporal.replace(destino)
            print(f"Instalado y verificado: {nombre}")
        finally:
            if temporal.exists(): temporal.unlink()


def cargar_imagen(ruta):
    with Image.open(ruta) as imagen:
        return cv2.cvtColor(np.asarray(imagen.convert("RGB")),cv2.COLOR_RGB2BGR)


def analizar_manifest(ruta, motor, galeria, cfg):
    ruta=Path(ruta).resolve()
    filas=[]; hashes=set(); sesiones={}; identidades=set(map(str,galeria.subjects))
    with ruta.open(encoding="utf-8-sig",newline="") as archivo:
        for entrada in csv.DictReader(archivo):
            origen=(ruta.parent/entrada["archivo"]).resolve()
            digest=sha256(origen)
            if digest in hashes or "sha256:"+digest in set(galeria.archivos):
                raise ValueError(f"Imagen duplicada o usada en registro: {entrada['archivo']}")
            hashes.add(digest)
            subset=entrada.get("subset","")
            if subset not in {"calibracion","prueba"}:
                raise ValueError("Cada imagen necesita subset calibracion o prueba.")
            sesion=entrada.get("sesion","").strip()
            if not sesion:
                raise ValueError("Indique una sesión independiente para cada captura de evaluación.")
            sesiones.setdefault(sesion,set()).add(subset)
            real=entrada["identidad_real"].strip()
            if real not in identidades and real!="DESCONOCIDO":
                raise ValueError(f"Identidad no inscrita: {real}. Para personas no registradas use DESCONOCIDO.")
            distancia=entrada.get("distancia_m","")
            if distancia and (not math.isfinite(float(distancia)) or float(distancia)<=0):
                raise ValueError("Distancia manual inválida.")
            frame=cargar_imagen(origen); inicio=time.perf_counter()
            caras=motor.detectar(frame,exhaustivo=True)
            fila={**entrada,"resolucion":f"{frame.shape[1]}x{frame.shape[0]}",
                  "candidato":None,"similitud":0.0,"margen":0.0,"identidad_predicha":"DESCONOCIDO",
                  "estado":"SIN_ROSTRO" if not caras else "VARIOS_ROSTROS"}
            if len(caras)==1:
                calidad=evaluar_calidad(frame,caras[0],cfg,minimo=32)
                fila.update(calidad); fila["calidad_estado"]=calidad["estado"]
                if calidad["valida"]:
                    vector,_=motor.extraer(frame,caras[0])
                    # Una captura casi idéntica a la galería no es evidencia independiente.
                    if len(galeria.vectores) and float(np.max(galeria.vectores@vector))>.99999:
                        raise ValueError(f"Posible fuga de datos: {entrada['archivo']} coincide con una muestra de registro.")
                    candidato,score,margen=galeria.comparar(vector)
                    fila.update(candidato=candidato,similitud=score,margen=margen,estado="SIN_CALIBRAR")
            fila["tiempo_inferencia_ms"]=(time.perf_counter()-inicio)*1000
            fila["fps_inferencia"]=1000/max(fila["tiempo_inferencia_ms"],.001)
            filas.append(fila)
    if any(len(partes)>1 for partes in sesiones.values()):
        raise ValueError("Una sesión no puede aparecer en calibración y prueba: evita fuga temporal.")
    return filas


def aplicar_politica(filas, politica):
    salida=[]
    for original in filas:
        fila=dict(original); predicha="DESCONOCIDO"
        valida=(fila.get("calidad_estado")=="CALIDAD_OK" and
                min(float(fila.get("ancho_rostro",0)),float(fila.get("alto_rostro",0)))>=politica["min_rostro"])
        if valida and fila.get("candidato") and fila["similitud"]>=politica["threshold"] and fila["margen"]>=politica["margen"]:
            predicha=fila["candidato"]
        fila.update(identidad_predicha=predicha,correcto=predicha==fila["identidad_real"],apto_identificar=valida,
                    estado="RECONOCIDO" if predicha!="DESCONOCIDO" else fila.get("calidad_estado") if not valida else "DESCONOCIDO")
        salida.append(fila)
    return salida


def metricas(filas):
    if not filas:
        return {"muestras":0}
    conocidas=[f for f in filas if f["identidad_real"]!="DESCONOCIDO"]
    desconocidas=[f for f in filas if f["identidad_real"]=="DESCONOCIDO"]
    aceptadas=[f for f in filas if f["identidad_predicha"]!="DESCONOCIDO"]
    correctas=sum(f["identidad_real"]==f["identidad_predicha"] for f in conocidas)
    falsos=sum(f["identidad_real"]!=f["identidad_predicha"] for f in aceptadas)
    fa=sum(f["identidad_predicha"]!="DESCONOCIDO" for f in desconocidas)
    fr=sum(f["identidad_predicha"]=="DESCONOCIDO" for f in conocidas)
    aptos=[f for f in desconocidas if f.get("apto_identificar")]
    precision=correctas/len(aceptadas) if aceptadas else 0
    recall=correctas/len(conocidas) if conocidas else 0
    etiquetas=sorted({f["identidad_real"] for f in filas}|{f["identidad_predicha"] for f in filas})
    matriz=[[sum(f["identidad_real"]==real and f["identidad_predicha"]==pred for f in filas) for pred in etiquetas] for real in etiquetas]
    promedio=float(np.mean([f["tiempo_inferencia_ms"] for f in filas]))
    return {"muestras":len(filas),"conocidos":len(conocidas),"desconocidos":len(desconocidas),
            "precision":precision,"recall":recall,"f1":2*precision*recall/(precision+recall) if precision+recall else 0,
            "accuracy":sum(f["identidad_real"]==f["identidad_predicha"] for f in filas)/len(filas),
            "far_desconocidos":fa/len(desconocidas) if desconocidas else None,
            "far_desconocidos_aptos":sum(f["identidad_predicha"]!="DESCONOCIDO" for f in aptos)/len(aptos) if aptos else None,
            "frr_conocidos":fr/len(conocidas) if conocidas else None,
            "identificaciones_incorrectas":falsos,
            "tasa_identidad_incorrecta_conocidos":sum(f["identidad_predicha"] not in {"DESCONOCIDO",f["identidad_real"]} for f in conocidas)/len(conocidas) if conocidas else None,
            "far_limite_superior_95_cero_errores":1-.05**(1/len(desconocidas)) if desconocidas and fa==0 else None,
            "etiquetas_matriz":etiquetas,"matriz_confusion":matriz,
            "inferencia_ms_promedio":promedio,"fps_inferencia_secuencial":1000/max(promedio,.001)}


def calibrar(filas, galeria, cfg, objetivo_far=0.0, recall_minimo=.5):
    desarrollo=[f for f in filas if f["subset"]=="calibracion"]
    prueba=[f for f in filas if f["subset"]=="prueba"]
    for nombre,grupo in (("calibracion",desarrollo),("prueba",prueba)):
        if sum(f["identidad_real"]=="DESCONOCIDO" for f in grupo)<20 or sum(f["identidad_real"]!="DESCONOCIDO" for f in grupo)<20:
            raise ValueError(f"{nombre}: se requieren al menos 20 imágenes conocidas y 20 desconocidas independientes.")
        if sum(f["identidad_real"]=="DESCONOCIDO" and f.get("calidad_estado")=="CALIDAD_OK" and f.get("candidato") is not None for f in grupo)<20:
            raise ValueError(f"{nombre}: faltan 20 rostros desconocidos utilizables; imágenes vacías no validan rechazo facial.")
        if set(map(str,galeria.subjects))-set(f["identidad_real"] for f in grupo):
            raise ValueError(f"{nombre}: faltan empleados de la galería. Evalúe todos antes de activar aceptación.")
    scores=sorted(set(f["similitud"] for f in desarrollo if f.get("candidato")))
    if not scores:
        raise ValueError("No hay rostros utilizables para calibrar.")
    thresholds=sorted(set([float(np.nextafter(s,np.inf)) for s in scores]+[min(scores)]))
    margenes=sorted(set([0.0]+[float(np.nextafter(f["margen"],np.inf)) for f in desarrollo if f.get("candidato") and f["margen"]<=.5]))
    # Cuadrícula acotada; thresholds se derivan de scores observados, no de softmax.
    if len(thresholds)>100:
        thresholds=[thresholds[i] for i in np.linspace(0,len(thresholds)-1,100,dtype=int)]
    if len(margenes)>30:
        margenes=[margenes[i] for i in np.linspace(0,len(margenes)-1,30,dtype=int)]
    mejores=[]
    for minimo in (64,80,96,112):
        desconocidos_aptos=[f for f in desarrollo if f["identidad_real"]=="DESCONOCIDO" and
                           f.get("calidad_estado")=="CALIDAD_OK" and f.get("candidato") is not None and
                           min(f.get("ancho_rostro",0),f.get("alto_rostro",0))>=minimo]
        if len(desconocidos_aptos)<20:
            continue
        for umbral in thresholds:
            for margen in margenes:
                p={"threshold":umbral,"margen":margen,"min_rostro":minimo}
                m=metricas(aplicar_politica(desarrollo,p))
                if m["far_desconocidos"]<=objetivo_far and m["identificaciones_incorrectas"]==0 and m["recall"]>=recall_minimo:
                    mejores.append((m["recall"],umbral,margen,-minimo,p,m))
    if not mejores:
        raise ValueError("No se obtuvo una política segura con recall suficiente. Mejore cámara, muestras o iluminación.")
    _,_,_,_,politica,m=max(mejores,key=lambda v:v[:4])
    pruebas_aptas=[f for f in prueba if f["identidad_real"]=="DESCONOCIDO" and
                  f.get("calidad_estado")=="CALIDAD_OK" and f.get("candidato") is not None and
                  min(f.get("ancho_rostro",0),f.get("alto_rostro",0))>=politica["min_rostro"]]
    if len(pruebas_aptas)<20:
        raise ValueError("Faltan 20 desconocidos de prueba aptos para el tamaño operativo elegido.")
    validacion=metricas(aplicar_politica(prueba,politica))
    if validacion["far_desconocidos"]>objetivo_far or validacion["identificaciones_incorrectas"] or validacion["recall"]<recall_minimo:
        raise ValueError("La política no pasó la sesión independiente de prueba; no se activó.")
    return {**politica,"calibrada":True,"pipeline":VERSION_PIPELINE,"galeria_sha256":galeria.firma,
            "config_sha256":firma_configuracion(cfg),"objetivo_far":objetivo_far,
            "calibracion":m,"validacion_independiente":validacion,
            "nota":"Métricas por imagen; la política temporal se evalúa separadamente en video. FAR observado no garantiza FAR poblacional."}


def guardar_resultados(filas, destino):
    destino=Path(destino); destino.parent.mkdir(parents=True,exist_ok=True)
    with destino.open("w",encoding="utf-8-sig",newline="") as archivo:
        escritor=csv.DictWriter(archivo,fieldnames=CAMPOS,extrasaction="ignore")
        escritor.writeheader(); escritor.writerows(filas)
    resumen=metricas(filas)
    resumen["por_distancia_manual"]={d:metricas([f for f in filas if f.get("distancia_m","")==d]) for d in sorted(set(f.get("distancia_m","") for f in filas))}
    escribir_json_atomico(destino.with_suffix(".metricas.json"),resumen)
    print(json.dumps(resumen,ensure_ascii=False,indent=2))


def evaluar_video(fuente, real, distancia, destino, galeria, cfg):
    from surveillance.camara_utils import CamaraUltimoFrame
    from ai.facial.pipeline_facial import PipelineFacial
    from ai.facial.reconocimiento_embeddings import dibujar, resultado_principal
    from ui.ventanas_camara import redimensionar_con_aspecto
    pipeline=PipelineFacial(galeria=galeria,cfg=cfg)
    captura=CamaraUltimoFrame(fuente,cfg["resolucion"]).iniciar()
    filas=[]; anterior=-1; inicio=time.monotonic(); analizados=0
    try:
        while True:
            numero,frame=captura.leer()
            if captura.error:
                break
            if frame is None or numero==anterior:
                time.sleep(.005); continue
            anterior=numero; analizados+=1
            marca_inferencia=time.perf_counter()
            resultados=pipeline.procesar(frame)
            duracion_ms=(time.perf_counter()-marca_inferencia)*1000
            principal=resultado_principal(resultados)
            if len(resultados)<=1:
                fila={**principal,"archivo":f"frame:{numero}","identidad_real":real,
                      "identidad_predicha":principal.get("etiqueta") if principal.get("reconocido") else "DESCONOCIDO",
                      "distancia_m":distancia,"subset":"prueba","sesion":"video"}
                fila["tiempo_inferencia_ms"]=duracion_ms
                filas.append(fila)
            vista=frame.copy(); dibujar(vista,resultados,True)
            cv2.imshow("Evaluacion facial - Q termina",redimensionar_con_aspecto(vista,1280,720))
            if cv2.waitKey(1)&255 in (27,ord("q")):
                break
    finally:
        captura.cerrar(); cv2.destroyAllWindows()
    guardar_resultados(filas,destino)
    print(f"FPS procesados reales: {analizados/max(time.monotonic()-inicio,.001):.2f}")
    print("Los frames de video están correlacionados; no use su cantidad como tamaño de muestra independiente para FAR.")


def benchmark_imagen(ruta, salida):
    """Ensayo de degradación sobre una imagen real; no mide accuracy ni metros."""
    cfg=cargar_configuracion(); motor=MotorEmbeddings(cfg)
    frame=cargar_imagen(ruta); caras=motor.detectar(frame,exhaustivo=True)
    if len(caras)!=1:
        raise ValueError("El benchmark requiere una imagen con un solo rostro detectado.")
    referencia,_=motor.extraer(frame,caras[0]); ancho=float(caras[0][2])
    filas=[]
    for objetivo in (32,48,64,80,96,112,160):
        escala=min(1.0,objetivo/ancho)
        reducido=cv2.resize(frame,(max(32,round(frame.shape[1]*escala)),max(32,round(frame.shape[0]*escala))),interpolation=cv2.INTER_AREA)
        inicio=time.perf_counter(); caras_test=motor.detectar(reducido,exhaustivo=True)
        fila={"ancho_objetivo":objetivo,"resolucion":f"{reducido.shape[1]}x{reducido.shape[0]}","detectado":len(caras_test)==1}
        if len(caras_test)==1:
            calidad=evaluar_calidad(reducido,caras_test[0],cfg,minimo=32)
            fila.update(calidad)
            if calidad["valida"]:
                vector,_=motor.extraer(reducido,caras_test[0])
                fila["similitud_misma_imagen_original"]=float(vector@referencia)
        fila["inferencia_ms"]=(time.perf_counter()-inicio)*1000
        filas.append(fila)
    escribir_json_atomico(salida,{"imagen":str(ruta),"tipo":"degradacion_de_una_imagen_no_validacion_de_identidad",
                                   "resultados":filas,"nota":"No equivale a distancia física ni prueba de cámara; no activa calibración."})
    print(json.dumps(filas,ensure_ascii=False,indent=2))


def capturar_pruebas(args):
    """Recolecta frames originales etiquetados por el operador, sin crear empleados."""
    from surveillance.camara_utils import CamaraUltimoFrame
    from ui.ventanas_camara import redimensionar_con_aspecto
    cfg=cargar_configuracion(); motor=MotorEmbeddings(cfg); galeria=GaleriaEmbeddings()
    if args.identidad_real not in set(galeria.subjects) and args.identidad_real!="DESCONOCIDO":
        raise ValueError("Use el subject inscrito del empleado o DESCONOCIDO.")
    if args.distancia_m<=0 or args.muestras<1 or not args.sesion.strip():
        raise ValueError("Sesión, distancia o cantidad inválida.")
    manifest=Path(args.manifest).resolve(); manifest.parent.mkdir(parents=True,exist_ok=True)
    import uuid
    carpeta=manifest.parent/"capturas"/uuid.uuid4().hex
    carpeta.mkdir(parents=True)
    captura=CamaraUltimoFrame(cfg["fuente_video"],cfg["resolucion"]).iniciar()
    filas=[]; anterior=-1; ultima=0.0; inicio=time.monotonic()
    try:
        while len(filas)<args.muestras and time.monotonic()-inicio<args.muestras*5+30:
            numero,frame=captura.leer()
            if captura.error: raise captura.error
            if frame is None or numero==anterior:
                time.sleep(.005); continue
            anterior=numero
            if time.monotonic()-ultima>=1.0:
                caras=motor.detectar(frame,exhaustivo=True)
                if len(caras)<=1:
                    destino=carpeta/f"{len(filas)+1:04d}.png"
                    if not cv2.imwrite(str(destino),frame):
                        raise OSError("No se pudo guardar un frame de evaluación.")
                    filas.append({"archivo":destino.relative_to(manifest.parent).as_posix(),
                        "identidad_real":args.identidad_real,"distancia_m":args.distancia_m,
                        "subset":args.subset,"sesion":args.sesion})
                    ultima=time.monotonic()
            vista=redimensionar_con_aspecto(frame.copy(),1280,720)
            cv2.putText(vista,f"{len(filas)}/{args.muestras} | {args.identidad_real} | {args.distancia_m} m MEDIDOS | Q termina",
                        (15,25),cv2.FONT_HERSHEY_SIMPLEX,.55,(0,255,0),2)
            cv2.imshow("Capturas de evaluacion",vista)
            if cv2.waitKey(1)&255 in (27,ord("q")): break
    finally:
        captura.cerrar(); cv2.destroyAllWindows()
        existe=manifest.exists() and manifest.stat().st_size>0
        with manifest.open("a",encoding="utf-8",newline="") as archivo:
            escritor=csv.DictWriter(archivo,fieldnames=("archivo","identidad_real","distancia_m","subset","sesion"))
            if not existe: escritor.writeheader()
            escritor.writerows(filas)
    print(f"Guardadas {len(filas)} capturas en {manifest}; cambia expresión, posición, iluminación y sesión.")


def instalar_calibracion(politica):
    escribir_json_atomico(CALIBRACION, politica)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    sub=parser.add_subparsers(dest="comando",required=True)
    sub.add_parser("instalar-modelos")
    sub.add_parser("estado")
    p=sub.add_parser("capturar-pruebas"); p.add_argument("manifest"); p.add_argument("--identidad-real",required=True)
    p.add_argument("--distancia-m",type=float,required=True); p.add_argument("--subset",choices=("calibracion","prueba"),required=True)
    p.add_argument("--sesion",required=True); p.add_argument("--muestras",type=int,default=20)
    p=sub.add_parser("benchmark"); p.add_argument("imagen"); p.add_argument("--salida",default="evaluacion_facial/benchmark.json")
    for comando in ("evaluar","calibrar"):
        p=sub.add_parser(comando); p.add_argument("manifest"); p.add_argument("--salida",default=f"evaluacion_facial/{comando}.csv")
        if comando=="calibrar":
            p.add_argument("--objetivo-far",type=float,default=0.0)
            p.add_argument("--recall-minimo",type=float,default=.5)
    p=sub.add_parser("video"); p.add_argument("--fuente",default=None); p.add_argument("--identidad-real",required=True)
    p.add_argument("--distancia-m",type=float,required=True); p.add_argument("--salida",default="evaluacion_facial/video.csv")
    args=parser.parse_args()
    if args.comando in {"calibrar", "instalar-modelos", "capturar-pruebas"}:
        pass
    if args.comando=="instalar-modelos":
        instalar_modelos(); return
    if args.comando=="capturar-pruebas":
        capturar_pruebas(args); return
    if args.comando=="benchmark":
        benchmark_imagen(args.imagen,args.salida); return
    cfg=cargar_configuracion(); galeria=GaleriaEmbeddings()
    if args.comando=="estado":
        print(json.dumps({"modelos":{r:(DIRECTORIO/n).is_file() for r,(n,_) in MODELOS.items()},
                          "muestras":len(galeria.vectores),"subjects":list(map(str,np.unique(galeria.subjects))),
                          "calibrada":cargar_politica(galeria,cfg) is not None},indent=2)); return
    if args.comando=="video":
        fuente=args.fuente if args.fuente is not None else cfg["fuente_video"]
        if isinstance(fuente,str) and fuente.isdigit(): fuente=int(fuente)
        if args.identidad_real not in set(galeria.subjects) and args.identidad_real!="DESCONOCIDO":
            raise ValueError("Use un subject inscrito o DESCONOCIDO.")
        evaluar_video(fuente,args.identidad_real,args.distancia_m,args.salida,galeria,cfg); return
    motor=MotorEmbeddings(cfg)
    # Cada imagen tiene el mismo barrido completo de tiles; orden del CSV no cambia la detección.
    filas=analizar_manifest(args.manifest,motor,galeria,cfg)
    politica=cargar_politica(galeria,cfg)
    if args.comando=="calibrar":
        if not 0<=args.objetivo_far<=.05 or not 0<args.recall_minimo<=1:
            raise ValueError("Objetivo FAR debe estar entre 0 y 0.05 y recall entre 0 y 1.")
        politica=calibrar(filas,galeria,cfg,args.objetivo_far,args.recall_minimo)
        politica["manifest_sha256"]=sha256(args.manifest)
        instalar_calibracion(politica)
        print(f"Política guardada: {CALIBRACION}")
    if politica:
        filas=aplicar_politica(filas,politica)
    else:
        print("Sin calibración: solo scores candidatos; ninguna identidad se acepta.")
    guardar_resultados(filas,args.salida)


if __name__=="__main__":
    try:
        main()
    except (OSError,ValueError,RuntimeError,cv2.error) as error:
        raise SystemExit(f"ERROR: {error}")
