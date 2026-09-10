import json
import asyncio
import audioop
import hashlib
import os
import queue
import re
import tempfile
import threading
import time
from pathlib import Path

os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")


BASE_DIR = Path(__file__).resolve().parent
RUTA_MODELO_VOZ = BASE_DIR / "modelos_voz" / "vosk-model-small-es-0.42"
VELOCIDAD_VOZ = 165
VOZ_EDGE = "es-MX-JorgeNeural"
FRASE_ACTIVACION = "hola jarvis"
FRECUENCIA_MUESTREO = 16000
TIEMPO_MAXIMO_ESCUCHA = 10
SILENCIO_FIN_FRASE = 0.6
TAMANO_BLOQUE = 2000
UMBRAL_VOZ = 250
TTS_RATE = "+10%"
TTS_TIMEOUT = 6.0
MODO_METRICAS_VOZ = False
CACHE_VOZ_DIR = BASE_DIR / "cache_voz"
FRASES_CACHEABLES = {
    "Hola, amigo. ¿En qué puedo ayudarte?", "Hola. Estoy listo para ayudarte con el inventario.",
    "Buenas. ¿Qué necesitas revisar?", "Todo bien, amigo. ¿En qué puedo ayudarte?",
    "Todo bien por aquí. ¿Qué necesitas revisar?", "Con gusto, amigo.",
    "Para eso estoy.", "Cuando quieras.", "Hasta luego, amigo.",
    "Nos vemos. Aquí estaré cuando necesites algo.",
}

_modelo_voz = None
_bloqueo_modelo = threading.Lock()
_bloqueo_microfono = threading.Lock()
_bloqueo_voz = threading.Lock()
_motor_voz = None
_evento_detener_voz = threading.Event()
_ultimas_metricas = {}
_bucle_async = None
_hilo_async = None
_bloqueo_bucle = threading.Lock()


def obtener_ruta_modelo():
    ruta = RUTA_MODELO_VOZ.resolve()
    if ruta.suffix.lower() == ".zip":
        raise RuntimeError(f"El modelo debe estar descomprimido, no ser un ZIP:\n{ruta}")
    if not ruta.is_dir():
        raise RuntimeError(f"No se encontró el modelo de reconocimiento de voz en:\n{ruta}")
    faltantes = [nombre for nombre in ("am", "conf", "graph") if not (ruta / nombre).is_dir()]
    if faltantes:
        raise RuntimeError(f"El modelo de voz está incompleto en:\n{ruta}\nFaltan: {', '.join(faltantes)}.")
    return ruta


def cargar_modelo_voz():
    global _modelo_voz
    if _modelo_voz is not None:
        return _modelo_voz
    with _bloqueo_modelo:
        if _modelo_voz is not None:
            return _modelo_voz
        try:
            from vosk import Model
        except ImportError as error:
            raise RuntimeError("Vosk no está instalado. Ejecute: python -m pip install -r requirements.txt") from error
        ruta = obtener_ruta_modelo()
        try:
            _modelo_voz = Model(str(ruta))
        except Exception as error:
            raise RuntimeError(f"No fue posible cargar el modelo Vosk. Verifique sus archivos en:\n{ruta}") from error
    return _modelo_voz


def _registrar_metricas(**metricas):
    _ultimas_metricas.update(metricas)
    if MODO_METRICAS_VOZ:
        for nombre, valor in metricas.items():
            if isinstance(valor, (int, float)) and not isinstance(valor, bool):
                print(f"[VOZ] {nombre}: {valor:.3f} s")


def obtener_ultimas_metricas():
    return {clave: valor for clave, valor in _ultimas_metricas.items()
            if not clave.startswith("_")}


def registrar_tiempo_jarvis(segundos):
    _registrar_metricas(jarvis=segundos)


def inicializar_audio():
    import pygame
    if not pygame.mixer.get_init():
        pygame.mixer.init()


