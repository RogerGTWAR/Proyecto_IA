"""Regresión de coordinación de voz sin micrófono, SQL ni ventana visible.
Los dobles solo pertenecen a estas pruebas; producción conserva el agente real.
"""

import sys
from pathlib import Path as _RutaProyecto
_RAIZ_PROYECTO = _RutaProyecto(__file__).resolve().parents[1]
if str(_RAIZ_PROYECTO) not in sys.path:
    sys.path.insert(0, str(_RAIZ_PROYECTO))

import ast
import json
import queue
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

from jarvis import asistente_voz as voz
from ui.ui_theme import COLORES

CONSULTAS = (
    "¿Cuántos motores quedan?", "¿Dónde están los tornillos?",
    "¿Qué productos tienen stock bajo?", "¿Cuántos filtros hay?",
    "Muéstrame los últimos movimientos.", "¿Cuál es el producto con menor existencia?",
)


class Control:
    def __init__(self, valor=None):
        self.valor = valor
        self.opciones = {}
        self.mensajes = []
    def get(self):
        return self.valor
    def set(self, valor):
        self.valor = valor
    def configure(self, *args, **kwargs):
        self.opciones.update(kwargs)
    def insert(self, *args):
        self.mensajes.append(args[1])
    def agregar(self, autor, texto):
        self.mensajes.append(texto + "\n\n")
    def limpiar(self):
        self.mensajes.clear()
    def delete(self, *args):
        self.valor = ""
    def see(self, *args):
        pass
    def focus_set(self):
        pass
    def after(self, *args):
        # El test llama explícitamente al consumidor desde su hilo principal.
        pass


def crear_interfaz_prueba():
    arbol = ast.parse((_RAIZ_PROYECTO / 'ui/interfaz.py').read_text(encoding="utf-8"))
    inicio = next(n for n in arbol.body if isinstance(n, ast.FunctionDef) and n.name == "iniciar_aplicacion")
    funciones = []
    activa = False
    for n in inicio.body:
        if isinstance(n, ast.FunctionDef) and n.name == "procesar_con_metricas":
            activa = True
        if isinstance(n, ast.FunctionDef) and n.name == "gestionar_placeholder":
            break
        if activa and isinstance(n, ast.FunctionDef):
            funciones.append(n)
    entorno = dict(queue=queue, threading=threading, hilo_de_sesion=threading.Thread, time=time, COLORES=COLORES,
                   tk=type("Tk", (), {"END": "end"}),
                   eventos_jarvis=queue.Queue(), cancelar_escucha=threading.Event(),
                   aplicacion_cerrando={"valor": False}, esperando_pregunta={"valor": False},
                   control_voz={"escuchando": False, "procesando": False, "hablando": False,
                                "hilo_escucha": None, "hilo_trabajo": None},
                   colores_estado={}, texto_placeholder="Escribe un mensaje para Jarvis...",
                   EscuchaSinTexto=voz.EscuchaSinTexto,
                   extraer_consulta_activada=voz.extraer_consulta_activada,
                   registrar_tiempo_jarvis=lambda _: None, reiniciar_contexto=lambda: None)
    for nombre in ("ventana", "conversacion", "etiqueta_estado", "boton_hablar",
                   "boton_enviar", "boton_reiniciar", "boton_detener", "estado_agente",
                   "texto_pregunta", "pregunta_agente"):
        entorno[nombre] = Control("")
    entorno["modo_asistente"] = Control(False)
    entorno["responder_con_voz"] = Control(True)
    entorno['badges']={'JARVIS':Control('')}
    exec(compile(ast.Module(body=funciones, type_ignores=[]), 'ui/interfaz.py', "exec"), entorno)
    return entorno


