import json
import asyncio
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

_modelo_voz = None
_bloqueo_microfono = threading.Lock()
_bloqueo_voz = threading.Lock()
_motor_voz = None
_evento_detener_voz = threading.Event()


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

        inicio = time.monotonic()
        try:
            with sd.RawInputStream(device=microfono["indice"], samplerate=FRECUENCIA_MUESTREO,
                                   blocksize=8000, dtype="int16", channels=1,
                                   callback=recibir_audio):
                while time.monotonic() - inicio < TIEMPO_MAXIMO_ESCUCHA:
                    try:
                        bloque = cola_audio.get(timeout=0.5)
                    except queue.Empty:
                        continue
                    if reconocedor.AcceptWaveform(bloque):
                        texto = json.loads(reconocedor.Result()).get("text", "").strip()
                        if texto:
                            return texto
        except sd.PortAudioError as error:
            print(f"Error técnico de sounddevice: {error}")
            raise RuntimeError("No fue posible utilizar el micrófono. Puede estar ocupado o no admitir 16000 Hz.") from error
        texto = json.loads(reconocedor.FinalResult()).get("text", "").strip()
        if not texto:
            raise RuntimeError("No pude entender lo que dijiste. Intenta nuevamente.")
        return texto
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
    await edge_tts.Communicate(texto, VOZ_EDGE).save(archivo)


def _hablar_edge(texto):
    import pygame
    descriptor, archivo = tempfile.mkstemp(prefix="inventario_voz_", suffix=".mp3")
    os.close(descriptor)
    try:
        asyncio.run(_generar_audio_edge(texto, archivo))
        if not os.path.exists(archivo) or os.path.getsize(archivo) == 0:
            raise RuntimeError("Edge TTS no generó audio.")
        if not pygame.mixer.get_init():
            pygame.mixer.init()
        pygame.mixer.music.load(archivo)
        pygame.mixer.music.play()
        while pygame.mixer.music.get_busy() and not _evento_detener_voz.wait(0.05):
            pass
        pygame.mixer.music.stop()
        pygame.mixer.music.unload()
    finally:
        try:
            os.remove(archivo)
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
