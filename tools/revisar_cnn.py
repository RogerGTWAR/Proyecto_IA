"""Diagnóstico y calibración de CNN; no ejecuta calibración de embeddings."""
from pathlib import Path
import argparse
import json
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('accion',choices=['dataset','calibrar'],default='dataset',nargs='?')
    args=parser.parse_args()
    if args.accion=='dataset':
        from ai.facial.dataset_rostros import cargar_dataset
        d=cargar_dataset()['reporte_dataset']
        import csv
        from ai.facial.diagnostico_cnn import detalle
        carpeta=Path(__file__).resolve().parents[1]/'evaluacion_facial/cnn'
        with (carpeta/'inventario_imagenes.csv').open('w',encoding='utf-8-sig',newline='') as archivo:
            filas=[{'subject':s,**v} for s,v in d['por_subject'].items()]
            escritor=csv.DictWriter(archivo,fieldnames=list(filas[0]));escritor.writeheader();escritor.writerows(filas)
        (carpeta/'diagnostico_sesiones.txt').write_text(detalle(),encoding='utf-8')
        informe={'estado':'SIN CALIBRAR','entrenamiento_ejecutado':False,
            'clases_activas':d['subjects_activos_sql'],'por_subject':d['por_subject'],
            'faltantes':d['problemas_particion'],'mapping':d['mapping_modelo_actual'],
            'accuracy_final':None,'falsos_positivos_finales':None,'threshold':None,'margin':None,
            'confusiones_corregidas':[],
            'nota':'Las confusiones del modelo anterior siguen pendientes de capturas y evaluación independiente. No hay medición acreditada de personas desconocidas.'}
        (carpeta/'preparacion_sesiones.json').write_text(json.dumps(informe,ensure_ascii=False,indent=2),encoding='utf-8')
        print('Subject | Archivos | Válidas | Duplicadas | Sesiones | Grupos | Activo SQL')
        for s,v in d['por_subject'].items():
            print(s,*[v[k] for k in ('archivos_dataset','validas','duplicadas','sesiones','grupos','activo_sql')],sep=' | ')
        print('No se entrenó. Detalle: evaluacion_facial/cnn/diagnostico_sesiones.txt')
    else:
        from ai.facial.calibracion_cnn import calibrar
        try:print(json.dumps(calibrar(),ensure_ascii=False,indent=2))
        except ValueError as error:
            print(str(error));sys.exit(2)
