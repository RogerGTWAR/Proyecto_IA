"""Preparación exclusiva de CNN con procedencia y grupos indivisibles de captura."""
from core.paths import PROJECT_ROOT
from collections import Counter
from pathlib import Path
import hashlib
import json
import cv2
import numpy as np
from PIL import Image

from ai.facial.dataset_rostros import RUTA_DATASET,EXTENSIONES,extraer_subject,preprocesar_region_rostro
from ai.facial.base_facial import fuentes_subject,PREPROCESAMIENTO_CNN
from ai.facial.pipeline_facial import MotorEmbeddings,evaluar_calidad,sha256,escribir_json_atomico
from ai.facial.seguridad_cnn import VERSION_PROTOCOLO

INFORME=PROJECT_ROOT/'evaluacion_facial/cnn/dataset.json'
MUESTRAS_CNN=PROJECT_ROOT/'modelos/cnn_muestras'


def fuentes_cnn(subject,ruta):
    yield from fuentes_subject(subject,ruta)
    for registro in sorted((MUESTRAS_CNN/subject).glob('*/registro.json')):
        sesion=registro.parent/'sesion.json'
        if not sesion.is_file() or not json.loads(sesion.read_text(encoding='utf-8')).get('completa'):continue
        datos_sesion=json.loads(sesion.read_text(encoding='utf-8'))
        if datos_sesion.get('subject')!=subject or datos_sesion.get('session_id')!=registro.parent.name:
            continue
        for fila in json.loads(registro.read_text(encoding='utf-8')):
            original=registro.parent/fila['original']
            if original.is_file():yield original,False,{**fila,'sesion_documentada':datos_sesion}


def procedencia(archivo,subject,metadata):
    """Un archivo distinto nunca acredita una sesión distinta."""
    archivo=Path(archivo)
    sesion=metadata.get('sesion_documentada')
    if sesion:
        from datetime import datetime
        try:
            fecha=datetime.fromisoformat(sesion.get('fecha_hora',sesion.get('fecha','')))
            correcta=(sesion['subject']==subject and sesion['session_id']==archivo.parent.name
                      and sesion.get('grupo') and fecha.tzinfo is not None)
        except (KeyError,ValueError,TypeError):correcta=False
        if not correcta:raise ValueError('Procedencia de sesión CNN incompleta o incompatible.')
        return sesion['session_id'],sesion.get('fecha_hora',sesion.get('fecha')),str(sesion['grupo'])
    # El registro original de inscripción acredita una sola captura, nunca sus frames.
    if archivo.parent.parent.name==subject and (archivo.parent/'registro.json').is_file() and metadata.get('archivo'):
        return archivo.parent.name,None,f'{subject}:captura:{archivo.parent.name}'
    return None,None,f'{subject}:historico_sin_sesion'


def entrada_alineada_cnn(region_bgr):
    """Transformación única tras alignCrop, compartida por dataset y cámara CNN."""
    return preprocesar_region_rostro(cv2.cvtColor(region_bgr,cv2.COLOR_BGR2GRAY))


def preparar(motor,ruta,alineada,metadata):
    with Image.open(ruta) as im:
        rgb=np.asarray(im.convert('RGB'));frame=cv2.cvtColor(rgb,cv2.COLOR_RGB2BGR)
    if frame.size==0 or min(frame.shape[:2])<32 or float(frame.std())<1:
        raise ValueError('Imagen vacía o sin información visual suficiente.')
    pixeles=hashlib.sha256(rgb.tobytes()).hexdigest()
    if alineada:
        if frame.shape[:2]!=(112,112):raise ValueError('Captura alineada de tamaño incompatible.')
        calidad=metadata.get('calidad',{})
        if not calidad.get('valida'):raise ValueError('Captura alineada sin calidad de origen válida.')
        region=frame
    else:
        caras=motor.detectar(frame,exhaustivo=True)
        if len(caras)!=1:raise ValueError(f'Se requiere un rostro; detectados: {len(caras)}.')
        calidad=evaluar_calidad(frame,caras[0],motor.cfg)
        if not calidad['valida']:raise ValueError(calidad['estado'])
        region=motor.alinear(frame,caras[0])
    # Igual que inferencia CNN; nunca calcula características SFace.
    entrada=entrada_alineada_cnn(region)
    return entrada,pixeles,calidad


