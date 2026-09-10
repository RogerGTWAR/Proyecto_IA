import re
from collections import Counter
from pathlib import Path

import numpy as np
from PIL import Image
import cv2


BASE_DIR = Path(__file__).resolve().parent
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
    ruta = Path(ruta_dataset)
    if not ruta.is_dir():
        raise FileNotFoundError(f"No se encontró el dataset en: {ruta.resolve()}")

    todos_archivos = sorted(a for a in ruta.iterdir() if a.is_file() and a.suffix.lower() in EXTENSIONES)
    encontrados = sorted({extraer_subject(a.name) for a in todos_archivos if extraer_subject(a.name)})
    if subjects_activos is None:
        from rostros_empleados import obtener_subjects_activos
        subjects_activos = obtener_subjects_activos()
    activos = set(subjects_activos)
    if not activos:
        raise ValueError("No existen rostros activos para entrenar la CNN.")
    archivos = [a for a in todos_archivos if extraer_subject(a.name) in activos]
    subjects = sorted({extraer_subject(a.name) for a in archivos if extraer_subject(a.name)})
    sin_imagenes = sorted(activos.difference(encontrados))
    subject_a_indice = {subject: indice for indice, subject in enumerate(subjects)}
    imagenes, etiquetas, archivos_validos, errores = [], [], [], []
    detector = _crear_detector()

    for archivo in archivos:
        subject = extraer_subject(archivo.name)
        if subject is None:
            errores.append({"archivo": archivo.name, "error": "Nombre sin formato subjectXX.condicion"})
            continue
        try:
            with Image.open(archivo) as imagen:
                gris = np.asarray(imagen.convert("L"))
                # Las capturas nuevas ya son recortes faciales 100x100.
                region = gris if gris.shape == TAMANO_IMAGEN else recortar_rostro(gris, detector)
                if region is None:
                    # Conserva imágenes históricas válidas si Haar falla en una
                    # expresión extrema; la cámara nunca clasifica sin detección.
                    region = gris
                arreglo = preprocesar_region_rostro(region)
            imagenes.append(arreglo)
            etiquetas.append(subject_a_indice[subject])
            archivos_validos.append(str(archivo))
        except Exception as error:
            errores.append({"archivo": archivo.name, "error": str(error)})

    if not imagenes:
        raise ValueError("No se pudo cargar ninguna imagen válida del dataset.")

    x = np.stack(imagenes).astype(np.float32)
    y = np.asarray(etiquetas, dtype=np.int32)
    indice_a_subject = {indice: subject for subject, indice in subject_a_indice.items()}
    conteos = Counter(indice_a_subject[int(valor)] for valor in y)
    return {
        "X": x, "y": y,
        "subject_a_indice": subject_a_indice,
        "indice_a_subject": indice_a_subject,
        "archivos": archivos_validos,
        "errores": errores,
        "conteos": dict(sorted(conteos.items())),
        "subjects_activos_sql": sorted(activos),
        "subjects_encontrados_dataset": encontrados,
        "subjects_sin_imagenes": sin_imagenes,
        "archivos_dataset_encontrados": len(todos_archivos),
    }


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