class IntegracionVoz(unittest.TestCase):
    def setUp(self):
        self.ui = crear_interfaz_prueba()
        self.consultas = []
        self.habladas = []
        self.ui["procesar_consulta"] = lambda texto,estructurada=False: self.consultas.append(texto) or {"respuesta":"respuesta de prueba","voz":"respuesta de prueba","acciones_ui":[]}
        self.ui["hablar"] = self.habladas.append

    def test_accion_opcional_de_mapa_se_ejecuta_solo_al_pulsarla(self):
        self.ui['responder_con_voz'].set(False)
        self.ui['mostrar_producto_en_mapa']=MagicMock()
        self.ui['conversacion'].agregar=MagicMock()
        for producto in (1,2):
            self.ui['eventos_jarvis'].put(('respuesta',{'respuesta':'Ubicación consultada.',
                'acciones_ui':[],'acciones_opcionales':[{'tipo':'producto_mapa','id':producto}]}))
            self.ui['consumir_eventos_jarvis']()
        self.ui['mostrar_producto_en_mapa'].assert_not_called()
        # El botón conserva el producto de su propia respuesta, aunque llegue otro mensaje.
        botones=self.ui['conversacion'].agregar.call_args_list[0].args[2]
        self.assertEqual(botones[0][0],'Ver en mapa')
        botones[0][1]()
        self.ui['mostrar_producto_en_mapa'].assert_called_once_with(1)

    def esperar(self, condicion):
        limite = time.monotonic() + 2
        while time.monotonic() < limite:
            self.ui["consumir_eventos_jarvis"]()
            if condicion():
                return
            time.sleep(0.005)
        self.fail("El flujo no terminó dentro del tiempo esperado")

    def test_seis_consultas_voz_y_texto_comparten_ruta(self):
        for pregunta in CONSULTAS:
            self.ui["escuchar_pregunta"] = lambda cancelar, p=pregunta: p
            self.ui["hablar_una_vez"]()
            self.esperar(lambda: not self.ui["ocupado"]())
            self.assertEqual(self.consultas[-1], pregunta)
            self.assertEqual(self.habladas[-1], "respuesta de prueba")
            self.assertIn(pregunta + "\n\n", self.ui["conversacion"].mensajes)
            self.ui["pregunta_agente"].set(pregunta)
            self.ui["enviar_pregunta"]()
            self.esperar(lambda: not self.ui["ocupado"]())
            self.assertEqual(self.consultas[-2:], [pregunta, pregunta])
        self.assertEqual(self.ui["boton_hablar"].opciones["text"], "🎤 Hablar")

    def test_nueva_consulta_interrumpe_tts_sin_activar_microfono(self):
        liberar=threading.Event()
        self.ui['hablar']=lambda texto:liberar.wait(1)
        self.ui['detener_voz']=liberar.set
        self.ui['enviar_consulta']('stock de motores')
        self.esperar(lambda:self.ui['control_voz']['hablando'])
        self.ui['enviar_consulta']('¿Dónde están?')
        self.esperar(lambda:len(self.consultas)==2 and not self.ui['ocupado']())
        self.assertEqual(self.consultas,['stock de motores','¿Dónde están?'])
        self.assertFalse(self.ui['control_voz']['escuchando'])

    def test_no_escucha_durante_respuesta_ni_doble_activacion(self):
        liberar = threading.Event()
        llamadas = []
        def escuchar(cancelar):
            llamadas.append(1)
            liberar.wait(1)
            return CONSULTAS[0]
        self.ui["escuchar_pregunta"] = escuchar
        self.ui["hablar_una_vez"]()
        self.ui["hablar_una_vez"]()
        self.assertEqual(len(llamadas), 1)
        liberar.set()
        self.esperar(lambda: not self.ui["ocupado"]())
        self.ui["control_voz"]["hablando"] = True
        self.ui["hablar_una_vez"]()
        self.assertEqual(len(llamadas), 1)

    def test_activacion_con_consulta_en_misma_frase(self):
        self.ui["modo_asistente"].set(True)
        self.ui["control_voz"]["escuchando"] = True
        self.ui["eventos_jarvis"].put(("texto_voz", ("Jarvis, " + CONSULTAS[1], True, False)))
        self.ui["consumir_eventos_jarvis"]()
        self.ui["modo_asistente"].set(False)
        self.esperar(lambda: not self.ui["ocupado"]())
        self.assertEqual(self.consultas, [CONSULTAS[1]])

    def test_error_tts_conserva_respuesta_y_rehabilita_microfono(self):
        def fallar(_):
            raise RuntimeError("No fue posible reproducir la respuesta por voz.")
        self.ui["hablar"] = fallar
        self.ui["enviar_consulta"](CONSULTAS[0])
        self.esperar(lambda: not self.ui["ocupado"]())
        self.assertIn("respuesta de prueba\n\n", self.ui["conversacion"].mensajes)
        self.assertIn("No fue posible reproducir la respuesta por voz.\n\n", self.ui["conversacion"].mensajes)
        self.assertEqual(self.ui["boton_hablar"].opciones["state"], "normal")

    def test_cancelacion_descarta_texto_y_rehabilita_control(self):
        self.ui["control_voz"]["escuchando"] = True
        self.ui["eventos_jarvis"].put(("texto_voz", (CONSULTAS[0], True, True)))
        self.ui["consumir_eventos_jarvis"]()
        self.assertEqual(self.consultas, [])
        self.assertFalse(self.ui["ocupado"]())

    def test_silencio_continuo_reintenta_error_de_dispositivo_detiene(self):
        llamadas = []
        self.ui["iniciar_escucha"] = lambda continua: llamadas.append(continua)
        self.ui["modo_asistente"].set(True)
        self.ui["eventos_jarvis"].put(("silencio", ("silencio", True, False)))
        self.ui["consumir_eventos_jarvis"]()
        self.assertEqual(llamadas, [True])
        self.ui["eventos_jarvis"].put(("error_escucha", ("No se encontró un micrófono disponible.", True, False)))
        self.ui["consumir_eventos_jarvis"]()
        self.assertFalse(self.ui["modo_asistente"].get())
        self.assertEqual(len(llamadas), 1)


