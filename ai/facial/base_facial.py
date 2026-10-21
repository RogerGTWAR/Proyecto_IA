"""Fuentes trazables, diagnóstico y calibración facial con imágenes separadas."""
import csv
import json
import shutil
from collections import Counter
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np

from ai.facial.dataset_rostros import RUTA_DATASET, EXTENSIONES, extraer_subject
from ai.facial.pipeline_facial import (BASE_DIR, DIRECTORIO, GALERIA, CALIBRACION, VERSION_PIPELINE,
    GaleriaEmbeddings, MotorEmbeddings, cargar_configuracion, evaluar_calidad,
    firma_configuracion, normalizar, sha256, escribir_json_atomico)

SALIDA = BASE_DIR / 'evaluacion_facial'
PREPROCESAMIENTO_CNN = 'yunet-align-sface-gris-100x100-float32-0-1-v2'


def leer_bgr(ruta):
    from PIL import Image
    with Image.open(ruta) as imagen:
        return cv2.cvtColor(np.asarray(imagen.convert('RGB')), cv2.COLOR_RGB2BGR)


def fuentes_subject(subject, ruta_dataset=RUTA_DATASET):
    """Prioriza capturas trazables; excluye sus copias reducidas del dataset."""
    registros = sorted((DIRECTORIO/'muestras'/subject).glob('*/registro.json'))
    if registros:
        for registro in registros:
            for fila in json.loads(registro.read_text(encoding='utf-8')):
                alineada = registro.parent/fila['archivo']
                original = registro.parent/fila['original'] if fila.get('original') else None
                if alineada.is_file():
                    yield original or alineada, original is None, fila
    else:
        for ruta in sorted(Path(ruta_dataset).rglob('*')):
            if ruta.is_file() and ruta.suffix.lower() in EXTENSIONES and extraer_subject(ruta.name)==subject:
                yield ruta, False, {}


def preparar_muestra(motor, ruta, ya_alineada=False, metadata=None):
    frame = leer_bgr(ruta)
    if ya_alineada:
        # Procedencia explícita de registro.json: alignCrop ya se ejecutó al capturar.
        # Volver a detectar/alinear este recorte cambia la geometría y el embedding.
        if frame.shape[:2] != (112,112):
            raise ValueError('Captura alineada incompatible: se requieren 112x112 píxeles.')
        vector = normalizar(motor.reconocedor.feature(frame).copy())
        calidad = dict((metadata or {}).get('calidad', {}))
        return vector, frame, calidad
    caras = motor.detectar(frame, exhaustivo=True)
    if len(caras)!=1:
        raise ValueError(f'Se requiere un rostro; detectados: {len(caras)}')
    calidad = evaluar_calidad(frame, caras[0], motor.cfg)
    vector, alineado = motor.extraer(frame, caras[0])
    return vector, alineado, calidad


def resumen(valores):
    v=np.asarray(valores, dtype=float)
    return {'cantidad':len(v), 'minimo':float(v.min()) if len(v) else None,
            'promedio':float(v.mean()) if len(v) else None,
            'maximo':float(v.max()) if len(v) else None}


