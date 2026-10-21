"""CNN provisional con imágenes existentes, sin SQL ni requisito de sesiones."""
from core.paths import PROJECT_ROOT
from datetime import datetime
from pathlib import Path
from collections import Counter
import json
import math
import threading
import uuid
import numpy as np

from ai.facial.dataset_rostros import RUTA_DATASET,EXTENSIONES,extraer_subject
from ai.facial.base_facial import PREPROCESAMIENTO_CNN
from ai.facial.pipeline_facial import escribir_json_atomico,sha256
from ai.facial.seguridad_cnn import ranking,metricas,buscar_politica

BASE=PROJECT_ROOT
DIRECTORIO=BASE/'modelos/cnn_dataset_actual'
VIGENTE=DIRECTORIO/'vigente.json'
INFORME=BASE/'evaluacion_facial/cnn/dataset_actual.json'
PROTOCOLO='cnn-dataset-actual-estratificado-provisional-v1'
SEMILLA=42
NOTA=('Evaluación provisional por imágenes, sin sesiones independientes. La validación también '
      'selecciona pesos y umbrales; sus resultados pueden ser optimistas. No mide rechazo de personas desconocidas.')
_cache=None
_bloqueo=threading.Lock()


def cargar_actual(ruta=RUTA_DATASET):
    from ai.facial.cnn_dataset import cargar
    candidatos=sorted({extraer_subject(p.name) for p in Path(ruta).rglob('*')
        if p.is_file() and p.suffix.lower() in EXTENSIONES and extraer_subject(p.name)})
    if not candidatos:raise ValueError('No hay imágenes etiquetadas subjectXX en el dataset.')
    datos=cargar(ruta,subjects_activos=candidatos,guardar_informe=False,incluir_sesiones=False)
    clases=[s for s in candidatos if datos['conteos'].get(s,0)>=2]
    if len(clases)<2:raise ValueError('Se requieren al menos dos clases con dos imágenes válidas cada una.')
    ids=[i for i,f in enumerate(datos['metadatos']) if f['subject'] in clases]
    meta=[datos['metadatos'][i] for i in ids];mapping=dict(enumerate(clases))
    inversa={s:i for i,s in mapping.items()}
    resultado={'X':datos['X'][ids],'y':np.array([inversa[f['subject']] for f in meta],np.int32),
        'metadatos':meta,'indice_a_subject':mapping,'conteos':dict(Counter(f['subject'] for f in meta)),
        'excluidas':{s:datos['reporte_dataset']['por_subject'][s] for s in candidatos if s not in clases},
        'rechazos':datos['errores']}
    escribir_json_atomico(INFORME,{'modo':'Dataset actual','protocolo':PROTOCOLO,'nota':NOTA,
        'imagenes':len(meta),'clases':clases,'conteos':resultado['conteos'],
        'excluidas':resultado['excluidas'],'rechazos':resultado['rechazos']})
    return resultado


def dividir(datos):
    from sklearn.model_selection import train_test_split
    ids=np.arange(len(datos['y']))
    entrenamiento,validacion=train_test_split(ids,test_size=max(len(datos['indice_a_subject']),math.ceil(len(ids)*.2)),
        stratify=datos['y'],random_state=SEMILLA)
    esperadas=set(datos['indice_a_subject'])
    for grupo in (entrenamiento,validacion):
        if set(map(int,datos['y'][grupo]))!=esperadas:raise ValueError('Faltan clases en entrenamiento o validación.')
    hashes=[f['pixeles_sha256'] for f in datos['metadatos']]
    if {hashes[i] for i in entrenamiento}&{hashes[i] for i in validacion}:
        raise ValueError('Contenido idéntico entre entrenamiento y validación.')
    return entrenamiento,validacion


def politica_valida(p):
    return (isinstance(p,dict) and p.get('protocolo')==PROTOCOLO and p.get('provisional') is True
        and all(isinstance(p.get(k),(int,float)) and not isinstance(p.get(k),bool)
                and math.isfinite(p[k]) and 0<p[k]<1 for k in ('threshold','margin')))


