import json
import threading
import time
from collections import Counter, deque
from pathlib import Path

import cv2
import numpy as np

from alertas import registrar_alerta_empleado_no_reconocido
from dataset_rostros import preprocesar_region_rostro, recortar_rostro
from rostros_empleados import obtener_empleado_por_etiqueta

BASE_DIR = Path(__file__).resolve().parent
RUTA_MODELO = BASE_DIR / "modelos" / "modelo_rostros.keras"
RUTA_ETIQUETAS = BASE_DIR / "modelos" / "etiquetas_rostros.json"
RUTA_METRICAS = BASE_DIR / "modelos" / "metricas_modelo_rostros.json"
UMBRAL_CONFIANZA = 0.60
VENTANA_PREDICCIONES = 10
MINIMO_COINCIDENCIAS = 6
MODO_DEBUG_RECONOCIMIENTO = True
FRAMES_DESCONOCIDO_MINIMOS = 15
FRAMES_SIN_ROSTRO_REINICIO = 5
COOLDOWN_ALERTA_DESCONOCIDO = 60

_bloqueo_camara = threading.Lock()
_evento_detener_camara = threading.Event()
_modelo_cnn = None
_etiquetas_cnn = None
_version_recursos = None
ESTADOS_DESCONOCIDOS = {"DESCONOCIDO", "PREDICCION_BAJA", "SUBJECT_SIN_RELACION"}


def _resultado_sin_rostro():
    return {"estado": "SIN_ROSTRO", "reconocido": False}


def _resultado_desconocido(confianza=0.0, estado="DESCONOCIDO"):
    return {"estado": estado, "reconocido": False, "id_empleado": None,
            "codigo_empleado": None, "nombre": "Desconocido", "cargo": None,
            "etiqueta": None, "confianza": float(confianza)}


def resolver_etiqueta(etiqueta, confianza):
    if not etiqueta or float(confianza) < UMBRAL_CONFIANZA:
        return _resultado_desconocido(confianza, "PREDICCION_BAJA")
    empleado = obtener_empleado_por_etiqueta(etiqueta)
    if empleado is None:
        return _resultado_desconocido(confianza, "SUBJECT_SIN_RELACION")
    base = {"id_empleado": empleado["id_empleado"], "codigo_empleado": empleado["codigo_empleado"],
            "nombre": empleado["nombre"], "cargo": empleado["cargo"], "etiqueta": etiqueta,
            "confianza": float(confianza)}
    if not empleado["empleado_activo"]:
        return {"estado": "EMPLEADO_INACTIVO", "reconocido": False, **base}
    return {"estado": "RECONOCIDO", "reconocido": True, **base}


def verificar_detector_facial():
    try:
        return not _detector_rostros().empty()
    except Exception:
        return False


def obtener_estado_cnn():
    modelo_existe = RUTA_MODELO.is_file() and RUTA_ETIQUETAS.is_file()
    modelo_valido = False
    if RUTA_METRICAS.is_file():
        try:
            modelo_valido = bool(json.loads(RUTA_METRICAS.read_text(encoding="utf-8")).get("modelo_valido"))
        except (OSError, ValueError):
            pass
    return {"modelo_existe": modelo_existe, "modelo_valido": modelo_valido,
            "detector_listo": verificar_detector_facial()}


def _cargar_recursos():
    global _modelo_cnn, _etiquetas_cnn, _version_recursos
    if not RUTA_MODELO.is_file() or not RUTA_ETIQUETAS.is_file():
        raise FileNotFoundError("La CNN todavía no ha sido entrenada. Entrene el modelo primero.")
    if not obtener_estado_cnn()["modelo_valido"]:
        raise RuntimeError("El modelo no tiene métricas válidas. Reentrene la CNN.")
    import tensorflow as tf
    version = (RUTA_MODELO.stat().st_mtime_ns, RUTA_ETIQUETAS.stat().st_mtime_ns)
    if _modelo_cnn is None or version != _version_recursos:
        _modelo_cnn = tf.keras.models.load_model(RUTA_MODELO)
        datos = json.loads(RUTA_ETIQUETAS.read_text(encoding="utf-8"))
        _etiquetas_cnn = {int(i): etiqueta for i, etiqueta in datos.items()}
        _version_recursos = version
    return _modelo_cnn, _etiquetas_cnn


def _detector_rostros():
    nombre = "haarcascade_frontalface_default.xml"
    candidatos = [Path(cv2.data.haarcascades) / nombre,
                   BASE_DIR / ".venv" / "Lib" / "site-packages" / "cv2" / "data" / nombre]
    for ruta in candidatos:
        if ruta.is_file():
            detector = cv2.CascadeClassifier(str(ruta))
            if not detector.empty():
                return detector
    raise RuntimeError("No se encontró Haar Cascade. Reinstale las dependencias del proyecto.")