def diagnostico(cache=None, imagenes=True):
    from ai.facial.rostros_empleados import obtener_cache_empleados_por_subject
    cache=obtener_cache_empleados_por_subject() if cache is None else cache
    g=GaleriaEmbeddings(); cfg=cargar_configuracion()
    activos={s:e for s,e in cache.items() if e.get('empleado_activo')}
    motor=MotorEmbeddings(cfg) if imagenes else None
    normas=np.linalg.norm(g.vectores,axis=1)
    with np.load(GALERIA,allow_pickle=False) as datos:
        raw=datos['vectores'];normas_raw=np.linalg.norm(raw,axis=1)
    politica=json.loads(CALIBRACION.read_text(encoding='utf-8')) if CALIBRACION.is_file() else {}
    informe={'motor':'YuNet 2023mar / SFace 2021dec BGR', 'empleados':len(activos),
        'embeddings':len(g.vectores),'dimension':g.vectores.shape[1],
        'no_finitos':int((~np.isfinite(g.vectores)).sum()),'vectores_cero':int((normas<1e-8).sum()),
        'norma_minima':float(normas.min()) if len(normas) else None,
        'norma_maxima':float(normas.max()) if len(normas) else None,
        'normas_archivo_sin_normalizar':resumen(normas_raw),
        'galeria_modificada':politica.get('galeria_sha256')!=g.firma,
        'configuracion_modificada':politica.get('config_sha256')!=firma_configuracion(cfg),
        'etiquetas_sin_vinculo_activo':sorted(set(map(str,g.subjects))-set(activos)),
        'por_empleado':{},'conflictos':[]}
    completa=DIRECTORIO/'base_muestras.npz'
    gd=GaleriaEmbeddings(completa) if completa.is_file() else g
    informe['embeddings_validos_base']=len(gd.vectores)
    informe['calidad_configurada']={k:cfg[k] for k in ('min_rostro','blur_min','blur_rechazo','blur_lado','iluminacion_min','iluminacion_max','roll_max','yaw_max')}
    for s,e in activos.items():
        archivos=list(fuentes_subject(s)); hashes=[]; pixeles=[]; calidades=[]; errores=[]
        for ruta,alineada,meta in archivos:
            hashes.append(sha256(ruta))
            try:
                pixeles.append(__import__('hashlib').sha256(leer_bgr(ruta).tobytes()).hexdigest())
                if motor:
                    _,_,q=preparar_muestra(motor,ruta,alineada,meta)
                    calidades.append({'archivo':str(ruta.relative_to(BASE_DIR)),**q})
            except Exception as error: errores.append({'archivo':str(ruta), 'error':str(error)})
        informe['por_empleado'][s]={'nombre':e['nombre'],'id_empleado':e['id_empleado'],
            'imagenes':len(archivos),'embeddings':int((g.subjects==s).sum()),
            'imagenes_repetidas':len(hashes)-len(set(hashes)),
            'pixeles_repetidos':len(pixeles)-len(set(pixeles)),
            'calidad':calidades,'errores':errores}
    sims=gd.vectores@gd.vectores.T; intra=[]; inter=[]; duplicados=[]
    SALIDA.mkdir(exist_ok=True)
    with (SALIDA/'distribuciones_similitud.csv').open('w',newline='',encoding='utf-8-sig') as f:
        w=csv.writer(f);w.writerow(['etiqueta_a','etiqueta_b','muestra_a','muestra_b','misma_persona','similitud'])
        for i in range(len(sims)):
            for j in range(i):
                score=float(sims[i,j]); misma=gd.subjects[i]==gd.subjects[j]
                (intra if misma else inter).append(score)
                w.writerow([gd.subjects[i],gd.subjects[j],gd.archivos[i],gd.archivos[j],misma,score])
                if score>.99999:duplicados.append({'a':int(i),'b':int(j),'similitud':score})
        for a in np.unique(gd.subjects):
            for b in np.unique(gd.subjects):
                if a>=b:continue
                score=float(sims[np.ix_(gd.subjects==a,gd.subjects==b)].max())
                informe['conflictos'].append({'a':str(a),'b':str(b),'maximo':score,
                    'a_activa':a in activos,'b_activa':b in activos})
    informe.update(intra=resumen(intra),inter=resumen(inter),embeddings_duplicados=duplicados)
    informe['conflictos'].sort(key=lambda r:r['maximo'],reverse=True)
    escribir_json_atomico(SALIDA/'diagnostico_completo.json',informe)
    return informe