def aumento(imagen):
    import cv2
    gris=np.asarray(imagen,np.float32)[...,0]
    if np.random.random()<.5:gris=cv2.flip(gris,1)
    matriz=cv2.getRotationMatrix2D((49.5,49.5),np.random.uniform(-6,6),np.random.uniform(.96,1.04))
    matriz[:,2]+=np.random.uniform(-3,3,2)
    gris=cv2.warpAffine(gris,matriz,(100,100),borderMode=cv2.BORDER_REFLECT_101)
    gris=(gris-.5)*np.random.uniform(.94,1.06)+.5+np.random.uniform(-.04,.04)
    return np.clip(gris,0,1).astype(np.float32)[...,None]


def entrenar(callback_estado=None):
    import random
    import tensorflow as tf
    from ai.facial.modelo_cnn import crear_modelo_cnn
    from sklearn.metrics import confusion_matrix,classification_report,ConfusionMatrixDisplay
    from matplotlib.figure import Figure
    avisar=callback_estado or print
    avisar('Preparando imágenes actuales (sin SQL)...')
    datos=cargar_actual();it,iv=dividir(datos);x,y=datos['X'],datos['y']
    random.seed(SEMILLA);np.random.seed(SEMILLA);tf.random.set_seed(SEMILLA)
    try:
        tf.config.threading.set_intra_op_parallelism_threads(2)
        tf.config.threading.set_inter_op_parallelism_threads(1)
    except RuntimeError:pass
    corrida=DIRECTORIO/'entrenamientos'/uuid.uuid4().hex;corrida.mkdir(parents=True)
    ruta_modelo=corrida/'modelo.keras'
    modelo=crear_modelo_cnn(len(datos['indice_a_subject']))
    class Progreso(tf.keras.callbacks.Callback):
        def on_epoch_end(self,epoca,logs=None):
            logs=logs or {};avisar(f"Época {epoca+1}: train {logs.get('accuracy',0):.1%}, validación {logs.get('val_accuracy',0):.1%}")
    callbacks=[tf.keras.callbacks.EarlyStopping(monitor='val_loss',patience=8,restore_best_weights=True),
        tf.keras.callbacks.ModelCheckpoint(str(ruta_modelo),monitor='val_loss',mode='min',save_best_only=True),
        tf.keras.callbacks.ReduceLROnPlateau(monitor='val_loss',factor=.5,patience=4,min_lr=1e-6),Progreso()]
    def transformar(imagen,etiqueta):
        nueva=tf.numpy_function(aumento,[imagen],tf.float32);nueva.set_shape((100,100,1));return nueva,etiqueta
    entrenamiento=(tf.data.Dataset.from_tensor_slices((x[it],y[it])).shuffle(len(it),seed=SEMILLA)
        .map(transformar,num_parallel_calls=1).batch(16).prefetch(1))
    opciones=tf.data.Options();opciones.threading.private_threadpool_size=1
    entrenamiento=entrenamiento.with_options(opciones)
    validacion=tf.data.Dataset.from_tensor_slices((x[iv],y[iv])).batch(16).with_options(opciones)
    clases,frecuencias=np.unique(y[it],return_counts=True)
    pesos={int(c):len(it)/(len(clases)*int(n)) for c,n in zip(clases,frecuencias)}
    historia=modelo.fit(entrenamiento,validation_data=validacion,epochs=50,callbacks=callbacks,class_weight=pesos,verbose=0)
    modelo=tf.keras.models.load_model(ruta_modelo)
    def scores(indices):
        return np.concatenate([modelo(x[ids],training=False).numpy() for ids in np.array_split(indices,max(1,math.ceil(len(indices)/16)))])
    st,sv=scores(it),scores(iv)
    mapping=datos['indice_a_subject'];pred=np.argmax(sv,axis=1)
    filas=[{**ranking(p,mapping),'real':mapping[int(y[i])],'archivo':datos['metadatos'][i]['archivo']} for p,i in zip(sv,iv)]
    error_calibracion=None
    try:politica={**buscar_politica(filas),'protocolo':PROTOCOLO,'provisional':True}
    except ValueError as error:politica=None;error_calibracion=str(error)
    if politica:politica.update(modelo_sha256=sha256(ruta_modelo),preprocesamiento=PREPROCESAMIENTO_CNN,nota=NOTA)
    matriz=confusion_matrix(y[iv],pred,labels=list(mapping))
    resultado={'modo':'Dataset actual','protocolo':PROTOCOLO,'provisional':True,'nota':NOTA,
        'fecha_hora':datetime.now().astimezone().isoformat(),'modelo_valido':True,
        'clases':list(mapping.values()),'conteos':datos['conteos'],'imagenes':len(x),
        'entrenamiento':len(it),'validacion':len(iv),'random_state':SEMILLA,
        'accuracy_entrenamiento':float(np.mean(np.argmax(st,axis=1)==y[it])),
        'accuracy_validacion':float(np.mean(pred==y[iv])),
        'threshold':politica['threshold'] if politica else None,'margin':politica['margin'] if politica else None,
        'error_calibracion':error_calibracion,'metricas_aceptacion':metricas(filas,politica),
        'matriz_confusion':matriz.tolist(),'filas_validacion':filas,
        'reporte_clasificacion':classification_report(y[iv],pred,labels=list(mapping),target_names=list(mapping.values()),output_dict=True,zero_division=0),
        'historial':{k:list(map(float,v)) for k,v in historia.history.items()},
        'mejor_epoca':int(np.argmin(historia.history['val_loss']))+1,
        'preprocesamiento':PREPROCESAMIENTO_CNN,'desconocidos_evaluados':0,
        'modelo_sha256':sha256(ruta_modelo)}
    escribir_json_atomico(corrida/'class_indices.json',mapping)
    escribir_json_atomico(corrida/'politica.json',politica)
    escribir_json_atomico(corrida/'metricas.json',resultado)
    escribir_json_atomico(corrida/'particiones.json',{'protocolo':PROTOCOLO,'random_state':SEMILLA,'nota':NOTA,
        'particiones':{k:[datos['metadatos'][int(i)] for i in ids] for k,ids in [('entrenamiento',it),('validacion',iv)]}})
    figura=Figure(figsize=(9,8));eje=figura.subplots()
    ConfusionMatrixDisplay(matriz,display_labels=list(mapping.values())).plot(ax=eje,xticks_rotation=90,colorbar=False)
    eje.set_title('Validación provisional por imágenes — sin independencia de sesiones')
    figura.tight_layout();figura.savefig(corrida/'matriz_confusion.png',dpi=130)
    escribir_json_atomico(VIGENTE,{'carpeta':str(corrida.relative_to(DIRECTORIO)),
        'modelo_sha256':sha256(ruta_modelo),'etiquetas_sha256':sha256(corrida/'class_indices.json'),
        'metricas_sha256':sha256(corrida/'metricas.json'),'politica_sha256':sha256(corrida/'politica.json')})
    escribir_json_atomico(BASE/'evaluacion_facial/cnn/entrenamiento_dataset_actual.json',
        {**resultado,'carpeta_artefactos':str(corrida.relative_to(BASE))})
    avisar('CNN del dataset actual entrenada. Evaluación y threshold provisionales.')
    return resultado


