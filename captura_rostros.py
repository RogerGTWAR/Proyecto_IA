import re
import shutil
import time
from pathlib import Path

import cv2

from dataset_rostros import RUTA_DATASET, preprocesar_region_rostro, recortar_rostro
from reconocimiento_cnn import (_bloqueo_camara, _detector_rostros,
                                _evento_detener_camara)
from rostros_empleados import asignar_etiqueta_empleado

BASE_DIR = Path(__file__).resolve().parent
CARPETA_TEMP = BASE_DIR / "rostros_temp"
NUM_IMAGENES_CAPTURA = 30
MIN_IMAGENES_VALIDAS = 20
INTERVALO_CAPTURA = 0.4
PATRON = re.compile(r"^subject(\d+)", re.IGNORECASE)
INSTRUCCIONES = ("Mirar al frente", "Mirar ligeramente a la izquierda",
                 "Mirar ligeramente a la derecha", "Sonreír",
                 "Acercarse ligeramente", "Expresión normal")


def obtener_siguiente_subject():
    numeros = []
    for archivo in RUTA_DATASET.iterdir():
        coincidencia = PATRON.match(archivo.name)
        if coincidencia:
            numeros.append(int(coincidencia.group(1)))
    return f"subject{max(numeros, default=0)+1:02d}"


def capturar_rostros_nuevo_empleado(id_empleado):
    if not _bloqueo_camara.acquire(blocking=False):
        raise RuntimeError("La cámara ya está siendo utilizada.")
    subject = obtener_siguiente_subject()
    temporal = CARPETA_TEMP / subject
    if temporal.exists():
        shutil.rmtree(temporal)
    temporal.mkdir(parents=True)
    camara = None; guardadas = 0; ultima = 0.0
    try:
        _evento_detener_camara.clear()
        detector = _detector_rostros(); camara = cv2.VideoCapture(0)
        if not camara.isOpened():
            raise RuntimeError("No se pudo acceder a la cámara.")
        while guardadas < NUM_IMAGENES_CAPTURA:
            correcto, frame = camara.read()
            if not correcto:
                raise RuntimeError("No se pudo leer la cámara.")
            gris = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            rostros = detector.detectMultiScale(gris, 1.2, 5, minSize=(70, 70))
            instruccion = INSTRUCCIONES[min(len(INSTRUCCIONES)-1,
                                            guardadas * len(INSTRUCCIONES) // NUM_IMAGENES_CAPTURA)]
            if len(rostros) == 1:
                x, y, ancho, alto = rostros[0]
                cv2.rectangle(frame, (x,y), (x+ancho,y+alto), (0,200,0), 2)
                ahora = time.monotonic()
                if ahora-ultima >= INTERVALO_CAPTURA:
                    region = recortar_rostro(gris, detector)
                    imagen = (preprocesar_region_rostro(region)[..., 0] * 255).astype("uint8")
                    guardadas += 1; ultima = ahora
                    cv2.imwrite(str(temporal / f"{subject}.capture{guardadas:03d}.png"), imagen)
            cv2.putText(frame, f"{instruccion} | {guardadas}/{NUM_IMAGENES_CAPTURA}",
                        (15,30), cv2.FONT_HERSHEY_SIMPLEX, .65, (0,255,0), 2)
            cv2.putText(frame, "Un solo rostro | ESC o Q cancela", (15,60),
                        cv2.FONT_HERSHEY_SIMPLEX, .58, (255,255,255), 2)
            cv2.imshow("Registrar rostro", frame)
            if (_evento_detener_camara.is_set() or
                    cv2.waitKey(1) & 0xFF in (27, ord("q"), ord("Q"))):
                break
        completado = guardadas >= MIN_IMAGENES_VALIDAS
        if completado:
            RUTA_DATASET.mkdir(parents=True, exist_ok=True)
            movidos = []
            for archivo in temporal.iterdir():
                destino = RUTA_DATASET / archivo.name
                shutil.move(str(archivo), str(destino)); movidos.append(destino)
            try:
                asignar_etiqueta_empleado(id_empleado, subject)
            except Exception:
                for archivo in movidos:
                    archivo.unlink(missing_ok=True)
                raise
        return {"completado": completado, "subject": subject if completado else None,
                "imagenes_guardadas": guardadas}
    finally:
        if camara is not None: camara.release()
        cv2.destroyAllWindows()
        if temporal.exists(): shutil.rmtree(temporal)
        _bloqueo_camara.release()
