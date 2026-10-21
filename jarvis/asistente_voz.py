from core.paths import PROJECT_ROOT
import json
import asyncio
from concurrent.futures import TimeoutError as EsperaFuturo
import math
import struct
import hashlib
import os
import queue
import re
import tempfile
import threading
import time
from pathlib import Path

os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")


BASE_DIR = PROJECT_ROOT
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
_ultimo_motor_tts = None
_ultima_reproduccion_tts = None
_evento_detener_voz = threading.Event()
_ultimas_metricas = {}
_bucle_async = None
_hilo_async = None
_bloqueo_bucle = threading.Lock()
_cola_tts = queue.Queue()
_bloqueo_tts = threading.Lock()
_hilo_tts = None
_audio_cerrado = False
_generacion_tts = 0
edge_tts_disponible = True
tts_provider_actual = None
_voz_local_nombre = None
_error_com = False



class _VozCancelada(Exception):
    pass


def obtener_estado_tts():
    from core.config_manager import cargar_configuracion
    c = cargar_configuracion()['jarvis']
    from core.system_state import state_manager,format_service_state
    state=state_manager.get('TTS');etiqueta='Voz: '+format_service_state(state)['text']
    return {'proveedor': state.details.get('provider'), 'etiqueta': etiqueta,'estado':state.status,'available':state.available,
            'edge_disponible': edge_tts_disponible, 'voz_local': _voz_local_nombre,
            'habilitado': c['tts_habilitado'], 'ultima_reproduccion': _ultima_reproduccion_tts}


def _motivo_edge(error):
    # No convertir la excepción a texto: puede contener URLs y parámetros del servicio.
    estado = getattr(error, 'status', None)
    if isinstance(estado, int):
        return 'HTTP ' + str(estado)
    if isinstance(error, (TimeoutError, asyncio.TimeoutError)):
        return 'tiempo de espera agotado'
    return 'servicio o conexión no disponible'


def _deshabilitar_edge(error):
    global edge_tts_disponible, tts_provider_actual
    if edge_tts_disponible:
        edge_tts_disponible = False
        tts_provider_actual = 'pyttsx3'
        from core.system_state import state_manager
        previous=state_manager.get('TTS')
        local_ready=previous.available and previous.details.get('provider')=='pyttsx3'
        state_manager.update('TTS','DEGRADED','Edge no disponible; se utilizará respaldo local.',
            details={'edge_available':False},available=local_ready,expected=True)
        print('[TTS] Edge TTS no disponible: ' + _motivo_edge(error) + '. Se usará pyttsx3 durante esta sesión.')


def obtener_ruta_modelo():
    from core.config_manager import obtener,ruta as ruta_config
    ruta = (RUTA_MODELO_VOZ if obtener('jarvis','modelo_vosk')=='modelos_voz/vosk-model-small-es-0.42' else ruta_config('jarvis','modelo_vosk')).resolve()
    if ruta.suffix.lower() == ".zip":
        raise RuntimeError(f"El modelo debe estar descomprimido, no ser un ZIP:\n{ruta}")
    if not ruta.is_dir():
        raise RuntimeError(f"No se encontró el modelo de reconocimiento de voz en:\n{ruta}")
    faltantes = [nombre for nombre in ("am", "conf", "graph") if not (ruta / nombre).is_dir()]
    if faltantes:
        raise RuntimeError(f"El modelo de voz está incompleto en:\n{ruta}\nFaltan: {', '.join(faltantes)}.")
    return ruta


def _cargar_modelo_voz_impl():
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


def cargar_modelo_voz():
    from core.system_state import state_manager
    from core.config_manager import obtener
    if _modelo_voz is None:state_manager.update('VOSK','STARTING','Cargando modelo Vosk.',activity='INITIALIZING')
    try:
        model=_cargar_modelo_voz_impl()
    except Exception:
        state_manager.update('VOSK','ERROR','No se pudo cargar el modelo Vosk.',error='VOSK_LOAD_FAILED',activity='IDLE')
        raise
    state_manager.update('VOSK','ONLINE','Modelo Vosk cargado.',details={'modelo':obtener('jarvis','modelo_vosk'),'sample_rate':FRECUENCIA_MUESTREO},activity='IDLE')
    return model


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
        finally:
            from core.system_state import state_manager
            if state_manager.get('TTS').status=='STARTING':
                state_manager.update('TTS','UNVERIFIED','Pendiente de la primera reproducción.',expected=True)
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
        from core.config_manager import obtener
        elegido=obtener('jarvis','microfono')
        if elegido>=0: indice=elegido
        candidatos = []
        if indice is not None and int(indice) >= 0:
            candidatos.append(int(indice))
        candidatos.extend(i for i, d in enumerate(dispositivos)
                          if d["max_input_channels"] > 0 and i not in candidatos)
        if elegido>=0: candidatos=[elegido] if elegido<len(dispositivos) else []
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


