"""Utilidades pequeñas para captura de webcam con baja latencia."""

import threading
import time

import cv2


ANCHO_CAMARA = 1920
ALTO_CAMARA = 1080
MODO_DEBUG_CAMARA = True
_bloqueo_cierre = threading.RLock()


def abrir_camara(indice=0, resolucion=None, servicio='CAMARA'):
    """Fuente USB/archivo/IP; no aplica backends de webcam a URLs RTSP."""
    from core.system_state import state_manager
    state_manager.update(servicio,'STARTING','Abriendo fuente de vídeo.',activity='INITIALIZING',expected=True)
    intentos = []
    if isinstance(indice, int):
        if hasattr(cv2, "CAP_DSHOW"):
            intentos.append(lambda: cv2.VideoCapture(indice, cv2.CAP_DSHOW))
        if hasattr(cv2, "CAP_MSMF"):
            intentos.append(lambda: cv2.VideoCapture(indice, cv2.CAP_MSMF))
        intentos.append(lambda: cv2.VideoCapture(indice))
    else:
        # FFmpeg limita esperas de apertura/lectura cuando soporta estos parámetros.
        parametros = [cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, 5000, cv2.CAP_PROP_READ_TIMEOUT_MSEC, 2000]
        intentos.append(lambda: cv2.VideoCapture(str(indice), cv2.CAP_FFMPEG, parametros))
    for crear in intentos:
        camara = crear()
        if camara.isOpened():
            if isinstance(indice, int):
                ancho, alto = resolucion or (ANCHO_CAMARA, ALTO_CAMARA)
                camara.set(cv2.CAP_PROP_FRAME_WIDTH, ancho)
                camara.set(cv2.CAP_PROP_FRAME_HEIGHT, alto)
            camara.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            state_manager.update(servicio,'ONLINE','Fuente de vídeo abierta.',activity='IDLE')
            return camara
        camara.release()
    state_manager.update(servicio,'ERROR','No se pudo abrir la fuente de vídeo.',error='CAMERA_OPEN_FAILED',activity='IDLE')
    raise RuntimeError("No se pudo acceder a la fuente de video. Revise dispositivo, URL o permisos.")


class CamaraUltimoFrame:
    """Captura continuamente; los consumidores leen solo el frame más reciente."""

    def __init__(self, indice=0, resolucion=None, servicio='CAMARA'):
        self.servicio = servicio
        self.camara = abrir_camara(indice, resolucion) if servicio=='CAMARA' else abrir_camara(indice, resolucion, servicio)
        self.detener = threading.Event()
        self.bloqueo = threading.Lock()
        self.frame = None
        self.numero = 0
        self.error = None
        self.ultima_lectura_ms = 0.0
        self._cerrada = False
        self._bloqueo_cierre = threading.Lock()
        self.hilo = threading.Thread(target=self._capturar, name="camara-captura", daemon=True)

    @property
    def resolucion(self):
        return (int(self.camara.get(cv2.CAP_PROP_FRAME_WIDTH)),
                int(self.camara.get(cv2.CAP_PROP_FRAME_HEIGHT)))

    def iniciar(self):
        self.hilo.start()
        return self

    def _capturar(self):
        from core.system_state import state_manager
        reported=False
        while not self.detener.is_set():
            inicio = time.perf_counter()
            correcto, frame = self.camara.read()
            self.ultima_lectura_ms = (time.perf_counter() - inicio) * 1000.0
            if not correcto:
                self.error = RuntimeError("No se pudo leer una imagen de la cámara.")
                self.detener.set()
                if not self._cerrada:
                    state_manager.update(self.servicio,'ERROR','No se pudieron leer imágenes.',error='CAMERA_READ_FAILED',activity='IDLE')
                break
            if not reported:
                state_manager.update(self.servicio,'ONLINE','Captura entregando imágenes.',activity='STREAMING')
                reported=True
            with self.bloqueo:
                self.frame = frame
                self.numero += 1

    def leer(self):
        with self.bloqueo:
            return self.numero, self.frame

    def cerrar(self):
        with self._bloqueo_cierre:
            if self._cerrada:
                return
            self._cerrada = True
            self.detener.set()
            self.camara.release()
            from core.system_state import state_manager
            if state_manager.get(self.servicio).status!='ERROR':
                state_manager.update(self.servicio,'OFFLINE','Captura liberada.',activity='IDLE',expected=True)
        if self.hilo.is_alive() and self.hilo is not threading.current_thread():
            self.hilo.join(timeout=0.5)


def cerrar_camara(eventos=(), capturador=None, workers=(), nombre_ventana=None,
                  ventana_tk=None, after_id=None, callback_final=None):
    """Cierre central, seguro e idempotente para cualquier sesión de cámara."""
    with _bloqueo_cierre:
        for evento in eventos:
            if evento is not None:
                evento.set()
        if ventana_tk is not None and after_id is not None:
            try: ventana_tk.after_cancel(after_id)
            except Exception: pass
        if capturador is not None:
            capturador.cerrar()
        for worker in workers:
            if worker is not None and worker.is_alive() and worker is not threading.current_thread():
                worker.join(timeout=0.5)
        if nombre_ventana:
            try: cv2.destroyWindow(nombre_ventana)
            except cv2.error: pass
        try: cv2.destroyAllWindows()
        except cv2.error: pass
        if ventana_tk is not None:
            try:
                if ventana_tk.winfo_exists(): ventana_tk.destroy()
            except Exception: pass
        if callback_final is not None:
            callback_final()


def evento_cierre_opencv(nombre_ventana, evento_detener=None, comprobar_ventana=True):
    """Detecta ESC, Q, el botón X y solicitudes externas sin perder eventos."""
    tecla = cv2.waitKey(1) & 0xFF
    if tecla in (27, ord("q"), ord("Q")):
        return True
    if evento_detener is not None and evento_detener.is_set():
        return True
    if not comprobar_ventana:
        return False
    try:
        return cv2.getWindowProperty(nombre_ventana, cv2.WND_PROP_VISIBLE) < 1
    except cv2.error:
        return False


class MedidorRendimiento:
    def __init__(self, intervalo_impresion=0.5):
        self.intervalo = intervalo_impresion
        self.inicio = time.perf_counter()
        self.ultima_salida = self.inicio
        self.frames = 0
        self.fps_suave = 0.0
        self.tiempos = {}
        self.valores = {}

    def registrar(self, nombre, segundos):
        self.tiempos[nombre] = segundos * 1000.0

    def registrar_valor(self, nombre, valor):
        self.valores[nombre] = float(valor)

    def nuevo_frame(self):
        self.frames += 1
        ahora = time.perf_counter()
        transcurrido = ahora - self.inicio
        fps = self.frames / transcurrido if transcurrido else 0.0
        self.fps_suave = fps if not self.fps_suave else self.fps_suave * 0.85 + fps * 0.15
        if MODO_DEBUG_CAMARA and ahora - self.ultima_salida >= self.intervalo:
            detalle = " | ".join(f"{k}: {v:.1f} ms" for k, v in self.tiempos.items())
            if self.valores:
                detalle += " | " + " | ".join(f"{k}: {v:.1f}" for k, v in self.valores.items())
            print(f"Cámara | {detalle} | FPS video: {self.fps_suave:.1f}")
            self.ultima_salida = ahora
        return self.fps_suave