def cercanas(a,b):
    ga=cv2.resize(a[...,0],(9,8));gb=cv2.resize(b[...,0],(9,8))
    distancia=int(np.count_nonzero((ga[:,1:]>ga[:,:-1])!=(gb[:,1:]>gb[:,:-1])))
    return distancia<=3 and float(np.sqrt(np.mean((a-b)**2)))<=.04


def cargar(ruta_dataset=RUTA_DATASET,subjects_activos=None,guardar_informe=True,incluir_sesiones=True):
    from ai.facial.rostros_empleados import obtener_subjects_activos
    activos=sorted(set(obtener_subjects_activos() if subjects_activos is None else subjects_activos))
    if not activos:raise ValueError('No hay etiquetas faciales activas vinculadas en SQL.')
    ruta=Path(ruta_dataset);todos=sorted(p for p in ruta.rglob('*') if p.is_file() and p.suffix.lower() in EXTENSIONES)
    conteos_archivos=Counter(extraer_subject(p.name) for p in todos if extraer_subject(p.name))
    motor=MotorEmbeddings();registros=[];imagenes=[];rechazos=[];contenido={};padres=[]
    def raiz(i):
        while padres[i]!=i:padres[i]=padres[padres[i]];i=padres[i]
        return i
    def unir(i,j):padres[raiz(i)]=raiz(j)
    subjects=sorted(set(conteos_archivos)|set(activos)|{p.name for p in MUESTRAS_CNN.glob('subject*') if p.is_dir()})
    fuentes=Counter();casi={s:set() for s in subjects};conflictos=[]
    for s in subjects:
        fuentes_subject_seleccionadas=fuentes_cnn if incluir_sesiones else fuentes_subject
        for archivo,alineada,meta in fuentes_subject_seleccionadas(s,ruta):
            fuentes[s]+=1
            try:
                entrada,pixeles,calidad=preparar(motor,archivo,alineada,meta)
                if pixeles in contenido:
                    anterior=contenido[pixeles]
                    if anterior['subject']!=s:
                        anterior['conflicto_identidad']=True
                        conflictos.append({'subjects':[anterior['subject'],s],'archivos':[anterior['archivo'],str(archivo)]})
                        raise ValueError('Contenido idéntico con otra etiqueta: '+anterior['subject'])
                    raise ValueError('Imagen duplicada de '+anterior['archivo'])
                captura,fecha,grupo=procedencia(archivo,s,meta)
                f={'archivo':str(archivo.resolve()),'sha256':sha256(archivo),'pixeles_sha256':pixeles,
                   'subject':s,'sesion':captura,'session_id':captura,'fecha':fecha,'grupo_origen':grupo,
                   'calidad':calidad,'conflicto_identidad':False}
                i=len(registros);padres.append(i)
                for j,anterior in enumerate(registros):
                    if f['grupo_origen']==anterior['grupo_origen']:unir(i,j)
                    if cercanas(entrada,imagenes[j]):
                        if s!=anterior['subject']:
                            f['conflicto_identidad']=anterior['conflicto_identidad']=True
                            conflictos.append({'subjects':[anterior['subject'],s],'archivos':[anterior['archivo'],f['archivo']]})
                        else:
                            unir(i,j);casi[s].add(str(archivo))
                registros.append(f);imagenes.append(entrada);contenido[pixeles]=f
            except Exception as error:rechazos.append({'subject':s,'archivo':str(archivo),'motivo':str(error)})
    for i,f in enumerate(registros):f['grupo']=registros[raiz(i)]['grupo_origen']
    utilizables=[i for i,f in enumerate(registros) if not f['conflicto_identidad']]
    for f in registros:
        if f['conflicto_identidad']:rechazos.append({'subject':f['subject'],'archivo':f['archivo'],'motivo':'Contenido idéntico o casi idéntico bajo otra etiqueta; requiere revisión humana.'})
    meta_todos=[registros[i] for i in utilizables]
    cantidades_sesion=Counter((f['subject'],f['sesion']) for f in meta_todos if f['sesion'])
    for f in meta_todos:
        f['sesion_apta']=bool(f['sesion'] and cantidades_sesion[(f['subject'],f['sesion'])]>=4)
    utilizables=[i for i in utilizables if registros[i]['subject'] in activos]
    meta=[registros[i] for i in utilizables];x=np.stack([imagenes[i] for i in utilizables]) if utilizables else np.empty((0,100,100,1),np.float32)
    etiquetas={s:i for i,s in enumerate(activos)};y=np.array([etiquetas[f['subject']] for f in meta],np.int32)
    conteos=Counter(f['subject'] for f in meta)
    sesiones={s:len({f['sesion'] for f in meta_todos if f['subject']==s and f['sesion_apta']}) for s in subjects}
    grupos={s:len({f['grupo'] for f in meta_todos if f['subject']==s and f['sesion_apta']}) for s in subjects}
    aptas=Counter(f['subject'] for f in meta_todos if f['sesion_apta'])
    grupos_sesiones={}
    for f in meta:
        if f['sesion_apta']:grupos_sesiones.setdefault((f['subject'],f['grupo']),set()).add(f['sesion'])
    fugas=sum(max(0,len(v)-1) for v in grupos_sesiones.values())
    problemas=[f'{s}: {conteos[s]} imágenes válidas, {aptas[s]} con sesión documentada; sesiones {sesiones[s]}/4, grupos independientes {grupos[s]}/4. Capture al menos {max(0,4-min(sesiones[s],grupos[s]))} sesiones nuevas y reúna 8 imágenes válidas con procedencia.' for s in activos if aptas[s]<8 or sesiones[s]<4 or grupos[s]<4]
    if fugas:problemas.append(f'Hay {fugas} solapamientos de contenido entre sesiones; revise las capturas antes de habilitar entrenamiento.')
    auditoria={}
    for s in subjects:
        motivos=[r['motivo'] for r in rechazos if r['subject']==s]
        auditoria[s]={'activo_sql':s in activos,'archivos_dataset':conteos_archivos[s],
            'fuentes_canonicas':fuentes[s],'validas':sum(f['subject']==s for f in meta_todos),
            'borrosas':sum('borros' in m.lower() or 'desenfo' in m.lower() for m in motivos),
            'duplicadas':sum(m.startswith('Imagen duplicada') for m in motivos),'casi_duplicadas':len(casi[s]),
            'rechazadas':len(motivos),'sesiones':sesiones[s],'grupos':grupos[s],
            'imagenes_con_sesion':aptas[s],'sin_sesion':sum(f['subject']==s and not f['sesion'] for f in meta_todos)}
    resumen={'preprocesamiento':PREPROCESAMIENTO_CNN,'protocolo':VERSION_PROTOCOLO,
             'resumen_sesiones':{'listo':not problemas and fugas==0,'subjects':len(activos),
                'sesiones_completas':sum(min(4,sesiones[s]) for s in activos),'sesiones_requeridas':4*len(activos),
                'clases_incompletas':sum(sesiones[s]<4 or grupos[s]<4 or aptas[s]<8 for s in activos),
                'fugas_entre_sesiones':fugas},
             'archivos_por_subject':dict(sorted(conteos_archivos.items())),
             'subjects_activos_sql':activos,'validas_por_subject':{s:conteos[s] for s in activos},
             'grupos_por_subject':grupos,'rechazos':rechazos,'problemas_particion':problemas,
             'sesiones_por_subject':sesiones,'por_subject':auditoria,'conflictos_contenido':conflictos,
             'sesiones_externas_verificadas':False,
             'nota':'Los archivos históricos sin sesión documentada se conservan en un grupo no acreditado y no participan en particiones. Los grupos indicados cuentan solo sesiones documentadas, fusionadas si hay contenido casi duplicado. Ninguna imagen se borró ni se reasignó a otra persona.'}
    import zipfile
    modelo=PROJECT_ROOT/'modelos/modelo_rostros.keras'
    etiquetas_path=modelo.parent/'etiquetas_rostros.json'
    try:
        mapping=json.loads(etiquetas_path.read_text(encoding='utf-8'))
        with zipfile.ZipFile(modelo) as z:config=json.loads(z.read('config.json'))
        unidades=config['config']['layers'][-1]['config']['units']
        resumen['mapping_modelo_actual']={'indice_a_subject':mapping,'salidas':unidades,
            'indices_consecutivos':sorted(map(int,mapping))==list(range(unidades)),
            'clases_sql_coinciden':set(mapping.values())==set(activos),
            'etiquetas_unicas':len(set(mapping.values()))==len(mapping),
            'modelo_sha256':sha256(modelo),'etiquetas_sha256':sha256(etiquetas_path)}
    except (OSError,ValueError,KeyError,zipfile.BadZipFile):
        resumen['mapping_modelo_actual']={'error':'No fue posible comprobar la arquitectura y el mapping guardados.'}
    if guardar_informe:escribir_json_atomico(INFORME,resumen)
    return {'X':x,'y':y,'subject_a_indice':etiquetas,'indice_a_subject':{i:s for s,i in etiquetas.items()},
        'archivos':[f['archivo'] for f in meta],'metadatos':meta,'errores':rechazos,'conteos':dict(conteos),
        'subjects_activos_sql':activos,'subjects_encontrados_dataset':sorted(conteos_archivos),
        'subjects_sin_imagenes':[s for s in activos if not conteos[s]],'archivos_dataset_encontrados':len(todos),
        'problemas_particion':problemas,'reporte_dataset':resumen}