def calibrar_base(cache=None):
    """Separa registro/calibración/evaluación antes de escoger la política."""
    from ai.facial.rostros_empleados import obtener_cache_empleados_por_subject
    cache=obtener_cache_empleados_por_subject() if cache is None else cache
    cfg=cargar_configuracion();g=GaleriaEmbeddings();partes={};registro=[];cal=[];evaluacion=[]
    base_completa=DIRECTORIO/'base_muestras.npz'
    if base_completa.is_file():
        completa=GaleriaEmbeddings(base_completa)
        if set(map(str,g.archivos)).issubset(set(map(str,completa.archivos))):g=completa
    for s,e in cache.items():
        if not e.get('empleado_activo'):continue
        ids=np.flatnonzero((g.subjects==s)&(g.empleados==e['id_empleado']))
        # Hashes únicos y no casi idénticos; orden estable independiente del directorio.
        distintos=[]; vistos=set()
        for i in sorted(ids,key=lambda i:str(g.archivos[i])):
            if g.archivos[i] in vistos:continue
            vistos.add(g.archivos[i])
            if distintos and float(np.max(g.vectores[distintos]@g.vectores[i]))>.99999:continue
            distintos.append(int(i))
        if len(distintos)<8:raise ValueError(f'{e["nombre"]} ({s}): {len(distintos)} muestras distintas; se requieren 8 para separar registro y evaluación.')
        n=min(15,len(distintos)-3);nc=(len(distintos)-n)//2
        registro+=distintos[:n];cal+=distintos[n:n+nc];evaluacion+=distintos[n+nc:]
        partes[s]={'registro':n,'calibracion':nc,'evaluacion':len(distintos)-n-nc}
    if len(partes)<2:raise ValueError('Se requieren dos identidades activas con muestras suficientes.')
    operativa=GaleriaEmbeddings(cargar=False)
    for campo in ('vectores','subjects','empleados','archivos'):setattr(operativa,campo,getattr(g,campo)[registro])
    def medir(indices):
        filas=[]
        for i in indices:
            scores=[]
            for s in partes:
                v=operativa.vectores[operativa.subjects==s]@g.vectores[i]
                scores.append((float(np.sort(v)[-3:].mean()),s))
            scores.sort(reverse=True);real=str(g.subjects[i]);propio=next(v for v,s in scores if s==real)
            ajeno=max(v for v,s in scores if s!=real)
            filas.append({'archivo':str(g.archivos[i]),'real':real,'candidato':scores[0][1],
                'score':scores[0][0],'margen':scores[0][0]-scores[1][0],'propio':propio,'ajeno':ajeno})
        return filas
    desarrollo=medir(cal);validacion=medir(evaluacion)
    intra=[f['propio'] for f in desarrollo];inter=[f['ajeno'] for f in desarrollo]
    informe={'particiones':partes,'calibracion':desarrollo,'evaluacion':validacion,
             'intra_top3':resumen(intra),'inter_top3':resumen(inter),
             'nota':'Imágenes separadas; las capturas de una misma sesión siguen correlacionadas. Falta evaluación con desconocidos y sesiones nuevas.'}
    escribir_json_atomico(SALIDA/'evaluacion_separada.json',informe)
    if min(intra)<=max(inter):
        conflictos=[f for f in desarrollo if f['propio']<=max(inter)]
        raise ValueError('Solapamiento activo; no se activó la base: '+', '.join(sorted({f['real'] for f in conflictos})))
    threshold=float((min(intra)+max(inter))/2)
    margen=float(min(f['propio']-f['ajeno'] for f in desarrollo)/2)
    correctas=sum(f['candidato']==f['real'] and f['score']>=threshold and f['margen']>=margen for f in validacion)
    errores=[f for f in validacion if f['candidato']!=f['real'] and f['score']>=threshold and f['margen']>=margen]
    aceptadas={f['real'] for f in validacion if f['candidato']==f['real'] and f['score']>=threshold and f['margen']>=margen}
    if errores or aceptadas!=set(partes):raise ValueError('La evaluación separada no permite una política útil para todos los empleados; revise evaluacion_separada.json.')
    respaldo=SALIDA/'respaldos'/datetime.now().strftime('%Y%m%d_%H%M%S_%f');respaldo.mkdir(parents=True)
    for ruta in (GALERIA,CALIBRACION):
        if ruta.is_file():shutil.copy2(ruta,respaldo/ruta.name)
    # Conserva todas las fuentes regeneradas para recalibrar sin reutilizar holdout.
    g.ruta=DIRECTORIO/'base_muestras.npz';g.guardar()
    operativa.guardar()
    politica={'threshold':threshold,'margen':margen,'min_rostro':cfg['min_rostro'],'calibrada':True,
        'pipeline':VERSION_PIPELINE,'galeria_sha256':operativa.firma,'config_sha256':firma_configuracion(cfg),
        'alcance':'registro_calibracion_evaluacion_imagenes_separadas',
        'validacion_desconocidos':'pendiente','particiones':partes,
        'intra_min':min(intra),'inter_max':max(inter),'intra':resumen(intra),'inter':resumen(inter),
        'evaluacion':{'imagenes':len(validacion),'correctas_aceptadas':correctas,'identidades_incorrectas_aceptadas':len(errores)},
        'nota':informe['nota']}
    escribir_json_atomico(CALIBRACION,politica)
    return politica
