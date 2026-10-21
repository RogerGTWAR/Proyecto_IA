"""Listener y conversaciones sin consumir actualizaciones ni publicar en Telegram."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import Mock,patch

from integrations.telegram import telegram_bot_service as bot
from integrations.telegram import telegram_service as envio
from core.config_manager import DEFAULTS


def actualizacion(texto='/jarvis',chat=1234,numero=1):
    return {'update_id':numero,'message':{'message_id':numero,'date':1,'chat':{'id':chat},
        'from':{'is_bot':False},'text':texto}}


class EntradaTelegram(unittest.TestCase):
    def setUp(self):
        self.s=bot.TelegramBotService()
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.s.ruta_cursor=Path(self.tmp.name)/'cursor.json'
        for destino in ('integrations.telegram.telegram_bot_service._credenciales','integrations.telegram.telegram_service._credenciales'):
            p=patch(destino,return_value=('token-local-no-real','1234'));p.start();self.addCleanup(p.stop)
        respuesta=patch.object(bot,'enviar_respuesta_chat',return_value={'enviado':True})
        self.responder=respuesta.start();self.addCleanup(respuesta.stop)

    def mensaje(self,texto,chat=1234):return self.s.procesar_actualizacion(actualizacion(texto,chat))

    def test_start_help_y_modo_desactivado(self):
        for texto in ('/start','/help'):
            self.mensaje(texto)
            self.assertIn('Soy JARVIS' if texto=='/start' else '/presentes',self.responder.call_args.args[1])
        with patch('jarvis.agente_inventario.procesar_consulta') as agente:
            self.mensaje('¿Qué stock hay?');agente.assert_not_called()
            self.assertIn('/jarvis',self.responder.call_args.args[1])

    def test_activar_y_salir_no_toca_notificaciones(self):
        with patch.object(bot.servicio_telegram,'cerrar') as cerrar,patch('jarvis.agente_inventario.reiniciar_contexto') as limpiar:
            self.mensaje('/jarvis')
            self.assertEqual(self.responder.call_args.args[1],'JARVIS en línea. Adelante, ¿qué necesitas consultar?')
            self.assertTrue(self.s.sessions['1234']['modo_jarvis'])
            self.mensaje('/salir')
            self.assertFalse(self.s.sessions['1234']['modo_jarvis'])
            limpiar.assert_called_once_with('telegram:1234');cerrar.assert_not_called()
            self.assertIn('seguiré pendiente de las alertas del sistema.',self.responder.call_args.args[1])

    def test_frases_naturales(self):
        for frase in ('Hablar con Jarvis','Quiero hablar con Jarvis','Activar Jarvis'):
            self.mensaje(frase);self.assertTrue(self.s.sessions['1234']['modo_jarvis'])
        with patch('jarvis.agente_inventario.reiniciar_contexto'):
            for frase in ('Salir de Jarvis','Dejar de hablar con Jarvis'):
                self.mensaje(frase);self.assertFalse(self.s.sessions['1234']['modo_jarvis'])

    def test_otro_chat_no_ejecuta_ninguna_consulta(self):
        with patch('jarvis.agente_inventario.procesar_consulta') as agente,patch.object(bot,'resumen_estado_actual') as estado, \
             patch.object(bot,'resumen_alertas_actuales') as alertas:
            for texto in ('/jarvis','/estado','/alertas','stock de filtros'):
                self.mensaje(texto,chat=77)
                self.assertEqual(self.responder.call_args.args,(77,'Chat no autorizado.',None))
            agente.assert_not_called();estado.assert_not_called();alertas.assert_not_called()
            self.assertEqual(self.s.sessions,{})

    def test_mismo_motor_sesion_y_solo_respuesta_textual(self):
        self.mensaje('/jarvis')
        r={'respuesta':'Ubicación consultada.','acciones_ui':[{'tipo':'producto_mapa','id':1}],
            'acciones_opcionales':[{'tipo':'led_producto','id':1}],'voz':'Texto de voz','datos':{'internos':True}}
        with patch('jarvis.agente_inventario.procesar_consulta',return_value=r) as agente:
            self.mensaje('¿Dónde está?')
            agente.assert_called_once_with('¿Dónde está?',estructurada=True,sesion='telegram:1234')
            self.assertEqual(self.responder.call_args.args[1],'Ubicación consultada.')

    def test_estados_y_alertas_no_cambian_conversacion(self):
        self.mensaje('/jarvis')
        with patch.object(bot,'resumen_estado_actual',return_value='ESTADO'),patch.object(bot,'resumen_alertas_actuales',return_value='ALERTAS'):
            self.mensaje('/estado');self.assertEqual(self.responder.call_args.args[1],'ESTADO')
            self.mensaje('/alertas');self.assertEqual(self.responder.call_args.args[1],'ALERTAS')
            self.assertTrue(self.s.sessions['1234']['modo_jarvis'])

    def test_comandos_dirigidos_a_otro_bot_se_ignoran(self):
        self.s.username='InventarioBot'
        self.mensaje('/jarvis@OtroBot');self.responder.assert_not_called()
        self.mensaje('/jarvis@InventarioBot');self.assertTrue(self.s.sessions['1234']['modo_jarvis'])

    def test_audio_no_descarga_ni_transcribe(self):
        a=actualizacion();a['message'].pop('text');a['message']['voice']={'file_id':'local'}
        self.s.procesar_actualizacion(a)
        self.assertIn('solo texto',self.responder.call_args.args[1])

    def test_offset_persistido_evito_reprocesar_mismo_update(self):
        a=actualizacion(numero=18)
        self.s._consumir_lote([a,a]);self.assertEqual(self.responder.call_count,1)
        self.assertEqual(self.s.offset,19)
        self.assertEqual(json.loads(self.s.ruta_cursor.read_text())['offset'],19)

    def test_no_ejecuta_si_falla_guardar_offset(self):
        with patch.object(self.s,'_guardar_cursor',side_effect=OSError()),patch.object(self.s,'procesar_actualizacion') as procesar:
            with self.assertRaises(OSError):self.s._consumir_lote([actualizacion()])
            procesar.assert_not_called()

    def test_excepcion_no_expone_detalle_interno(self):
        self.mensaje('/jarvis')
        with patch('jarvis.agente_inventario.procesar_consulta',side_effect=RuntimeError('password=secreto; C:\\interno\\archivo')):
            self.mensaje('stock')
        self.assertNotIn('secreto',self.responder.call_args.args[1]);self.assertNotIn('interno',self.responder.call_args.args[1])

    def test_consulta_lenta_no_bloquea_cola_de_alertas(self):
        self.mensaje('/jarvis');comenzo=threading.Event();liberar=threading.Event()
        def consulta(*a,**kw):comenzo.set();liberar.wait(2);return {'respuesta':'Respuesta real del motor'}
        with patch('jarvis.agente_inventario.procesar_consulta',side_effect=consulta):
            hilo=threading.Thread(target=self.mensaje,args=('stock',));hilo.start()
            try:
                self.assertTrue(comenzo.wait(1))
                servicio=envio.ServicioTelegram()
                servicio.notificar('inventario','Stock bajo','Cambio registrado',referencia='alerta:concurrente')
                self.assertEqual(servicio.cola.qsize(),1)
            finally:liberar.set();hilo.join(2)
            self.assertFalse(hilo.is_alive())


class ConversacionRealTelegram(unittest.TestCase):
    def test_intencion_pendiente_y_seguimiento_no_contaminan_desktop(self):
        from tests.probar_contexto_jarvis import Conversacion
        from jarvis import agente_inventario as agente
        escenario=Conversacion('runTest');escenario.setUp();self.addCleanup(escenario.doCleanups)
        servicio=bot.TelegramBotService();textos=[]
        def responder(chat,texto,*args):textos.append(texto);return {'enviado':True}
        agente.reiniciar_contexto('telegram:1234');agente.reiniciar_contexto('telegram:5678')
        with patch.object(bot,'_credenciales',return_value=('local','1234')),patch.object(bot,'enviar_respuesta_chat',side_effect=responder):
            for texto in ('/jarvis','Ubicación','Filtro de aceite','¿Cuánto queda?'):
                servicio.procesar_actualizacion(actualizacion(texto))
            ctx=agente.obtener_contexto('telegram:1234')
            self.assertEqual(ctx['ultimo_producto_id'],1)
            self.assertEqual(ctx['ultima_intencion'],'consultar_stock')
            self.assertIn('Quedan 8 unidades',textos[-1])
            self.assertIsNone(agente.obtener_contexto()['ultimo_producto_id'])
            self.assertIsNone(agente.obtener_contexto('telegram:5678')['ultimo_producto_id'])
        with patch.object(bot,'_credenciales',return_value=('local','5678')),patch.object(bot,'enviar_respuesta_chat',side_effect=responder):
            servicio.procesar_actualizacion(actualizacion('/jarvis',chat=5678))
            servicio.procesar_actualizacion(actualizacion('stock de tornillo',chat=5678))
            self.assertEqual(agente.obtener_contexto('telegram:5678')['ultimo_producto_id'],3)
            self.assertEqual(agente.obtener_contexto('telegram:1234')['ultimo_producto_id'],1)


class TransporteYListener(unittest.TestCase):
    def test_listener_completo_respeta_orden_y_offset(self):
        s=bot.TelegramBotService();respuestas=[];llamadas=[]
        def api(metodo,datos=None,**kw):
            llamadas.append((metodo,datos))
            if metodo=='getWebhookInfo':return {'ok':True,'result':{'url':''}}
            if metodo=='getMe':return {'ok':True,'result':{'username':'InventarioBot'}}
            if datos['offset']==0:
                return {'ok':True,'result':[actualizacion('/jarvis',numero=40),actualizacion('stock de filtro',numero=41)]}
            s.cerrar();return {'ok':True,'result':[]}
        def enviar(chat,texto,*a):respuestas.append(texto);return {'enviado':True}
        with tempfile.TemporaryDirectory() as carpeta,patch.object(bot,'BASE',Path(carpeta)), \
             patch.object(bot,'_credenciales',return_value=('sin-conexion','1234')), \
             patch.object(bot,'consultar_bot',side_effect=api),patch.object(bot,'enviar_respuesta_chat',side_effect=enviar), \
             patch('jarvis.agente_inventario.procesar_consulta',return_value={'respuesta':'Stock desde JARVIS'}) as agente:
            s.iniciar();hilo=s.hilo;s.iniciar();self.assertIs(s.hilo,hilo);hilo.join(3)
            self.assertFalse(hilo.is_alive());self.assertEqual(s.offset,42)
            self.assertEqual(respuestas,['JARVIS en línea. Adelante, ¿qué necesitas consultar?','Stock desde JARVIS'])
            agente.assert_called_once_with('stock de filtro',estructurada=True,sesion='telegram:1234')
            self.assertEqual([d['offset'] for m,d in llamadas if m=='getUpdates'],[0,42])

    def test_reinicio_recupera_cursor_sin_volver_a_ejecutar(self):
        with tempfile.TemporaryDirectory() as carpeta,patch.object(bot,'BASE',Path(carpeta)):
            a=bot.TelegramBotService();a._preparar_cursor('sin-conexion');a._guardar_cursor(100)
            b=bot.TelegramBotService();b._preparar_cursor('sin-conexion')
            with patch.object(b,'procesar_actualizacion') as procesar:
                b._consumir_lote([actualizacion(numero=99)]);procesar.assert_not_called()
            self.assertEqual(b.offset,100)

    def test_resumen_alertas_es_lectura_de_pendientes(self):
        filas=[dict(tipo='Stock bajo',nivel='Crítica'),dict(tipo='Cantidad inusual',nivel='Alta'),
            dict(tipo='Producto agotado',nivel='Critica')]
        with patch('inventory.inventario_service.consultar',return_value=filas) as consultar, \
             patch('inventory.lotes_service.refrescar_vencimientos') as refrescar:
            r=bot.resumen_alertas_actuales()
            for dato in ('Pendientes: 3','Críticas: 2','Stock bajo: 1','Anomalías: 1'):self.assertIn(dato,r)
            self.assertIn('a.atendida=0',consultar.call_args.args[0]);refrescar.assert_not_called()

    def test_estado_no_abre_camara_ni_usa_contexto_desktop(self):
        with patch('core.estado_sistema.probar_base',return_value={'estado':'ONLINE'}), \
             patch('surveillance.vigilancia_yolo.servicio_vigilancia.obtener_estado',return_value={'activo':False,'frame':None,'estado':'Inactivo'}), \
             patch('ai.facial.reconocimiento_cnn._bloqueo_camara') as bloqueo,patch('surveillance.camara_utils.abrir_camara') as abrir, \
             patch('jarvis.agente_inventario.procesar_consulta') as agente:
            bloqueo.locked.return_value=False
            r=bot.resumen_estado_actual()
            self.assertIn('Base de datos: ONLINE',r);self.assertIn('Cámara 1: SIN VERIFICAR',r)
            self.assertIn('Cámara 2 · Presencia:',r)
            agente.assert_not_called();abrir.assert_not_called()

    def test_lectura_y_entregas_comparten_transporte(self):
        with patch.object(envio,'_credenciales',return_value=('local','1234')),patch('requests.post') as post:
            post.return_value.status_code=200;post.return_value.json.return_value={'ok':True,'result':[]}
            r=envio.consultar_bot('getUpdates',{'offset':5,'timeout':15},timeout=22)
            self.assertTrue(r['ok']);self.assertEqual(post.call_args.kwargs['timeout'],(5,22))
            self.assertEqual(post.call_args.kwargs['data']['offset'],5)

    def test_solo_http200_oktrue_confirma_lectura(self):
        for http,ok in ((403,False),(200,False),(500,True)):
            with patch.object(envio,'_credenciales',return_value=('local','1234')),patch('requests.post') as post:
                post.return_value.status_code=http;post.return_value.json.return_value={'ok':ok,'result':[]}
                self.assertFalse(envio.consultar_bot('getUpdates')['ok'])

    def test_texto_largo_dividido_sin_payload_ni_secreto(self):
        with patch.object(envio,'_credenciales',return_value=('token-reservado','1234')),patch.object(envio,'_enviar',return_value={'enviado':True}) as enviar:
            envio.enviar_respuesta_chat(1234,'A'*8001+' token-reservado C:\\interno\\secreto.txt password=clave;')
            self.assertEqual(enviar.call_count,3)
            texto=''.join(c.args[1]['text'] for c in enviar.call_args_list)
            self.assertNotIn('token-reservado',texto);self.assertNotIn('secreto.txt',texto);self.assertNotIn('clave',texto)
            self.assertTrue(all(len(c.args[1]['text'])<=4000 for c in enviar.call_args_list))

    def test_otra_destinacion_solo_recibe_rechazo(self):
        with patch.object(envio,'_credenciales',return_value=('local','1234')),patch.object(envio,'_enviar',return_value={'enviado':True}) as enviar:
            envio.enviar_respuesta_chat(8,'Datos del inventario')
            self.assertEqual(enviar.call_args.args[1]['text'],'Chat no autorizado.')
            self.assertEqual(enviar.call_args.kwargs['chat_destino'],8)

    def test_entrega_incierta_no_repite_texto(self):
        with patch.object(envio,'_credenciales',return_value=('local','1234')),patch.object(envio,'_enviar',return_value={'enviado':False,'incierto':True}) as enviar:
            envio.enviar_respuesta_chat(1234,'X'*9000);enviar.assert_called_once()

    def test_lector_unico(self):
        a=bot.ConsumidorUnico('sin-conexion');b=bot.ConsumidorUnico('sin-conexion')
        try:
            self.assertTrue(a.adquirir());self.assertFalse(b.adquirir())
            a.liberar();self.assertTrue(b.adquirir())
        finally:a.liberar();b.liberar()

    def test_webhook_existente_no_arranca_getupdates(self):
        s=bot.TelegramBotService();cfg=deepcopy(DEFAULTS)
        with tempfile.TemporaryDirectory() as carpeta,patch.object(bot,'BASE',Path(carpeta)), \
             patch.object(bot,'_credenciales',return_value=('sin-conexion','1234')), \
             patch.object(bot,'cargar_configuracion',return_value=cfg), \
             patch.object(bot,'consultar_bot',return_value={'ok':True,'result':{'url':'https://ya-configurado'}}) as api:
            s._ejecutar();self.assertEqual(s.estado,'CONFLICTO')
            api.assert_called_once_with('getWebhookInfo')

    def test_conflicto409_no_afecta_notificaciones(self):
        s=bot.TelegramBotService();cfg=deepcopy(DEFAULTS)
        respuestas=[{'ok':True,'result':{'url':''}},{'ok':True,'result':{'username':'InventarioBot'}},
            {'ok':False,'http':409,'detalle':'Conflicto'}]
        with tempfile.TemporaryDirectory() as carpeta,patch.object(bot,'BASE',Path(carpeta)), \
             patch.object(bot,'_credenciales',return_value=('sin-conexion','1234')), \
             patch.object(bot,'cargar_configuracion',return_value=cfg),patch.object(bot,'consultar_bot',side_effect=respuestas), \
             patch.object(bot.servicio_telegram,'cerrar') as cerrar:
            s._ejecutar();self.assertEqual(s.estado,'CONFLICTO');cerrar.assert_not_called()


if __name__=='__main__':unittest.main()
