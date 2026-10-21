"""Migración y diagnóstico real; no altera SQL ni inventa calibración."""
pass

import argparse
import csv
import json
from pathlib import Path
import cv2
import numpy as np
from PIL import Image
from ai.facial.dataset_rostros import RUTA_DATASET, EXTENSIONES, extraer_subject
from ai.facial.pipeline_facial import MotorEmbeddings, GaleriaEmbeddings, GALERIA, normalizar, sha256
from ai.facial.rostros_empleados import obtener_cache_empleados_por_subject


def cargar_imagen(ruta):
    with Image.open(ruta) as im:
        return cv2.cvtColor(np.asarray(im.convert("RGB")), cv2.COLOR_RGB2BGR)


def extraer_archivo(motor, ruta):
    frame = cargar_imagen(ruta)
    caras = motor.detectar(frame)
    if len(caras) != 1:
        raise ValueError(f"Se requiere un rostro; detectados: {len(caras)}")
    vector, alineado = motor.extraer(frame, caras[0])
    return vector


def regenerar(cache=None, ruta_dataset=RUTA_DATASET):
    cache = obtener_cache_empleados_por_subject() if cache is None else cache
    motor = MotorEmbeddings()
    # Construcción limpia: una etiqueta retirada no compite contra su reemplazo.
    galeria=GaleriaEmbeddings(cargar=False)
    informe = {"empleados_sql": len(cache), "migrados": {}, "errores": []}
    for subject, empleado in cache.items():
        if not empleado.get("empleado_activo"):
            continue
        vectores, archivos = [], []
        from ai.facial.base_facial import fuentes_subject, preparar_muestra
        hashes=set()
        for ruta, alineada, metadata in fuentes_subject(subject, ruta_dataset):
            try:
                digest='sha256:'+sha256(ruta)
                if digest in hashes:continue
                vector,_,calidad=preparar_muestra(motor,ruta,alineada,metadata)
                if not calidad.get('valida',False):
                    informe['errores'].append({'archivo':str(ruta),'error':calidad.get('estado','Calidad no documentada')})
                    continue
                vectores.append(vector); archivos.append(digest); hashes.add(digest)
            except Exception as error:
                informe["errores"].append({"archivo": str(ruta), "error": str(error)})
        if len(vectores) >= 5:
            galeria.agregar(subject, empleado["id_empleado"], vectores, archivos)
            informe["migrados"][subject] = {"nombre": empleado["nombre"], "embeddings": len(vectores)}
        else:
            informe["errores"].append({"subject":subject, "error": "Menos de cinco imágenes detectables. Los rostros deben registrarse nuevamente porque cambió el modelo facial y estas imágenes no permiten generar su base."})
    esperados={s for s,e in cache.items() if e.get('empleado_activo')}
    if set(informe['migrados'])!=esperados:
        raise ValueError('Regeneración incompleta; se conserva la galería anterior. Faltan: '+', '.join(sorted(esperados-set(informe['migrados']))))
    if GALERIA.exists():
        import shutil
        from datetime import datetime
        shutil.copy2(GALERIA, GALERIA.with_name("galeria_respaldo_"+datetime.now().strftime("%Y%m%d_%H%M%S_%f")+".npz"))
    galeria.guardar()
    informe["embeddings_totales"] = len(galeria.vectores)
    informe["nota"] = "Imágenes originales reprocesadas con YuNet + alineación SFace BGR. No se comparan vectores CNN. Calibración pendiente; pruebas de reutilización no miden generalización."
    return informe


def diagnosticar():
    from ai.facial.base_facial import diagnostico
    return diagnostico()


def calibrar_registrados():
    """Separa registro, calibración y evaluación; no valida desconocidos."""
    from ai.facial.base_facial import calibrar_base
    return calibrar_base()


def calibrar_cnn():
    from ai.facial.calibracion_cnn import calibrar
    return calibrar()


if __name__=="__main__":
    parser=argparse.ArgumentParser(); parser.add_argument("accion",choices=["regenerar","diagnosticar"])
    args=parser.parse_args()
    pass
    pass
    print(json.dumps(regenerar() if args.accion=="regenerar" else diagnosticar(),ensure_ascii=False,indent=2))
