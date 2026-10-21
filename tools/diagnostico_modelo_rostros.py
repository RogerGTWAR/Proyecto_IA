"""Evaluación reproducible del modelo facial usando imágenes reales del dataset."""

import sys
from pathlib import Path as _RutaProyecto
_RAIZ_PROYECTO = _RutaProyecto(__file__).resolve().parents[1]
if str(_RAIZ_PROYECTO) not in sys.path:
    sys.path.insert(0, str(_RAIZ_PROYECTO))


import json
import time
from collections import defaultdict
from pathlib import Path

import numpy as np

from ai.facial.dataset_rostros import cargar_dataset
from ai.facial.reconocimiento_cnn import RUTA_ETIQUETAS, RUTA_MODELO


def evaluar_modelo(verbose=True):
    import tensorflow as tf
    etiquetas = {int(k): v for k, v in json.loads(
        RUTA_ETIQUETAS.read_text(encoding="utf-8")).items()}
    datos = cargar_dataset(subjects_activos=set(etiquetas.values()))
    modelo = tf.keras.models.load_model(RUTA_MODELO)
    dummy = np.zeros((1, *datos["X"].shape[1:]), dtype=np.float32)
    modelo(dummy, training=False).numpy()
    tiempos = []
    for imagen in datos["X"][:min(30, len(datos["X"]))]:
        inicio = time.perf_counter()
        modelo(imagen[None, ...], training=False).numpy()
        tiempos.append(time.perf_counter() - inicio)
    probabilidades = modelo.predict(datos["X"], verbose=0)
    predicciones = np.argmax(probabilidades, axis=1)
    detalle, resumen = [], defaultdict(lambda: {"aciertos": 0, "errores": 0, "total": 0})
    for indice, (real, predicha) in enumerate(zip(datos["y"], predicciones)):
        subject_real = datos["indice_a_subject"][int(real)]
        subject_predicho = etiquetas[int(predicha)]
        correcto = subject_real == subject_predicho
        resumen[subject_real]["total"] += 1
        resumen[subject_real]["aciertos" if correcto else "errores"] += 1
        fila = {"archivo": Path(datos["archivos"][indice]).name, "real": subject_real,
                "predicha": subject_predicho,
                "confianza": float(probabilidades[indice, predicha]), "correcto": correcto}
        detalle.append(fila)
        if verbose:
            print(f"Real: {subject_real:10} | Predicción: {subject_predicho:10} | "
                  f"Confianza: {fila['confianza']:.3f} | {'Correcto' if correcto else 'INCORRECTO'}")
    for subject, valores in resumen.items():
        valores["accuracy"] = valores["aciertos"] / valores["total"]
    resultado = {"imagenes": len(detalle),
                 "accuracy": sum(f["correcto"] for f in detalle) / len(detalle),
                 "cnn_ms_promedio": float(np.mean(tiempos) * 1000),
                 "por_subject": dict(resumen), "errores": [f for f in detalle if not f["correcto"]]}
    print(f"\nAccuracy dataset completo: {resultado['accuracy']:.2%}")
    print(f"Inferencia individual promedio: {resultado['cnn_ms_promedio']:.2f} ms")
    for subject, valores in resultado["por_subject"].items():
        print(f"{subject}: {valores['aciertos']}/{valores['total']} ({valores['accuracy']:.2%})")
    return resultado


if __name__ == "__main__":
    evaluar_modelo()