def archivos_vigentes():
    p=json.loads(VIGENTE.read_text(encoding='utf-8'));carpeta=(DIRECTORIO/p['carpeta']).resolve()
    if DIRECTORIO.resolve() not in carpeta.parents:raise ValueError('Ruta de modelo provisional incompatible.')
    for archivo,campo in [('modelo.keras','modelo_sha256'),('class_indices.json','etiquetas_sha256'),('metricas.json','metricas_sha256'),('politica.json','politica_sha256')]:
        if sha256(carpeta/archivo)!=p[campo]:raise ValueError('Artefactos del modelo provisional modificados: '+archivo)
    return carpeta


def estado():
    try:
        carpeta=archivos_vigentes();m=json.loads((carpeta/'metricas.json').read_text(encoding='utf-8'))
        politica=json.loads((carpeta/'politica.json').read_text(encoding='utf-8'))
        return {'motor':'cnn','modo':'Dataset actual','modelo_existe':True,'entrenada':True,
            'modelo_valido':politica_valida(politica),'calibrada':False,'provisional':True,'detector_listo':True,
            'threshold':m['threshold'],'margin':m['margin'],'subjects':m['clases'],'metricas':m}
    except (OSError,ValueError,KeyError):
        return {'motor':'cnn','modo':'Dataset actual','modelo_existe':False,'entrenada':False,'modelo_valido':False,
            'calibrada':False,'provisional':True,'detector_listo':True,'subjects':[]}


