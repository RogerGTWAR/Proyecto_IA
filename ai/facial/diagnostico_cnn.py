"""Presentación breve y detalle verificable del dataset exclusivo de CNN."""
from core.paths import PROJECT_ROOT
import json
from pathlib import Path

BASE=PROJECT_ROOT


def leer(nombre):
    try:return json.loads((BASE/'evaluacion_facial/cnn'/nombre).read_text(encoding='utf-8'))
    except (OSError,ValueError):return {}


def conflictos_historicos():
    """Errores del modelo anterior; no son resultados de una evaluación nueva."""
    datos=leer('calibracion.json')
    return sorted({(f['real'],f['best_class']) for f in datos.get('metricas_candidato',{}).get('confusiones',[]) if f.get('aceptada')})


def resumen(calibrada=False):
    d=leer('dataset.json');activos=d.get('subjects_activos_sql',[])
    sesiones=d.get('sesiones_por_subject',{})
    minimo=min((sesiones.get(s,0) for s in activos),default=0)
    validas=sum(d.get('validas_por_subject',{}).values())
    motivo='Dataset insuficiente' if d.get('problemas_particion') else 'Falta evaluación independiente' if not calibrada else 'Evaluación aprobada'
    g=d.get('resumen_sesiones',{})
    return (f"Dataset CNN: {'LISTO' if g.get('listo') else 'INCOMPLETO'} · Subjects: {len(activos)}\n"
            f"Sesiones completas: {g.get('sesiones_completas',0)}/{4*len(activos)} · Clases incompletas: {g.get('clases_incompletas',len(activos))} · Fugas detectadas: {g.get('fugas_entre_sesiones',0)}\n"
            f"CNN: {'Calibrada' if calibrada else 'Sin calibrar'} · {motivo}\n"
            f"Sesiones mínimas por clase: {minimo}/4 · Imágenes válidas: {validas}\n"
            f"Pares con confusión histórica: {len(conflictos_historicos())} · Ver diagnóstico")


def estado_subject(subject,calibrada=False):
    if calibrada:return 'Reconocible'
    d=leer('dataset.json').get('por_subject',{}).get(subject)
    if d is None:return 'CNN: validar dataset'
    motivos=[]
    if d['sesiones']<4:motivos.append(f"faltan sesiones ({d['sesiones']}/4)")
    if d['imagenes_con_sesion']<8:motivos.append(f"imágenes con sesión {d['imagenes_con_sesion']}/8")
    pares=sorted({b if a==subject else a for a,b in conflictos_historicos() if subject in (a,b)})
    if pares:motivos.append('confusión histórica con '+', '.join(pares))
    return 'CNN: '+('; '.join(motivos) or 'evaluación y calibración pendientes')


def detalle():
    from collections import Counter
    d=leer('dataset.json')
    inactivos={s for s,v in d.get('por_subject',{}).items() if not v['activo_sql']}
    excluidas_inactivas=Counter(r['motivo'] for r in d.get('rechazos',[]) if r['subject'] in inactivos)
    lineas=['AUDITORÍA DEL DATASET CNN',
        'Válida indica calidad visual, no independencia de sesión ni identidad humana confirmada.',
        'Los archivos históricos sin procedencia no se reparten entre conjuntos.',
        'Las copias reducidas de inscripciones se sustituyen por sus fuentes canónicas; no se suman dos veces.',
        'Las sesiones incompletas se conservan, pero no habilitan entrenamiento.',
        '', 'Subject | Activo | Archivos | Fuentes | Válidas | Borrosas detectadas | Duplicadas | Casi duplicadas | Sesiones | Grupos']
    for s,v in d.get('por_subject',{}).items():
        lineas.append(' | '.join(map(str,[s,'Sí' if v['activo_sql'] else 'No',v['archivos_dataset'],v['fuentes_canonicas'],
            v['validas'],v['borrosas'],v['duplicadas'],v['casi_duplicadas'],v['sesiones'],v['grupos']])))
    lineas+=['','DATOS QUE FALTAN',*d.get('problemas_particion',[]),'',
        'CONFUSIONES DEL MODELO ANTERIOR (PARTICIONES NO VÁLIDAS)',
        *[a+' → '+b+': pendiente de nuevas sesiones y evaluación; no se reasignaron etiquetas.' for a,b in conflictos_historicos()],
        'No se puede confirmar una etiqueta humana ni una carpeta mezclada solo por similitud visual.',
        'No se encontraron conflictos de contenido entre las fuentes válidas de las clases revisadas: '+str(len(d.get('conflictos_contenido',[])))+'.',
        '', 'MAPPING GUARDADO',
        json.dumps(d.get('mapping_modelo_actual',{}),ensure_ascii=False,indent=2),
        '', 'PROTOCOLO',
        'Mínimo 4 sesiones documentadas, cada una con al menos 4 imágenes válidas, y 4 grupos sin fuga por clase activa.',
        'Se reserva una sesión/grupo completo para validación, otro para calibración y otro para evaluación final.',
        'Los grupos restantes se usan para entrenamiento. Con cuatro sesiones queda una por conjunto.',
        'El conjunto final no selecciona el modelo ni ajusta threshold o margin.',
        'Capturar sesiones → Validar dataset → Entrenar desde cero → Evaluar → Calibrar → Activar.',
        'No se entrenó en esta revisión. Accuracy final, falsos positivos finales, threshold y margin: pendientes.',
        'No se acreditaron personas desconocidas independientes para medir falsos positivos fuera de las clases.',
        'Motivos de exclusión en clases inactivas: '+json.dumps(dict(excluidas_inactivas),ensure_ascii=False),
        'El conteo de borrosas refleja el motivo detectado; no certifica nitidez en imágenes rechazadas por otro motivo.',
        '', 'IMÁGENES EXCLUIDAS']
    lineas += [r['subject']+' | '+Path(r['archivo']).name+' | '+r['motivo'] for r in d.get('rechazos',[])]
    return '\n'.join(lineas)