def particionar(datos):
    if datos['problemas_particion']:raise ValueError('No se puede entrenar una CNN con evaluación independiente. '+' '.join(datos['problemas_particion']))
    for s in datos['subjects_activos_sql']:
        filas=[f for f in datos['metadatos'] if f['subject']==s and f.get('sesion') and f.get('sesion_apta',True)]
        if len(filas)<8 or len({f['sesion'] for f in filas})<4 or len({f['grupo'] for f in filas})<4:
            raise ValueError(s+' no tiene suficientes sesiones para crear validación independiente (mínimo 4 sesiones y 8 imágenes).')
    salida={k:[] for k in ('entrenamiento','validacion','calibracion','evaluacion')}
    for s in datos['subjects_activos_sql']:
        grupos={}
        for i,f in enumerate(datos['metadatos']):
            if f['subject']==s and f.get('sesion') and f.get('sesion_apta',True):grupos.setdefault(f['grupo'],[]).append(i)
        orden=sorted(grupos,key=lambda g:hashlib.sha256(g.encode()).hexdigest())
        # Reservar grupos completos antes de cualquier aumento de datos o entrenamiento.
        for k,g in zip(('validacion','calibracion','evaluacion'),orden[:3]):salida[k]+=grupos[g]
        for g in orden[3:]:salida['entrenamiento']+=grupos[g]
    problemas=validar_manifest({'protocolo':VERSION_PROTOCOLO,'particiones':{
        k:[datos['metadatos'][i] for i in ids] for k,ids in salida.items()}},datos)
    if problemas:raise ValueError('Partición insegura: '+' '.join(problemas))
    return salida


