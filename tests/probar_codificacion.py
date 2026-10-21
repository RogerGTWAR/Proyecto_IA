"""Regresiones de Unicode sin red, dispositivos ni cambios de inventario."""
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools.verificar_codificacion import auditar, problemas_texto


class Codificacion(unittest.TestCase):
    def test_fuentes_utf8(self):
        self.assertEqual(auditar()['hallazgos'], [])

    def test_detecta_palabra_danada(self):
        self.assertTrue(problemas_texto('Autom' + '?' + 'tica'))
        self.assertTrue(problemas_texto('\u00c3\u00a1'))
        self.assertTrue(problemas_texto('\ufffd'))
        self.assertTrue(problemas_texto('?' + 'nicamente'))

    def test_conserva_preguntas_sql_y_urls(self):
        for texto in ('¿Dónde está? ¿Cuánto queda?', 'SELECT nombre WHERE id = ?',
                      'https://servidor/ruta?view=sql-server', 'wss://servidor?clave=valor'):
            self.assertEqual(problemas_texto(texto), [])

    def test_normalizacion_solo_comparacion(self):
        from jarvis.nlp_jarvis import normalizar_texto
        for a, b in (('último', 'ultimo'), ('cámara', 'camara'), ('predicción', 'prediccion')):
            self.assertEqual(normalizar_texto(a), normalizar_texto(b))

    def test_configuracion_preserva_unicode(self):
        from core import config_manager
        with tempfile.TemporaryDirectory() as carpeta:
            destino = Path(carpeta) / 'configuracion.json'
            with patch.object(config_manager, 'ARCHIVO', destino):
                config = config_manager.cargar_configuracion()
                config['general']['nombre'] = 'Inventario: Cámara, Predicción y Anomalías'
                config_manager.guardar_configuracion(config)
                texto = destino.read_text(encoding='utf-8')
                self.assertNotIn('\\u00', texto)
                self.assertEqual(json.loads(texto)['general']['nombre'], config['general']['nombre'])
                self.assertEqual(config_manager.cargar_configuracion()['general']['nombre'], config['general']['nombre'])

    def test_etiquetas_visibles(self):
        from jarvis import asistente_voz
        from ui import configuracion_ui
        self.assertIn('Síntesis de voz habilitada', str(configuracion_ui.CAMPOS))
        from core.system_state import ServiceState
        with patch('core.system_state.state_manager.get',return_value=ServiceState('TTS','ONLINE',True)):
            self.assertEqual(asistente_voz.obtener_estado_tts()['etiqueta'],'Voz: En línea')

    def test_salida_consola(self):
        import main
        datos = io.BytesIO()
        salida = io.TextIOWrapper(datos, encoding='ascii')
        with patch.object(main.sys, 'stdout', salida), patch.object(main.sys, 'stderr', salida), \
                patch('ui.interfaz.iniciar_aplicacion'), patch.object(main.Path, 'is_file', return_value=False):
            main.main()
            salida.write('Cámara · Predicción · Anomalía · Configuración')
            salida.flush()
        self.assertEqual(datos.getvalue().decode('utf-8'), 'Cámara · Predicción · Anomalía · Configuración')


if __name__ == '__main__':
    unittest.main()