def recursos():
    global _cache
    with _bloqueo:
        carpeta=archivos_vigentes();firma=VIGENTE.read_bytes()
        if _cache is None or _cache[0]!=firma:
            import tensorflow as tf
            modelo=tf.keras.models.load_model(carpeta/'modelo.keras')
            mapping={int(i):s for i,s in json.loads((carpeta/'class_indices.json').read_text(encoding='utf-8')).items()}
            if tuple(modelo.input_shape[1:])!=(100,100,1) or set(mapping)!=set(range(modelo.output_shape[-1])) or len(set(mapping.values()))!=len(mapping):
                raise ValueError('Modelo o class_indices provisional incompatible.')
            politica=json.loads((carpeta/'politica.json').read_text(encoding='utf-8'))
            if politica and (not politica_valida(politica) or politica['modelo_sha256']!=sha256(carpeta/'modelo.keras') or politica['preprocesamiento']!=PREPROCESAMIENTO_CNN):
                raise ValueError('Política provisional incompatible.')
            inferir=lambda lote:modelo(lote,training=False).numpy()
            inferir(np.zeros((1,100,100,1),np.float32))
            _cache=(firma,modelo,mapping,inferir,politica)
        return _cache[1:]


def resumen():
    e=estado();m=e.get('metricas',{})
    if not m:return 'CNN · Dataset actual · Entrene con las imágenes existentes. No requiere SQL ni sesiones nuevas.'
    return (f"CNN · Dataset actual · {m['imagenes']} imágenes / {len(m['clases'])} clases\n"
        f"Train: {m['accuracy_entrenamiento']:.1%} · Validación: {m['accuracy_validacion']:.1%} · Threshold: {m['threshold']} · Margen: {m['margin']}\n"
        'Evaluación provisional por imágenes; sin independencia de sesiones.')


def diagnostico():
    e=estado();m=e.get('metricas',{})
    if not m:return resumen()
    return resumen()+'\n\n'+NOTA+'\n\nImágenes por clase:\n'+json.dumps(m['conteos'],ensure_ascii=False,indent=2)+'\n\nConfusiones:\n'+json.dumps(m['metricas_aceptacion']['confusiones'],ensure_ascii=False,indent=2)


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument('accion',choices=['entrenar','camara','diagnostico','dataset'])
    accion=parser.parse_args().accion
    if accion=='entrenar':print(json.dumps(entrenar(),ensure_ascii=False,indent=2))
    elif accion=='camara':
        from ai.facial.reconocimiento_cnn import reconocer_con_camara
        print(reconocer_con_camara(motor='cnn',modo_cnn='Dataset actual'))
    elif accion=='diagnostico':print(diagnostico())
    else:
        d=cargar_actual();print(json.dumps({'imagenes':len(d['X']),'conteos':d['conteos']},ensure_ascii=False,indent=2))