def precalentar_voz():
    """Carga Vosk y el mezclador una sola vez en segundo plano."""
    def tarea():
        try:
            cargar_modelo_voz()
            inicializar_audio()
        except Exception as error:
            print(f"[VOZ] No fue posible precalentar el audio: {error}")
    threading.Thread(target=tarea, daemon=True).start()


def listar_dispositivos_audio():
    try:
        import sounddevice as sd
        return [dict(dispositivo) for dispositivo in sd.query_devices()]
    except ImportError as error:
        raise RuntimeError("sounddevice no está instalado. Ejecute: python -m pip install -r requirements.txt") from error
    except Exception as error:
        raise RuntimeError("No fue posible consultar los dispositivos de audio.") from error


def obtener_microfono_predeterminado():
    try:
        import sounddevice as sd
        dispositivos = sd.query_devices()
        indice = sd.default.device[0]
        candidatos = []
        if indice is not None and int(indice) >= 0:
            candidatos.append(int(indice))
        candidatos.extend(i for i, d in enumerate(dispositivos)
                          if d["max_input_channels"] > 0 and i not in candidatos)
        indice = None
        dispositivo = None
        for candidato in candidatos:
            actual = dispositivos[candidato]
            if actual["max_input_channels"] <= 0:
                continue
            try:
                sd.check_input_settings(device=candidato, channels=1,
                                        dtype="int16",
                                        samplerate=FRECUENCIA_MUESTREO)
            except sd.PortAudioError:
                continue
            indice, dispositivo = candidato, actual
            break
        if dispositivo is None:
            raise RuntimeError("No se encontró un micrófono disponible compatible con 16000 Hz.")
        return {"indice": indice, "nombre": dispositivo["name"],
                "canales_entrada": dispositivo["max_input_channels"]}
    except RuntimeError:
        raise
    except ImportError as error:
        raise RuntimeError("sounddevice no está instalado. Ejecute: python -m pip install -r requirements.txt") from error
    except Exception as error:
        raise RuntimeError("No se encontró un micrófono disponible.") from error


def escuchar_pregunta():
    if not _bloqueo_microfono.acquire(blocking=False):
        raise RuntimeError("El micrófono está siendo utilizado por otra escucha.")
    try:
        try:
            import sounddevice as sd
            from vosk import KaldiRecognizer
        except ImportError as error:
            raise RuntimeError("Las dependencias de voz no están instaladas.") from error
        modelo = cargar_modelo_voz()
        microfono = obtener_microfono_predeterminado()
        reconocedor = KaldiRecognizer(modelo, FRECUENCIA_MUESTREO)
        cola_audio = queue.Queue()

        def recibir_audio(datos, cuadros, tiempo_audio, estado):
            if estado:
                print(f"Aviso de audio: {estado}")
            cola_audio.put(bytes(datos))

        inicio = time.perf_counter()
        tiempo_vosk = 0.0
        ultimo_sonido = None
        voz_detectada = False

        def finalizar_texto(texto):
            ahora = time.perf_counter()
            _ultimas_metricas["_ultimo_sonido_perf"] = ultimo_sonido
            _registrar_metricas(
                escucha=ahora - inicio,
                silencio_fin=0.0 if ultimo_sonido is None else ahora - ultimo_sonido,
                vosk=tiempo_vosk,
            )
            return texto

        try:
            with sd.RawInputStream(device=microfono["indice"], samplerate=FRECUENCIA_MUESTREO,
                                   blocksize=TAMANO_BLOQUE, dtype="int16", channels=1,
                                   callback=recibir_audio):
                while time.perf_counter() - inicio < TIEMPO_MAXIMO_ESCUCHA:
                    try:
                        bloque = cola_audio.get(timeout=0.1)
                    except queue.Empty:
                        continue
                    marca_vosk = time.perf_counter()
                    aceptado = reconocedor.AcceptWaveform(bloque)
                    tiempo_vosk += time.perf_counter() - marca_vosk
                    if aceptado:
                        texto = json.loads(reconocedor.Result()).get("text", "").strip()
                        if texto:
                            return finalizar_texto(texto)
                    marca_vosk = time.perf_counter()
                    parcial = json.loads(reconocedor.PartialResult()).get("partial", "").strip()
                    tiempo_vosk += time.perf_counter() - marca_vosk
                    if parcial:
                        voz_detectada = True
                    if voz_detectada and audioop.rms(bloque, 2) >= UMBRAL_VOZ:
                        ultimo_sonido = time.perf_counter()
                    if (voz_detectada and ultimo_sonido is not None and
                            time.perf_counter() - ultimo_sonido >= SILENCIO_FIN_FRASE):
                        marca_vosk = time.perf_counter()
                        texto = json.loads(reconocedor.FinalResult()).get("text", "").strip()
                        tiempo_vosk += time.perf_counter() - marca_vosk
                        if texto:
                            return finalizar_texto(texto)
                        break
        except sd.PortAudioError as error:
            print(f"Error técnico de sounddevice: {error}")
            raise RuntimeError("No fue posible utilizar el micrófono. Puede estar ocupado o no admitir 16000 Hz.") from error
        marca_vosk = time.perf_counter()
        texto = json.loads(reconocedor.FinalResult()).get("text", "").strip()
        tiempo_vosk += time.perf_counter() - marca_vosk
        if not texto:
            raise RuntimeError("No pude entender lo que dijiste. Intenta nuevamente.")
        return finalizar_texto(texto)
    finally:
        _bloqueo_microfono.release()