class ControlAlertaDesconocido:
    def __init__(self, registrar=registrar_alerta_empleado_no_reconocido, reloj=time.monotonic):
        self.registrar = registrar; self.reloj = reloj
        self.frames_desconocido = 0; self.frames_sin_rostro = 0
        self.alertada = False; self.ultima_alerta = -float("inf")

    def procesar(self, estado):
        if estado == "SIN_ROSTRO":
            self.frames_sin_rostro += 1; self.frames_desconocido = 0
            if self.frames_sin_rostro >= FRAMES_SIN_ROSTRO_REINICIO:
                self.alertada = False
            return None
        self.frames_sin_rostro = 0
        if estado not in ESTADOS_DESCONOCIDOS:
            self.frames_desconocido = 0
            return None
        self.frames_desconocido += 1
        ahora = self.reloj()
        if (self.frames_desconocido >= FRAMES_DESCONOCIDO_MINIMOS and not self.alertada
                and ahora - self.ultima_alerta >= COOLDOWN_ALERTA_DESCONOCIDO):
            resultado = self.registrar(); self.alertada = True; self.ultima_alerta = ahora
            return resultado
        return None


def reconocer_con_camara(callback_alerta=None):
    if not _bloqueo_camara.acquire(blocking=False):
        raise RuntimeError("La cámara ya está siendo utilizada.")
    camara = None
    try:
        _evento_detener_camara.clear()
        modelo, etiquetas = _cargar_recursos(); detector = _detector_rostros()
        camara = cv2.VideoCapture(0)
        if not camara.isOpened():
            raise RuntimeError("No se pudo acceder a la cámara.")
        historial = deque(maxlen=VENTANA_PREDICCIONES)
        control_alerta = ControlAlertaDesconocido()
        ultimo = _resultado_sin_rostro()
        while True:
            correcto, frame = camara.read()
            if not correcto:
                raise RuntimeError("No se pudo leer una imagen de la cámara.")
            gris = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            rostros = detector.detectMultiScale(gris, 1.2, 5, minSize=(70, 70))
            if len(rostros) == 0:
                historial.clear(); ultimo = _resultado_sin_rostro()
            else:
                x, y, ancho, alto = max(rostros, key=lambda r: r[2] * r[3])
                recorte = recortar_rostro(gris, detector)
                entrada = preprocesar_region_rostro(recorte)
                probabilidades = modelo.predict(entrada[None, ...], verbose=0)[0]
                indice = int(np.argmax(probabilidades)); confianza_frame = float(probabilidades[indice])
                historial.append((indice, confianza_frame))
                validas = Counter(i for i, c in historial if c >= UMBRAL_CONFIANZA)
                candidata, repeticiones = validas.most_common(1)[0] if validas else (-1, 0)
                confianzas = [c for i, c in historial if i == candidata]
                confianza = float(np.mean(confianzas)) if confianzas else confianza_frame
                estable = len(historial) == VENTANA_PREDICCIONES and repeticiones >= MINIMO_COINCIDENCIAS
                ultimo = (resolver_etiqueta(etiquetas.get(candidata), confianza) if estable
                          else _resultado_desconocido(confianza, "PREDICCION_BAJA"))
                if ultimo["estado"] == "RECONOCIDO":
                    lineas = [ultimo["nombre"], ultimo["codigo_empleado"], f"Confianza: {confianza:.0%}"]; color = (0, 190, 0)
                elif ultimo["estado"] == "EMPLEADO_INACTIVO":
                    lineas = [ultimo["nombre"], "EMPLEADO INACTIVO", f"Confianza: {confianza:.0%}"]; color = (0, 140, 255)
                else:
                    lineas = ["PERSONA DESCONOCIDA" if len(historial) == VENTANA_PREDICCIONES else "Analizando..."]; color = (0, 0, 220)
                cv2.rectangle(frame, (x, y), (x + ancho, y + alto), color, 2)
                for numero, texto in enumerate(lineas):
                    cv2.putText(frame, texto, (x, max(25, y - 12 - 24 * (len(lineas)-numero-1))),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.65, color, 2)
                if MODO_DEBUG_RECONOCIMIENTO:
                    candidato = etiquetas.get(indice, "Sin clase")
                    estado_debug = "Candidato" if not estable else ultimo["estado"]
                    cv2.putText(frame, f"CNN: {candidato}  {confianza_frame:.3f}  {estado_debug}",
                                (15, 58), cv2.FONT_HERSHEY_SIMPLEX, 0.58, (255, 220, 0), 2)
            alerta = control_alerta.procesar(ultimo["estado"])
            if alerta and callback_alerta:
                callback_alerta(alerta)
            cv2.putText(frame, "ESC o Q para salir", (15, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (255,255,255), 2)
            cv2.imshow("Reconocimiento facial CNN", frame)
            if (_evento_detener_camara.is_set() or
                    cv2.waitKey(1) & 0xFF in (27, ord("q"), ord("Q"))):
                return ultimo
    finally:
        if camara is not None:
            camara.release()
        cv2.destroyAllWindows(); _bloqueo_camara.release()


def detener_reconocimiento():
    _evento_detener_camara.set()


if __name__ == "__main__":
    try:
        print(reconocer_con_camara())
    except (RuntimeError, FileNotFoundError, ValueError) as error:
        print(f"ERROR: {error}")
