from core.paths import PROJECT_ROOT
import re
from collections import Counter
from pathlib import Path

import numpy as np
from PIL import Image
import cv2


BASE_DIR = PROJECT_ROOT
RUTA_DATASET = BASE_DIR / "Clasificacion" / "rostros" / "DataSet01" / "data"
EXTENSIONES = {".gif", ".jpg", ".jpeg", ".png", ".pgm"}
TAMANO_IMAGEN = (100, 100)
PATRON_SUBJECT = re.compile(r"^(subject\d+)\.", re.IGNORECASE)


def preprocesar_region_rostro(gris):
    """Pipeline único para dataset y cámara: gris, 100x100, float32, 0-1, canal."""
    imagen = cv2.resize(np.asarray(gris), TAMANO_IMAGEN, interpolation=cv2.INTER_AREA)
    return (imagen.astype(np.float32) / 255.0)[..., np.newaxis]


def recortar_rostro(gris, detector, margen=0.15):
    rostros = detector.detectMultiScale(np.asarray(gris), 1.2, 5, minSize=(30, 30))
    if len(rostros) == 0:
        return None
    x, y, ancho, alto = max(rostros, key=lambda r: r[2] * r[3])
    margen_x, margen_y = int(ancho * margen), int(alto * margen)
    alto_img, ancho_img = gris.shape[:2]
    x1, y1 = max(0, x-margen_x), max(0, y-margen_y)
    x2, y2 = min(ancho_img, x+ancho+margen_x), min(alto_img, y+alto+margen_y)
    return np.asarray(gris)[y1:y2, x1:x2]


def _crear_detector():
    ruta = Path(cv2.data.haarcascades) / "haarcascade_frontalface_default.xml"
    if not ruta.is_file():
        ruta = BASE_DIR / ".venv" / "Lib" / "site-packages" / "cv2" / "data" / "haarcascade_frontalface_default.xml"
    detector = cv2.CascadeClassifier(str(ruta))
    if detector.empty():
        raise RuntimeError("No se pudo cargar Haar Cascade para preparar el dataset.")
    return detector


def extraer_subject(nombre_archivo):
    coincidencia = PATRON_SUBJECT.match(nombre_archivo)
    return coincidencia.group(1).lower() if coincidencia else None


def cargar_dataset(ruta_dataset=RUTA_DATASET, subjects_activos=None):
    from ai.facial.cnn_dataset import cargar
    return cargar(ruta_dataset,subjects_activos)


def resumir_dataset(datos):
    return {
        "imagenes": len(datos["X"]),
        "subjects": len(datos["indice_a_subject"]),
        "shape_X": datos["X"].shape,
        "shape_y": datos["y"].shape,
        "rango_pixeles": (float(datos["X"].min()), float(datos["X"].max())),
        "tipo": str(datos["X"].dtype),
        "conteos": datos["conteos"],
        "subjects_activos_sql": datos["subjects_activos_sql"],
        "subjects_encontrados_dataset": datos["subjects_encontrados_dataset"],
        "subjects_sin_imagenes": datos["subjects_sin_imagenes"],
        "archivos_dataset_encontrados": datos["archivos_dataset_encontrados"],
        "errores": datos["errores"],
    }


if __name__ == "__main__":
    resumen = resumir_dataset(cargar_dataset())
    print(f"Imágenes válidas: {resumen['imagenes']}")
    print(f"Subjects: {resumen['subjects']}")
    print(f"Shape X: {resumen['shape_X']} | Shape y: {resumen['shape_y']}")
    print(f"Tipo: {resumen['tipo']} | Rango: {resumen['rango_pixeles']}")
    for subject, cantidad in resumen["conteos"].items():
        print(f"{subject}: {cantidad}")
    print(f"Imágenes con error: {len(resumen['errores'])}")