def _seleccionar_voz_espanol(motor):
    for voz in motor.getProperty("voices"):
        descripcion = f"{voz.id} {voz.name} {getattr(voz, 'languages', '')}".lower()
        if any(valor in descripcion for valor in ("spanish", "español", "_es", "es-", "es_")):
            motor.setProperty("voice", voz.id)
            break


def preparar_texto_para_voz(texto):
    numeros = {"0": "cero", "1": "uno", "2": "dos", "3": "tres", "4": "cuatro",
               "5": "cinco", "6": "seis", "7": "siete", "8": "ocho", "9": "nueve"}
    def pronunciar_codigo(coincidencia):
        partes = coincidencia.group(0).replace("-", " ").split()
        resultado = []
        for parte in partes:
            resultado.append(" ".join(numeros.get(c, c) for c in parte) if parte.isdigit() else parte)
        return ", ".join(resultado)
    texto = re.sub(r"\b[A-Za-z]+(?:-\d+)+\b", pronunciar_codigo, str(texto))
    return texto.replace("\n- ", ". ").replace("\n", ". ")


async def _generar_audio_edge(texto, archivo):
    import edge_tts
    comunicacion = edge_tts.Communicate(texto, VOZ_EDGE, rate=TTS_RATE)
    await asyncio.wait_for(comunicacion.save(archivo), timeout=TTS_TIMEOUT)


def _obtener_bucle_async():
    global _bucle_async, _hilo_async
    with _bloqueo_bucle:
        if _bucle_async is not None and _bucle_async.is_running():
            return _bucle_async
        listo = threading.Event()
        def ejecutar_bucle():
            global _bucle_async
            bucle = asyncio.new_event_loop()
            asyncio.set_event_loop(bucle)
            _bucle_async = bucle
            listo.set()
            bucle.run_forever()
            bucle.close()
        _hilo_async = threading.Thread(target=ejecutar_bucle, daemon=True)
        _hilo_async.start()
        listo.wait(timeout=2)
        if _bucle_async is None:
            raise RuntimeError("No fue posible iniciar el generador de voz.")
        return _bucle_async


def _ejecutar_async(corutina):
    futuro = asyncio.run_coroutine_threadsafe(corutina, _obtener_bucle_async())
    return futuro.result(timeout=TTS_TIMEOUT + 1)