class EscuchaSinTexto(RuntimeError):
    """Silencio o audio no reconocido; recuperable en el modo continuo."""


def extraer_consulta_activada(texto):
    """None: sin activación; cadena vacía: solo Jarvis; resto: consulta."""
    coincidencia = re.search(r"\b(?:jarvis|jarbis|yarvis)\b", texto, re.IGNORECASE)
    if coincidencia is None:
        return None
    return texto[coincidencia.end():].lstrip(" ,;:.").strip()


def _nivel_audio(bloque):
    muestras = struct.unpack("<" + "h" * (len(bloque) // 2), bloque)
    return math.sqrt(sum(m * m for m in muestras) / len(muestras)) if muestras else 0


def _escuchar_pregunta_impl(cancelar=None):
    if not _bloqueo_microfono.acquire(blocking=False):
        raise RuntimeError("El micrófono está siendo utilizado por otra escucha.")
    try:
        try:
            import sounddevice as sd
            from vosk import KaldiRecognizer
        except ImportError as error:
            raise RuntimeError("Las dependencias de voz no están instaladas.") from error
        if cancelar is not None and cancelar.is_set():
            return ""
        modelo = cargar_modelo_voz()
        if cancelar is not None and cancelar.is_set():
            return ""
        microfono = obtener_microfono_predeterminado()
        reconocedor = KaldiRecognizer(modelo, FRECUENCIA_MUESTREO)
        cola_audio = queue.Queue(maxsize=80)

        def recibir_audio(datos, cuadros, tiempo_audio, estado):
            if estado:
                print(f"Aviso de audio: {estado}")
            try:
                cola_audio.put_nowait(bytes(datos))
            except queue.Full:
                pass

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
                    if cancelar is not None and cancelar.is_set():
                        return ""
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
                    if voz_detectada and _nivel_audio(bloque) >= UMBRAL_VOZ:
                        ultimo_sonido = time.perf_counter()
                    if (voz_detectada and ultimo_sonido is not None and
                            time.perf_counter() - ultimo_sonido >= SILENCIO_FIN_FRASE):
                        marca_vosk = time.perf_counter()
                        texto = json.loads(reconocedor.FinalResult()).get("text", "").strip()
                        tiempo_vosk += time.perf_counter() - marca_vosk
                        if texto:
                            return finalizar_texto(texto)
                        raise EscuchaSinTexto("No pude entenderte. Intenta hablar nuevamente.")
        except sd.PortAudioError as error:
            print(f"Error técnico de sounddevice: {error}")
            raise RuntimeError("No fue posible utilizar el micrófono. Revisa los permisos, si está ocupado o si admite 16000 Hz.") from error
        marca_vosk = time.perf_counter()
        texto = json.loads(reconocedor.FinalResult()).get("text", "").strip()
        tiempo_vosk += time.perf_counter() - marca_vosk
        if not texto:
            raise EscuchaSinTexto("No pude entenderte. Intenta hablar nuevamente.")
        return finalizar_texto(texto)
    except RuntimeError:
        raise
    except Exception as error:
        raise RuntimeError("No fue posible reconocer el audio. Revisa el modelo Vosk y el micrófono.") from error
    finally:
        _bloqueo_microfono.release()


def escuchar_pregunta(cancelar=None):
    from core.system_state import state_manager
    state_manager.set_activity('JARVIS','LISTENING')
    try:return _escuchar_pregunta_impl(cancelar)
    finally:state_manager.set_activity('JARVIS','IDLE')


def _seleccionar_voz_espanol(motor):
    global _voz_local_nombre
    voces = list(motor.getProperty("voices") or [])
    seleccionada = next((v for v in voces if any(valor in
        f"{v.id} {v.name} {getattr(v, 'languages', '')}".lower()
                          for valor in ("spanish", "español", "_es", "es-", "es_", "\\x0aes"))), None)
    if seleccionada is not None:
        motor.setProperty("voice", seleccionada.id)
    actual = motor.getProperty("voice")
    voz = seleccionada or next((v for v in voces if v.id == actual), None)
    _voz_local_nombre = getattr(voz, 'name', None) or 'Voz predeterminada del sistema'
    return _voz_local_nombre


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
    from core.config_manager import obtener
    comunicacion = edge_tts.Communicate(texto, obtener('jarvis','voz'), rate=obtener('jarvis','tts_rate_edge'))
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
            pendientes = asyncio.all_tasks(bucle)
            for tarea in pendientes:
                tarea.cancel()
            if pendientes:
                bucle.run_until_complete(asyncio.gather(*pendientes, return_exceptions=True))
            bucle.close()
        _hilo_async = threading.Thread(target=ejecutar_bucle, daemon=True)
        _hilo_async.start()
        listo.wait(timeout=2)
        if _bucle_async is None:
            raise RuntimeError("No fue posible iniciar el generador de voz.")
        return _bucle_async


def _ejecutar_async(corutina):
    futuro = asyncio.run_coroutine_threadsafe(corutina, _obtener_bucle_async())
    limite = time.monotonic() + TTS_TIMEOUT + 1
    try:
        while True:
            if _evento_detener_voz.is_set():
                raise _VozCancelada()
            try:
                return futuro.result(timeout=0.05)
            except EsperaFuturo:
                if futuro.done():
                    return futuro.result()
                if time.monotonic() >= limite:
                    raise TimeoutError()
    except Exception:
        futuro.cancel()
        raise


def _ruta_cache(texto):
    if texto not in FRASES_CACHEABLES:
        return None
    from core.config_manager import obtener
    clave = hashlib.sha256(f"{obtener('jarvis','voz')}|{obtener('jarvis','tts_rate_edge')}|{texto}".encode("utf-8")).hexdigest()
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
        if _evento_detener_voz.is_set():
            raise _VozCancelada()
        inicializar_audio()
        pygame.mixer.music.load(archivo)
        from core.config_manager import obtener
        pygame.mixer.music.set_volume(obtener('jarvis','volumen'))
        if _evento_detener_voz.is_set():
            raise _VozCancelada()
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
    if _error_com:
        raise RuntimeError("No se pudo iniciar el audio de Windows.")
    import pyttsx3
    from core.config_manager import obtener
    if _motor_voz is None:
        _motor_voz = pyttsx3.init()
        _seleccionar_voz_espanol(_motor_voz)
    _motor_voz.setProperty("rate", obtener('jarvis', 'velocidad'))
    _motor_voz.setProperty("volume", obtener('jarvis', 'volumen'))
    if _evento_detener_voz.is_set():
        raise _VozCancelada()
    # El bucle externo permite detener SAPI en el mismo hilo que creó el motor.
    _motor_voz.say(texto)
    _motor_voz.startLoop(False)
    try:
        _motor_voz.iterate()
        while _motor_voz.isBusy():
            if _evento_detener_voz.wait(0.01):
                _motor_voz.stop()
                raise _VozCancelada()
            _motor_voz.iterate()
    finally:
        _motor_voz.endLoop()


def _reproducir_tts_impl(texto):
    global tts_provider_actual, _ultimo_motor_tts, _ultima_reproduccion_tts
    from datetime import datetime
    from core.config_manager import obtener
    if not obtener('jarvis', 'tts_habilitado') or not str(texto).strip():
        return None
    texto = preparar_texto_para_voz(texto)
    if obtener('jarvis', 'tts_provider_preferido') != 'local' and edge_tts_disponible:
        tts_provider_actual = 'edge_tts'
        try:
            _hablar_edge(texto)
            proveedor = 'edge-tts'
        except _VozCancelada:
            return None
        except Exception as error:
            _deshabilitar_edge(error)
            proveedor = None
    else:
        proveedor = None
    if proveedor is None:
        if _evento_detener_voz.is_set():
            return None
        tts_provider_actual = 'pyttsx3'
        try:
            _hablar_pyttsx3(texto)
            proveedor = 'pyttsx3'
        except _VozCancelada:
            return None
        except Exception:
            # La UI recibe únicamente una explicación sin detalles internos.
            raise RuntimeError('No fue posible reproducir la voz local. Revisa las voces y el dispositivo de salida de Windows.') from None
    if _evento_detener_voz.is_set():
        return None
    _ultimo_motor_tts = proveedor
    _ultima_reproduccion_tts = datetime.now()
    return proveedor


def _reproducir_tts(texto):
    from core.system_state import state_manager
    from core.config_manager import obtener
    if not obtener('jarvis','tts_habilitado'):
        state_manager.update('TTS','DISABLED','Voz deshabilitada.',expected=True)
        return None
    state_manager.set_activity('TTS','SPEAKING');state_manager.set_activity('JARVIS','SPEAKING')
    try:
        provider=_reproducir_tts_impl(texto)
        if provider:
            fallback=provider=='pyttsx3' and obtener('jarvis','tts_provider_preferido')!='local'
            state_manager.update('TTS','DEGRADED' if fallback else 'ONLINE',
                'Reproducción completada con respaldo local.' if fallback else 'Reproducción comprobada.',
                details={'provider':provider,'voice':_voz_local_nombre if provider=='pyttsx3' else obtener('jarvis','voz'),
                         'fallback':fallback,'edge_available':edge_tts_disponible},available=True)
        return provider
    except Exception:
        state_manager.update('TTS','OFFLINE','No se pudo reproducir audio con los motores disponibles.',error='TTS_PLAYBACK_FAILED')
        raise
    finally:
        state_manager.set_activity('TTS','IDLE');state_manager.set_activity('JARVIS','IDLE')


def _trabajador_tts():
    global _motor_voz, _error_com
    com = None
    try:
        if os.name == 'nt':
            try:
                import pythoncom
                pythoncom.CoInitialize()
                com = pythoncom
            except Exception:
                _error_com = True
        while True:
            solicitud = _cola_tts.get()
            if solicitud is None:
                break
            texto, generacion, listo, resultado = solicitud
            try:
    # Cancelar también frases pendientes al pulsar Detener voz.
                with _bloqueo_microfono, _bloqueo_voz:
                    with _bloqueo_tts:
                        if generacion != _generacion_tts or _audio_cerrado:
                            continue
                        _evento_detener_voz.clear()
                    resultado['valor'] = _reproducir_tts(texto)
            except Exception as error:
                resultado['error'] = error
            finally:
                listo.set()
    finally:
        if _motor_voz is not None:
            _motor_voz.stop()
            _motor_voz = None
        if com is not None:
            com.CoUninitialize()


def hablar(texto):
    """Encola una frase y espera su resultado; llamar desde un hilo de trabajo."""
    global _hilo_tts
    listo, resultado = threading.Event(), {}
    with _bloqueo_tts:
        if _audio_cerrado:
            return None
        if _hilo_tts is None or not _hilo_tts.is_alive():
            _hilo_tts = threading.Thread(target=_trabajador_tts, name='jarvis-tts', daemon=True)
            _hilo_tts.start()
        _cola_tts.put((texto, _generacion_tts, listo, resultado))
    listo.wait()
    if 'error' in resultado:
        raise resultado['error']
    return resultado.get('valor')


def detener_voz():
    global _generacion_tts
    with _bloqueo_tts:
        _generacion_tts += 1
        _evento_detener_voz.set()
    # El motor local se detiene exclusivamente desde su hilo propietario.


def diagnosticar_edge():
    """Sintetiza una frase aislada sin reproducirla ni cargar Vosk."""
    descriptor, archivo = tempfile.mkstemp(prefix='jarvis_diagnostico_', suffix='.mp3')
    os.close(descriptor)
    try:
        asyncio.run(_generar_audio_edge('Hola. Soy Jarvis.', archivo))
        if os.path.getsize(archivo) == 0:
            raise RuntimeError('Audio vacío')
        return {'disponible': True, 'bytes': os.path.getsize(archivo)}
    except Exception as error:
        _deshabilitar_edge(error)
        return {'disponible': False, 'motivo': _motivo_edge(error)}
    finally:
        Path(archivo).unlink(missing_ok=True)


def cerrar_audio():
    """Solicita el cierre sin esperar al motor en el hilo de Tkinter."""
    global _audio_cerrado
    detener_voz()
    with _bloqueo_tts:
        _audio_cerrado = True
        _cola_tts.put(None)
    # La limpieza de COM ocurre en el trabajador; asyncio se cierra después de cancelar.
    def liberar():
        if _hilo_tts is not None:
            _hilo_tts.join(timeout=TTS_TIMEOUT + 2)
        try:
            import pygame
            if pygame.mixer.get_init():
                pygame.mixer.quit()
        except Exception:
            pass
        if _bucle_async is not None and _bucle_async.is_running():
            _bucle_async.call_soon_threadsafe(_bucle_async.stop)
    threading.Thread(target=liberar, name='jarvis-audio-cierre', daemon=True).start()
