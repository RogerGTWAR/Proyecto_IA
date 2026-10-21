"""Contrato central y flujos obligatorios; sin escrituras, red ni dispositivos."""
import unittest
from unittest.mock import patch
from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
import tests.probar_orquestador_jarvis as montaje
from jarvis import agente_inventario as agente
from jarvis import jarvis
from jarvis import jarvis_consultas as datos
from jarvis import herramientas_jarvis as servicios
_ESTADO_REAL=datos.estado


class CerebroCentral(montaje.Orquestador):
    def setUp(self):
        super().setUp()
        from tests.probar_system_state import aislar_estado
        aislar_estado(self)
        agente.reiniciar_contexto('telegram:cerebro')

    def turno(self, texto, origen='desktop', sesion='desktop', **kw):
        return jarvis.procesar(texto, sesion, origen, **kw)

    def test_contrato_y_canales(self):
        r = self.turno('¿Dónde está Tornillo M8?')
        self.assertIsInstance(r, jarvis.JarvisResult)
        self.assertTrue(r.ok);self.assertFalse(r.requiere_confirmacion)
        self.assertFalse(r.extras['acciones_ui'])
        self.assertIs(agente.obtener_contexto('desktop'), agente.obtener_contexto('escritorio'))
        self.assertIn('43', self.turno('¿Cuánto tiene?', 'voz').respuesta)
        self.assertIsNone(agente.obtener_contexto('telegram:cerebro')['producto_actual'])
        self.turno('¿Dónde está Filtro de aceite?', 'telegram', 'telegram:cerebro')
        self.assertEqual(agente.obtener_contexto('telegram:cerebro')['producto_actual'], 2)
        self.assertEqual(agente.obtener_contexto('desktop')['producto_actual'], 1)

    def test_todas_las_consultas_obligatorias(self):
        casos = ('¿Cuántos productos hay?', '¿Cuál tiene mayor stock?', '¿Cuál tiene menor stock?',
            '¿Dónde está Tornillo M8?', 'Muéstramelo en el mapa.',
            '¿Cuál fue el último movimiento?', '¿Quién hizo el último movimiento?',
            '¿Qué producto movió?', '¿Cuál fue la última salida?',
            '¿Cuántos empleados hay?', '¿Quién fue el último empleado agregado?',
            '¿Quién ha realizado más movimientos?', '¿Tengo alertas?', '¿Cuántas críticas?',
            '¿Cuál es la más reciente?', '¿Hay anomalías?', '¿Cuál fue la última?',
            '¿Por qué fue una anomalía?', '¿Qué productos están en riesgo?',
            '¿Tornillo M8 se va a acabar?', '¿Está funcionando Telegram?',
            '¿La cámara está activa?', '¿Todo está funcionando?', 'Hola Jarvis', 'Qué nota', 'Gracias')
        for texto in casos:
            with self.subTest(texto=texto):
                r = self.turno(texto)
                self.assertNotIn(r.intent, ('error','desconocida'), r.respuesta)
                self.assertTrue(r.respuesta)

    def test_contexto_movimiento_autor_y_led(self):
        with patch('integrations.arduino.led_service.servicio_led.por_producto', return_value={'mensaje':'LED confirmado.'}) as led:
            for texto in ('¿Dónde está Tornillo M8?', '¿Cuánto tiene?', '¿Cuál fue su último movimiento?', '¿Quién lo hizo?', 'Enciende su luz.'):
                r = self.turno(texto)
                self.assertNotIn(r.intent, ('error','desconocida'), r.respuesta)
            led.assert_called_once_with(1, True)
            self.assertEqual(agente.obtener_contexto()['movimiento_actual']['id_movimiento'], 12)

    def test_pendiente_y_desambiguacion(self):
        self.turno('Ubicación')
        self.assertIsNotNone(agente.obtener_contexto()['pending_intent'])
        self.assertEqual(self.turno('Filtro de aceite').intent, 'consultar_ubicacion')
        self.ps.append(dict(self.ps[1], id_producto=3, codigo='FIL-002', nombre='Filtro de aire'))
        r = self.turno('Busca filtro')
        self.assertTrue(r.requiere_aclaracion)
        self.assertIn('Filtro de aire', r.respuesta)
        self.assertIn('Filtro de aire', self.turno('2').respuesta)

    def test_compuestas_y_no_duplicar_eventos(self):
        for texto in ('¿Dónde está Tornillo M8 y cuánto stock tiene?',
                      '¿Cuál fue su último movimiento y quién lo hizo?',
                      '¿Cuántos productos están bajos y cuáles son?',
                      '¿Hay anomalías o alertas críticas?'):
            r = self.turno(texto)
            self.assertNotIn(r.intent, ('error','desconocida'), r.respuesta)
        self.assertEqual(r.intent, 'alertas_y_anomalias')
        self.assertIn('alertas', r.datos);self.assertIn('anomalias',r.datos)

    def test_salida_confirmada_una_sola_vez(self):
        with patch('inventory.movimientos.registrar_salida', return_value=1001) as salida:
            r = self.turno('Registra una salida de 5 Tornillos M8.')
            self.assertTrue(r.requiere_aclaracion);salida.assert_not_called()
            r = self.turno('EMP-008')
            self.assertTrue(r.requiere_confirmacion);salida.assert_not_called()
            r = self.turno('Sí.')
            self.assertEqual(r.intent, 'accion_confirmada');salida.assert_called_once()
            self.assertEqual(salida.call_args.args[:4], (8,1,4,5))
            self.assertEqual(r.accion_ejecutada['accion'], 'registrar_salida')
            self.assertIsNone(agente.obtener_contexto()['pending_confirmation'])
            self.turno('Sí.');salida.assert_called_once()

    def test_cancelaciones_y_cambio_de_pregunta(self):
        with patch('inventory.movimientos.registrar_salida') as salida:
            for cancelacion in ('no','Cancelar.','Olvídalo.','Mejor no.'):
                self.turno('Registra una salida de 5 TOR-001 por EMP-008')
                self.assertEqual(self.turno(cancelacion).intent, 'cancelar_consulta')
                self.turno('sí')
            self.turno('Registra una salida de 5 TOR-001')
            self.turno('¿Cuántos empleados hay?');self.turno('EMP-008');self.turno('sí')
            salida.assert_not_called()

    def test_entrada_transferencia_reutilizan_servicios(self):
        ubicaciones=[dict(self.us[0]), dict(self.us[0],id_ubicacion=5,codigo_ubicacion='E05-N01')]
        with patch.object(datos,'ubicaciones',return_value=ubicaciones), \
             patch('inventory.movimientos.registrar_entrada',return_value=1002) as entrada, \
             patch('inventory.movimientos.registrar_transferencia',return_value=1003) as transferencia:
            for texto, fn in (('Registra entrada de 3 TOR-001 en E05-N01 por EMP-008', entrada),
                               ('Registra transferencia de 5 TOR-001 de E04-N01 a E05-N01 por EMP-008', transferencia)):
                r=self.turno(texto);self.assertTrue(r.requiere_confirmacion,r.respuesta);fn.assert_not_called()
                self.assertEqual(self.turno('sí').intent, 'accion_confirmada');fn.assert_called_once()

    def test_confirmacion_caduca_cambia_stock_y_error_no_reintenta(self):
        with patch('inventory.movimientos.registrar_salida', side_effect=RuntimeError('fallo interno')) as salida:
            self.turno('Registra salida de 5 TOR-001 por EMP-008')
            agente.obtener_contexto()['pending_confirmation']['vence']=0
            self.assertEqual(self.turno('sí').intent,'confirmacion_vencida');salida.assert_not_called()
            self.turno('Registra salida de 5 TOR-001 por EMP-008')
            self.us[0]['cantidad']=40
            self.assertEqual(self.turno('sí').intent,'aclaracion');salida.assert_not_called()
            self.turno('Registra salida de 5 TOR-001 por EMP-008')
            self.assertEqual(self.turno('sí').intent,'error')
            self.turno('sí');salida.assert_called_once()

    def test_eventos_repetidos_y_confirmaciones_concurrentes(self):
        with patch('inventory.movimientos.registrar_salida',return_value=1004) as salida:
            self.turno('Registra salida de 5 TOR-001 por EMP-008')
            with ThreadPoolExecutor(max_workers=2) as pool:
                rs=list(pool.map(lambda _:self.turno('sí',event_id='evento-1'),range(2)))
            salida.assert_called_once()
            self.assertEqual(rs[0].respuesta,rs[1].respuesta)

    def test_herramienta_sensible_bloqueada_fuera_de_confirmacion(self):
        from jarvis.tools import instalar
        instalar()
        with self.assertRaises(ValueError):
            servicios.ejecutar('registrar_salida', {'datos':{}})

    def test_catalogo_incluye_parametros_requeridos_por_todos_los_adaptadores(self):
        import inspect
        from jarvis.tools import catalogo
        catalogo()
        for nombre,h in servicios.REGISTRO_HERRAMIENTAS.items():
            requeridos={p.name for p in inspect.signature(h.funcion).parameters.values()
                        if p.default is inspect.Parameter.empty and p.kind in
                        (p.POSITIONAL_ONLY,p.POSITIONAL_OR_KEYWORD,p.KEYWORD_ONLY)}
            self.assertTrue(requeridos.issubset(h.parametros), nombre)

    def test_reportes_exportan_y_prediccion_no_inventa(self):
        with patch.object(datos,'vista_reporte',return_value=({'filas':[]},'reportes/Inventario.pdf')) as reporte:
            r=self.turno('Genera un reporte de inventario')
            self.assertIn('reportes/Inventario.pdf',r.respuesta)
            self.assertEqual(reporte.call_args.kwargs['formato'],'PDF')
        with patch.object(servicios,'datos_prediccion',return_value={'datos_suficientes':False,'mensaje':'Historial insuficiente.'}):
            self.assertIn('No hay una predicción calculada',self.turno('Tornillo M8 se va a acabar').respuesta)

    def test_social_no_toca_servicios(self):
        with patch.object(servicios,'datos_inventario') as productos:
            for texto in ('Hola','Qué nota','Cómo estás','Gracias','Qué puedes hacer'):
                self.assertTrue(self.turno(texto).respuesta)
            productos.assert_not_called()

    def test_resumen_critico_y_conversacion_final(self):
        from core.event_bus import EventBus
        from core.system_event import SystemEvent
        bus=EventBus()
        bus.publish(SystemEvent('STOCK_AGOTADO','INVENTARIO','stock','Producto agotado',
                    'Filtro de aceite sin existencias.',severity='CRITICA'))
        with patch('jarvis.tools.eventos.event_store',bus.store):
            r=self.turno('¿Hay algo crítico?')
            self.assertIn('Filtro de aceite',r.respuesta)
            self.assertEqual(r.datos['eventos'][0]['type'],'STOCK_AGOTADO')
        agotado=dict(self.us[0],id_ubicacion=6,codigo_ubicacion='E01-N02',estante='01',nivel='02',cantidad=0)
        with patch.object(servicios,'datos_ubicaciones',side_effect=lambda i:deepcopy([agotado] if i==2 else self.us)):
            for texto in ('¿Qué producto está agotado?', '¿Dónde está?', 'Muéstramelo en el mapa.'):
                r=self.turno(texto)
                self.assertNotIn(r.intent,('error','desconocida'),r.respuesta)
        self.assertEqual(r.extras['acciones_ui'],[{'tipo':'producto_mapa','id':2}])

    def test_faciales_no_confunden_rostro_no_visible_con_desconocido(self):
        import json
        from datetime import datetime
        eventos=[{'reconocido':False,'estado_identidad':'ROSTRO_NO_VISIBLE'},
                 {'reconocido':False,'estado_identidad':'NO_RECONOCIDO','motor_facial':'SFace'}]
        with patch('inventory.inventario_service.consultar',return_value=[{'contenido':json.dumps({'datos':e}),'fecha_creacion':datetime(2026,10,18)} for e in eventos]):
            self.assertEqual(len(datos.facial({'identidad':'desconocida'})),1)

    def test_contar_conserva_nivel_y_stock_por_ubicacion_no_usa_producto_anterior(self):
        self.al.append(dict(self.al[0],id_alerta=5,nivel='Alta',mensaje='Otro evento.'))
        self.turno('Tengo alertas')
        r=self.turno('Cuántas críticas');self.assertEqual(r.datos['total'],1)
        r=self.turno('Cuál es la más reciente');self.assertIn('Sin existencias',r.respuesta)
        self.assertNotIn('Otro evento',r.respuesta)
        self.turno('Dónde está Tornillo M8')
        with patch.dict(datos.LECTURAS,{'ubicaciones':lambda filtros:self.us}), \
             patch('inventory.mapa_almacen.productos_ubicacion',return_value=[dict(unidad_medida='Unidad',cantidad=43)]):
            r=self.turno('stock por ubicación');self.assertEqual(r.intent,'stock_por_ubicacion')

    def test_estados_no_activan_hardware_ni_anuncian_voz_sin_comprobar(self):
        with patch('core.estado_sistema.probar_base',return_value={'estado':'ONLINE'}), \
             patch('integrations.telegram.telegram_service.estado_telegram',return_value={'estado':'SIN VERIFICAR'}), \
             patch('surveillance.vigilancia_yolo.servicio_vigilancia.obtener_estado',return_value={'activo':False}), \
             patch('jarvis.asistente_voz.obtener_estado_tts',return_value={'habilitado':True,'ultima_reproduccion':False}), \
             patch('jarvis.asistente_voz.obtener_ruta_modelo',side_effect=RuntimeError()), \
             patch('integrations.arduino.led_service.servicio_led.estado_conexion',return_value={'estado':'Simulación activa'}), \
             patch('surveillance.camara_utils.CamaraUltimoFrame') as camara:
            r=_ESTADO_REAL()
            self.assertEqual(r['TTS'],'Sin verificar')
            self.assertEqual(r['Vosk'],'Sin verificar')
            camara.assert_not_called()


def load_tests(loader, tests, pattern):
    return unittest.TestSuite(CerebroCentral(nombre) for nombre in CerebroCentral.__dict__ if nombre.startswith('test_'))