def _ruta_cache(texto):
    if texto not in FRASES_CACHEABLES:
        return None
    clave = hashlib.sha256(f"{VOZ_EDGE}|{TTS_RATE}|{texto}".encode("utf-8")).hexdigest()
    return CACHE_VOZ_DIR / f"{clave}.mp3"


def _hablar_edge(texto):
    import pygame
    inicio = time.perf_counter()
    cache = _ruta_cache(texto)
    desde_cache = bool(cache and cache.is_file() and cache.stat().st_size > 0)
    descriptor = None
    temporal = None
    if desde_cache:
        archivo = str(cache)
    else:
        descriptor, temporal = tempfile.mkstemp(prefix="jarvis_voz_", suffix=".mp3")
        os.close(descriptor)
        archivo = temporal
    try:
        inicio_tts = time.perf_counter()
        if not desde_cache:
            _ejecutar_async(_generar_audio_edge(texto, archivo))
            if cache:
                CACHE_VOZ_DIR.mkdir(exist_ok=True)
                os.replace(archivo, cache)
                archivo = str(cache)
                temporal = None
        tiempo_tts = time.perf_counter() - inicio_tts
        if not os.path.exists(archivo) or os.path.getsize(archivo) == 0:
            raise RuntimeError("Edge TTS no generó audio.")
        inicializar_audio()
        pygame.mixer.music.load(archivo)
        pygame.mixer.music.play()
        inicio_reproduccion = time.perf_counter()
        marca_voz = _ultimas_metricas.get("_ultimo_sonido_perf")
        metricas = {"tts": tiempo_tts, "hasta_reproduccion": inicio_reproduccion - inicio,
                    "cache_tts": desde_cache}
        if marca_voz is not None:
            metricas["total_hasta_hablar"] = inicio_reproduccion - marca_voz
        _registrar_metricas(**metricas)
        while pygame.mixer.music.get_busy() and not _evento_detener_voz.wait(0.05):
            pass
        pygame.mixer.music.stop()
        pygame.mixer.music.unload()
    finally:
        try:
            if temporal:
                os.remove(temporal)
        except OSError:
            pass


def _hablar_pyttsx3(texto):
    global _motor_voz
    import pyttsx3
    _motor_voz = pyttsx3.init()
    _motor_voz.setProperty("rate", VELOCIDAD_VOZ)
    _seleccionar_voz_espanol(_motor_voz)
    _motor_voz.say(texto)
    _motor_voz.runAndWait()


def hablar(texto):
    global _motor_voz
    with _bloqueo_voz:
        _evento_detener_voz.clear()
        texto_voz = preparar_texto_para_voz(texto)
        try:
            try:
                _hablar_edge(texto_voz)
                return "edge-tts"
            except Exception as error_edge:
                print(f"Edge TTS no disponible; usando pyttsx3: {error_edge}")
            try:
                _hablar_pyttsx3(texto_voz)
                return "pyttsx3"
            except Exception as error:
                print(f"Error técnico de pyttsx3: {error}")
                raise RuntimeError("No fue posible reproducir la respuesta por voz.") from error
        finally:
            _motor_voz = None


def detener_voz():
    _evento_detener_voz.set()
    try:
        import pygame
        if pygame.mixer.get_init():
            pygame.mixer.music.stop()
    except Exception:
        pass
    if _motor_voz is not None:
        try:
            _motor_voz.stop()
        except Exception:
            pass


def cerrar_audio():
    """Detiene la voz y libera el mezclador al cerrar la aplicación."""
    detener_voz()
    try:
        import pygame
        if pygame.mixer.get_init():
            pygame.mixer.quit()
    except Exception:
        pass
    global _bucle_async
    if _bucle_async is not None and _bucle_async.is_running():
        _bucle_async.call_soon_threadsafe(_bucle_async.stop)
    _bucle_async = None