def validar_manifest(manifest,datos):
    problemas=[];partes=manifest.get('particiones',{});meta={f['sha256']:f for f in datos['metadatos']}
    vistos={};grupos={};sesiones={};clases=set(datos['subjects_activos_sql'])
    problemas.extend(datos.get('problemas_particion',[]))
    if manifest.get('protocolo')!=VERSION_PROTOCOLO:problemas.append('Partición anterior sin separación de validación y calibración ni grupos de captura.')
    for nombre in ('entrenamiento','validacion','calibracion','evaluacion'):
        filas=partes.get(nombre,[])
        if not filas:problemas.append('Conjunto ausente o vacío: '+nombre)
        if {f.get('subject') for f in filas}!=clases:problemas.append('Faltan clases activas en '+nombre)
        for f in filas:
            actual=meta.get(f.get('sha256'))
            if not actual or actual['subject']!=f.get('subject'):
                problemas.append('Imagen modificada, excluida o etiqueta incompatible: '+str(f.get('archivo')));continue
            h=actual['pixeles_sha256'];g=actual['grupo']
            sesion=(actual['subject'],actual.get('sesion'))
            if not sesion[1]:problemas.append('Imagen sin sesión documentada: '+str(f.get('archivo')))
            if not actual.get('sesion_apta',True):problemas.append('Sesión con menos de cuatro imágenes válidas: '+str(sesion))
            if sesion in sesiones and sesiones[sesion]!=nombre:problemas.append('Misma sesión en '+sesiones[sesion]+' y '+nombre+': '+str(sesion))
            sesiones[sesion]=nombre
            if h in vistos:problemas.append('Contenido repetido entre '+vistos[h]+' y '+nombre)
            vistos[h]=nombre
            if g in grupos and grupos[g]!=nombre:problemas.append('Misma sesión o grupo en '+grupos[g]+' y '+nombre+': '+g)
            grupos[g]=nombre
    return sorted(set(problemas))
