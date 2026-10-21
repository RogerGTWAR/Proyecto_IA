"""Calibración y diagnóstico CNN sin entrenar ni modificar embeddings."""
from core.paths import PROJECT_ROOT
from datetime import datetime
from pathlib import Path
import json
import shutil
import time
import numpy as np

from ai.facial.pipeline_facial import sha256,escribir_json_atomico
from ai.facial.base_facial import PREPROCESAMIENTO_CNN
from ai.facial.seguridad_cnn import VERSION_PROTOCOLO,ranking,metricas,buscar_politica
from ai.facial.cnn_dataset import validar_manifest

BASE=PROJECT_ROOT
SALIDA=BASE/'evaluacion_facial/cnn'


def calibrar():
    from ai.facial import reconocimiento_cnn as cnn
    from ai.facial.dataset_rostros import cargar_dataset
    from ai.facial.rostros_empleados import obtener_cache_empleados_por_subject
    cache={s:e for s,e in obtener_cache_empleados_por_subject().items() if e.get('empleado_activo')}
    datos=cargar_dataset(subjects_activos=cache)
    modelo,etiquetas,inferir=cnn._cargar_recursos()
    ruta_manifest=cnn.RUTA_MODELO.parent/'particiones_cnn.json'
    manifest=json.loads(ruta_manifest.read_text(encoding='utf-8')) if ruta_manifest.is_file() else {}
    problemas=validar_manifest(manifest,datos)
    problemas.extend(datos['problemas_particion'])
    if manifest.get('modelo_sha256')!=sha256(cnn.RUTA_MODELO):problemas.append('El manifiesto no corresponde al modelo actual.')
    if set(etiquetas.values())!=set(cache):problemas.append('Clases del modelo distintas de las etiquetas activas en SQL.')
    if manifest.get('preprocesamiento')!=PREPROCESAMIENTO_CNN:problemas.append('Preprocesamiento distinto en las particiones.')
    protocolo_valido=not problemas
    por_hash={f['sha256']:i for i,f in enumerate(datos['metadatos'])}
    inversa={s:i for i,s in etiquetas.items()}
    def medir(nombre):
        salida=[]
        for f in manifest.get('particiones',{}).get(nombre,[]):
            if f.get('sha256') not in por_hash or f.get('subject') not in inversa:continue
            i=por_hash[f['sha256']];inicio=time.perf_counter()
            scores=np.asarray(inferir(datos['X'][i:i+1]))[0]
            salida.append({**ranking(scores,etiquetas),'real':f['subject'],'archivo':f['archivo'],
                'inferencia_ms':(time.perf_counter()-inicio)*1000})
        return salida
    desarrollo=medir('calibracion');evaluacion=medir('evaluacion')
    candidato=None
    try:candidato=buscar_politica(desarrollo)
    except ValueError as error:problemas.append(str(error))
    m=metricas(evaluacion,candidato)
    if not evaluacion:problemas.append('No hay imágenes de evaluación utilizables.')
    if m['incorrectas_aceptadas']:
        pares=sorted({f["real"]+' → '+f['best_class'] for f in m['confusiones'] if f['aceptada']})
        problemas.append('Confusiones aceptadas en evaluación: '+', '.join(pares))
    if evaluacion and m['correctas_aceptadas']<np.ceil(len(evaluacion)/2):problemas.append('Cobertura de evaluación inferior al 50 %.')
    reconocidas={f['real'] for f in evaluacion if candidato and f['best_class']==f['real'] and f['best_score']>=candidato['threshold'] and f['margin']>=candidato['margin']}
    if reconocidas!=set(cache):problemas.append('La evaluación no acredita al menos un acierto aceptado para cada clase activa.')
    m['protocolo_valido']=protocolo_valido
    anterior=None
    historico=cnn.RUTA_MODELO.parent/'diagnostico_calibracion_cnn.json'
    if historico.is_file():
        previo=json.loads(historico.read_text(encoding='utf-8'))
        if previo.get('modelo_sha256')==sha256(cnn.RUTA_MODELO):anterior=previo.get('threshold_candidato')
    antes=metricas(evaluacion,{'threshold':anterior,'margin':0}) if isinstance(anterior,(int,float)) else None
    vigente=metricas(evaluacion,candidato if not problemas else None)
    politica={'calibrada':not problemas,'threshold':candidato['threshold'] if candidato and not problemas else None,
        'margin':candidato['margin'] if candidato and not problemas else None,
        'modelo_sha256':sha256(cnn.RUTA_MODELO),'etiquetas_sha256':sha256(cnn.RUTA_ETIQUETAS),
        'particiones_sha256':sha256(ruta_manifest) if ruta_manifest.is_file() else None,
        'protocolo':VERSION_PROTOCOLO,'preprocesamiento':PREPROCESAMIENTO_CNN,
        'validacion_independiente':m,'motivo':' '.join(sorted(set(problemas))),
        'vinculos_sql':{s:e['id_empleado'] for s,e in cache.items()},
        'desconocidos_evaluados':0,
        'alcance':'Evaluación entre clases registradas; no acredita rechazo poblacional de desconocidos.'}
    etiquetas_orden=[etiquetas[i] for i in range(len(etiquetas))]
    matriz=[[sum(f['real']==a and f['best_class']==b for f in evaluacion) for b in etiquetas_orden] for a in etiquetas_orden]
    informe={'modelo_sha256':politica['modelo_sha256'],'protocolo_valido':protocolo_valido,
        'errores_protocolo':sorted(set(problemas)),'candidato_calibracion':candidato,
        'calibracion':desarrollo,'evaluacion':evaluacion,'metricas_candidato':m,
        'referencia_anterior_solo_score':antes,'decision_vigente':vigente,
        'etiquetas_matriz':etiquetas_orden,'matriz_confusion':matriz,
        'dataset':datos['reporte_dataset'],
        'nota':'Si protocolo_valido es falso, los resultados son diagnóstico del modelo anterior; no una nueva evaluación independiente. La cámara anterior ya bloqueaba identidades CNN.'}
    SALIDA.mkdir(parents=True,exist_ok=True)
    escribir_json_atomico(SALIDA/'calibracion.json',informe)
    respaldo=SALIDA/'respaldos'/datetime.now().strftime('%Y%m%d_%H%M%S_%f');respaldo.mkdir(parents=True)
    if cnn.RUTA_CALIBRACION.is_file():shutil.copy2(cnn.RUTA_CALIBRACION,respaldo/cnn.RUTA_CALIBRACION.name)
    escribir_json_atomico(cnn.RUTA_CALIBRACION,politica)
    if problemas:raise ValueError('CNN sin calibración segura. '+politica['motivo']+' Consulte evaluacion_facial/cnn/calibracion.json.')
    return politica