class Reconocimiento(unittest.TestCase):
    def test_activacion_respeta_palabra_y_pregunta(self):
        self.assertIsNone(voz.extraer_consulta_activada("objetos jarvisianos"))
        self.assertEqual(voz.extraer_consulta_activada("Hola Jarvis"), "")
        for consulta in CONSULTAS:
            self.assertEqual(voz.extraer_consulta_activada("Jarvis, " + consulta), consulta)

    def test_cancelacion_libera_bloqueo(self):
        cancelar = threading.Event()
        cancelar.set()
        self.assertEqual(voz.escuchar_pregunta(cancelar=cancelar), "")
        self.assertTrue(voz._bloqueo_microfono.acquire(blocking=False))
        voz._bloqueo_microfono.release()

    def test_microfono_exclusivo(self):
        with voz._bloqueo_microfono:
            with self.assertRaisesRegex(RuntimeError, "otra escucha"):
                voz.escuchar_pregunta()


class CapturaAudio(unittest.TestCase):
    def test_stream_se_cierra_al_reconocer(self):
        import sounddevice
        import vosk
        stream = MagicMock()
        recognizer = MagicMock()
        recognizer.AcceptWaveform.return_value = True
        recognizer.Result.return_value = json.dumps({"text": CONSULTAS[0]})
        def abrir(**kwargs):
            kwargs["callback"](b"\0\0" * 100, 100, None, None)
            return stream
        with patch.object(voz, "cargar_modelo_voz"), \
             patch.object(voz, "obtener_microfono_predeterminado", return_value={"indice": 0}), \
             patch.object(vosk, "KaldiRecognizer", return_value=recognizer), \
             patch.object(sounddevice, "RawInputStream", side_effect=abrir):
            self.assertEqual(voz.escuchar_pregunta(), CONSULTAS[0])
        stream.__exit__.assert_called_once()
        self.assertFalse(voz._bloqueo_microfono.locked())

    def test_stream_se_cierra_al_cancelar(self):
        import sounddevice
        import vosk
        cancelar = threading.Event()
        stream = MagicMock()
        stream.__enter__.side_effect = lambda: cancelar.set()
        with patch.object(voz, "cargar_modelo_voz"), \
             patch.object(voz, "obtener_microfono_predeterminado", return_value={"indice": 0}), \
             patch.object(vosk, "KaldiRecognizer"), \
             patch.object(sounddevice, "RawInputStream", return_value=stream):
            self.assertEqual(voz.escuchar_pregunta(cancelar=cancelar), "")
        stream.__exit__.assert_called_once()
        self.assertFalse(voz._bloqueo_microfono.locked())

    def test_timeout_silencio_libera_stream(self):
        import sounddevice
        import vosk
        stream = MagicMock()
        recognizer = MagicMock()
        recognizer.FinalResult.return_value = '{"text": ""}'
        with patch.object(voz, "cargar_modelo_voz"), \
             patch.object(voz, "obtener_microfono_predeterminado", return_value={"indice": 0}), \
             patch.object(vosk, "KaldiRecognizer", return_value=recognizer), \
             patch.object(sounddevice, "RawInputStream", return_value=stream), \
             patch.object(voz, "TIEMPO_MAXIMO_ESCUCHA", 0):
            with self.assertRaises(voz.EscuchaSinTexto):
                voz.escuchar_pregunta()
        stream.__exit__.assert_called_once()
        self.assertFalse(voz._bloqueo_microfono.locked())

    def test_dispositivo_ocupado_libera_bloqueo(self):
        import sounddevice
        import vosk
        with patch.object(voz, "cargar_modelo_voz"), \
             patch.object(voz, "obtener_microfono_predeterminado", return_value={"indice": 0}), \
             patch.object(vosk, "KaldiRecognizer"), \
             patch.object(sounddevice, "RawInputStream", side_effect=sounddevice.PortAudioError("ocupado")):
            with self.assertRaisesRegex(RuntimeError, "permisos"):
                voz.escuchar_pregunta()
        self.assertFalse(voz._bloqueo_microfono.locked())


class ConsultasAgente(unittest.TestCase):
    def test_consultas_solicitadas_se_interpretan(self):
        from jarvis.agente_inventario import detectar_intencion
        esperadas = ("consultar_stock", "consultar_ubicacion", "stock_bajo",
                     "consultar_stock", "consultar_movimientos", "producto_menor_stock")
        for consulta, esperada in zip(CONSULTAS, esperadas):
            with self.subTest(consulta=consulta):
                self.assertEqual(detectar_intencion(consulta), esperada)

    def test_movimientos_recientes_usan_funcion_existente(self):
        from jarvis import agente_inventario as agente
        with patch.object(agente, "interpretar_con_llm", return_value=(None, 0, "sin servicio")), \
             patch('inventory.movimientos.buscar_movimientos', return_value=[]) as herramienta:
            self.assertIn('No hay registros',agente.procesar_consulta(CONSULTAS[4]))
            herramienta.assert_called_once_with(id_producto=None,id_empleado=None,fecha_desde=None,fecha_hasta=None,tipo_movimiento=None)


if __name__ == "__main__":
    unittest.main(verbosity=2)
