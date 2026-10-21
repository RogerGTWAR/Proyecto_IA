"""Eventos automáticos sin publicar mensajes, abrir cámaras ni alterar SQL."""
import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
from copy import deepcopy
from unittest.mock import Mock,patch
import numpy as np
from integrations.telegram import telegram_service as t
from core.config_manager import DEFAULTS


class CentralAutomatico(unittest.TestCase):
    def setUp(self):
        from tests.probar_system_state import aislar_estado
        aislar_estado(self)
        self.s=t.ServicioTelegram()
        self.tmp=tempfile.TemporaryDirectory();self.s.directorio=Path(self.tmp.name)
        self.cfg=deepcopy(DEFAULTS);self.cfg['telegram']['habilitado']=True
        self.config=patch('core.config_manager.cargar_configuracion',return_value=self.cfg);self.config.start()
    def tearDown(self):
        self.s.cerrar()
        if self.s.hilo:self.s.hilo.join(2)
        self.config.stop();self.tmp.cleanup()
    def test_encolar_no_hace_sql_ni_http(self):
        with patch.object(self.s,'_guardar') as guardar,patch.object(t,'_enviar') as enviar:
            r=self.s.notificar('inventario','Stock bajo','Quedan 4',referencia='alerta:1')
            self.assertEqual(r['estado'],'PENDIENTE');guardar.assert_not_called();enviar.assert_not_called()
    def test_misma_referencia_una_solicitud_en_cola(self):
        for _ in range(50):self.s.notificar('inventario','Stock bajo','Quedan 4',referencia='alerta:1')
        self.assertEqual(self.s.cola.qsize(),1)
    def test_caida_es_transicion_no_actualizacion_de_pantalla(self):
        from core.event_bus import EventBus
        from core.event_subscribers import consumir_telegram,NOTIFICABLES
        bus=EventBus();self.addCleanup(bus.close)
        bus.subscribe(NOTIFICABLES,consumir_telegram)
        with patch('core.event_bus.event_bus',bus),patch.object(t,'servicio_telegram',self.s):
            for _ in range(50):self.s.informar_componente('SQL',False,'Conexión no disponible')
            self.assertEqual(self.s.cola.qsize(),1)
            self.s.informar_componente('SQL',True,'Disponible');self.s.informar_componente('SQL',False,'Caída nueva')
            self.assertEqual(self.s.cola.qsize(),2)
    def test_foto_y_video_se_adjuntan_en_orden(self):
        foto=Path(self.tmp.name)/'captura.png';foto.write_bytes(b'imagen')
        video=Path(self.tmp.name)/'clip.mp4';video.write_bytes(b'video')
        datos=dict(mensaje='Intrusión',imagen=str(foto),video=str(video))
        with patch.object(t,'_enviar',return_value=dict(enviado=True,detalle='Confirmado')) as enviar:
            r=t._entregar_contenido(datos,lambda d:None)
            self.assertTrue(r['enviado']);self.assertEqual([c.args[0] for c in enviar.call_args_list],['sendPhoto','sendVideo'])
            self.assertEqual(enviar.call_args_list[0].args[2],foto)
    def test_imagen_ausente_envia_texto(self):
        with patch.object(t,'_enviar',return_value=dict(enviado=True,detalle='Confirmado')) as enviar:
            t._entregar_contenido(dict(mensaje='Intrusión',imagen='no_existe.jpg'),lambda d:None)
            self.assertEqual(enviar.call_args.args[0],'sendMessage')
    def test_reintento_clip_no_repite_fotografia(self):
        foto=Path(self.tmp.name)/'captura.jpg';foto.touch();video=Path(self.tmp.name)/'clip.mp4';video.touch()
        datos=dict(mensaje='Intrusión',imagen=str(foto),video=str(video))
        resultados=[dict(enviado=True,detalle='Foto confirmada'),dict(enviado=False,reintentable=True,detalle='HTTP 503'),dict(enviado=True,detalle='Vídeo confirmado')]
        with patch.object(t,'_enviar',side_effect=resultados) as enviar:
            self.assertTrue(t._entregar_contenido(datos,lambda d:None)['reintentable'])
            self.assertTrue(t._entregar_contenido(datos,lambda d:None)['enviado'])
            self.assertEqual([c.args[0] for c in enviar.call_args_list],['sendPhoto','sendVideo','sendVideo'])
    def test_resultado_incierto_no_se_repite(self):
        datos=dict(mensaje='Alerta')
        with patch.object(t,'_enviar',return_value=dict(enviado=False,incierto=True,detalle='Sin confirmación')) as enviar:
            self.assertFalse(t._entregar_contenido(datos,lambda d:None)['reintentable'])
            t._entregar_contenido(datos,lambda d:None);self.assertEqual(enviar.call_count,1)
    def test_sql_caido_conserva_local_y_avisa_una_vez(self):
        e=dict(tipo='sistema',titulo='SQL',mensaje='Base no disponible',nivel='CRÍTICA',datos={'componente':'SQL'},imagen=None,video=None,referencia='sistema:sql:1')
        with patch.object(self.s,'_guardar',side_effect=ConnectionError()),patch.object(t,'_enviar',return_value=dict(enviado=True,detalle='Confirmado')) as enviar:
            for _ in range(4):self.s._procesar_evento(e)
            self.assertEqual(enviar.call_count,1)
            registros=list(self.s.directorio.glob('*.json'));self.assertEqual(len(registros),1)
            self.assertEqual(json.loads(registros[0].read_text(encoding='utf-8'))['_entrega_local']['estado'],'ENVIADA')
    def test_reintentos_registro_son_limitados(self):
        e=dict(tipo='inventario',titulo='Stock',mensaje='Sin stock',nivel='ALTA',datos={},imagen=None,video=None,referencia='alerta:1')
        with patch.object(self.s,'_guardar',side_effect=ConnectionError()):
            for _ in range(3):self.s.reintentos.clear();self.s._procesar_evento(e)
        self.assertFalse(self.s.reintentos);self.assertEqual(e['_intentos_registro'],3)
    def test_facial_rechaza_cnn_y_baja_calidad(self):
        with patch.object(t,'servicio_telegram',self.s):
            for r in [dict(estado='VERIFICANDO'),dict(estado='DESCONOCIDO',motor='cnn'),dict(estado='DESCONOCIDO',calidad_estado='BORROSO')]:
                self.assertIsNone(t.notificar_rostro_desconocido(r,None))
        self.assertTrue(self.s.cola.empty())
    def test_sface_valido_encola_foto_sin_sql_en_inferencia(self):
        frame=np.zeros((40,40,3),np.uint8)
        with patch.object(t,'servicio_telegram',self.s),patch('core.database.conectar') as conectar:
            t.notificar_rostro_desconocido(dict(estado='DESCONOCIDO',motor='embeddings',calidad_estado='CALIDAD_OK'),frame,referencia='facial:1')
            evento=self.s.cola.get_nowait();self.assertTrue(evento['_crear_alerta_facial'])
            self.assertIsNot(evento['_frame'],frame);conectar.assert_not_called()
    def test_png_se_sube_como_archivo_real(self):
        foto=Path(self.tmp.name)/'captura.png';foto.write_bytes(b'png')
        respuesta=Mock(status_code=200);respuesta.json.return_value={'ok':True}
        with patch.object(t,'_credenciales',return_value=('privado','chat')),patch('requests.post',return_value=respuesta) as post:
            self.assertTrue(t._enviar('sendPhoto',{'caption':'Alerta'},foto,'photo')['enviado'])
            datos=post.call_args.kwargs['files']['photo'];self.assertEqual(datos[2],'image/png');self.assertTrue(datos[1].closed)
    def test_video_grande_no_bloquea_envio_texto(self):
        video=Path(self.tmp.name)/'clip.mp4'
        with video.open('wb') as archivo:archivo.truncate(46*1024*1024)
        respuesta=Mock(status_code=200);respuesta.json.return_value={'ok':True}
        with patch.object(t,'_credenciales',return_value=('privado','chat')),patch('requests.post',return_value=respuesta) as post:
            r=t._entregar_contenido(dict(mensaje='Intrusión',video=str(video)),lambda d:None)
            self.assertFalse(r['enviado']);self.assertEqual(post.call_count,1)
    def test_worker_unico_y_no_publica_desde_caller(self):
        hilos=[];listo=threading.Event()
        def entregar(ref):hilos.append(threading.get_ident());listo.set()
        with patch.object(self.s,'_sincronizar_observadores'),patch.object(self.s,'_guardar'),patch.object(self.s,'entregar',side_effect=entregar):
            self.s.iniciar();hilo=self.s.hilo;self.s.iniciar();self.assertIs(self.s.hilo,hilo)
            self.s.notificar('inventario','Stock','Agotado',referencia='alerta:3')
            self.assertTrue(listo.wait(2));self.s.cerrar();hilo.join(2)
            self.assertNotEqual(hilos[0],threading.get_ident())

    def test_solo_clip_no_duplica_mensaje_de_la_foto(self):
        video=Path(self.tmp.name)/'clip.mp4';video.touch()
        with patch.object(t,'_enviar',return_value=dict(enviado=True,detalle='Confirmado')) as enviar:
            t._entregar_contenido(dict(mensaje='Intrusión',video=str(video),datos={'solo_video':True}),lambda d:None)
            self.assertEqual(enviar.call_count,1);self.assertEqual(enviar.call_args.args[0],'sendVideo')

    def test_telegram_no_ejecuta_analisis_de_movimientos(self):
        self.s.base_movimientos=10
        filas=[dict(id_movimiento=11,id_producto=2,tipo_movimiento='Transferencia')]
        hallazgos=[dict(id_movimiento=1),dict(id_movimiento=11)]
        with patch('inventory.inventario_service.consultar',return_value=filas), \
             patch('ai.anomalies.deteccion_anomalias.analizar_movimientos',return_value={'resultados':hallazgos}), \
             patch('ai.anomalies.deteccion_anomalias.guardar_hallazgos') as guardar, \
             patch('ai.prediction.prediccion_stock.predecir_agotamiento') as predecir:
            self.s._observar_movimientos();guardar.assert_not_called()
            predecir.assert_not_called()

    def test_linea_base_excluye_historicos_por_fecha_de_creacion(self):
        from core.system_state import state_manager
        state_manager.update('SQL','ONLINE')
        consultas=[]
        def consultar(sql,*args):
            consultas.append((sql,args))
            if 'MAX(id_alerta)' in sql:return [dict(alertas=8,anomalias=3,movimientos=10)]
            return []
        c=Mock();c.cursor.return_value=Mock()
        self.s._conexion_comprobada=True
        with patch('core.database.conectar',return_value=c),patch.object(self.s,'_observar'),patch.object(self.s,'_observar_movimientos'):
            self.s._sincronizar_observadores(consultar)
        consulta=next(c for c in consultas if 'MAX(id_alerta)' in c[0])
        self.assertIn('fecha_creacion<?',consulta[0]);self.assertIn('fecha_creacion IS NULL',consulta[0])
        self.assertEqual(consulta[1][0],self.s.iniciado.replace(tzinfo=None))

    def test_historico_local_no_se_recupera_al_volver_sql(self):
        self.s._sql_estaba_caido=True;self.s.base_alertas=10;self.s._conexion_comprobada=True
        (self.s.directorio/'registro.json').write_text(json.dumps({'sesion':'anterior','referencia':'historico'}))
        with patch.object(self.s,'_procesar_evento') as procesar,patch.object(self.s,'_observar'),patch.object(self.s,'_observar_movimientos'):
            self.s._sincronizar_observadores(lambda *args:[])
        procesar.assert_not_called()

    def test_boton_prueba_usa_flujo_central_y_espera_confirmacion(self):
        with patch.object(t,'notificar_evento',return_value={'estado':'PENDIENTE'} ) as notificar, \
             patch.object(t.servicio_telegram,'estado_entrega',return_value={'enviado':True,'estado':'ENVIADA','detalle':'HTTP 200'}):
            r=t.probar_telegram()
            self.assertTrue(r['enviado']);self.assertTrue(r['worker_proceso'])
            self.assertEqual(notificar.call_args.args[0],'PRUEBA')
            self.assertEqual(notificar.call_args.kwargs['nivel'],'INFO')

    def test_tipo_prueba_y_niveles_espanoles_no_se_bloquean(self):
        for nivel in ('INFO','MEDIO','ALTO','CRÍTICO'):
            r=self.s.notificar('PRUEBA','Comprobación','Mensaje',nivel,referencia='diagnostico:'+nivel)
            self.assertEqual(r['estado'],'PENDIENTE')
            e=self.s.cola.get_nowait();self.assertEqual(e['tipo'],'sistema')
            self.assertTrue(t.permitido(self.cfg['telegram'],e['tipo'],nivel))

    def test_api_error_incluye_causa_y_no_token(self):
        respuesta=Mock(status_code=403)
        respuesta.json.return_value={'ok':False,'description':'Forbidden: bot cannot send messages TOKEN_PRIVADO'}
        with patch.object(t,'_credenciales',return_value=('TOKEN_PRIVADO','chat')),patch('requests.post',return_value=respuesta):
            with self.assertLogs(t.LOG,level='INFO') as logs:r=t._enviar('sendMessage',{'text':'Comprobación'})
        self.assertFalse(r['enviado']);self.assertIn('Forbidden',r['detalle'])
        self.assertNotIn('TOKEN_PRIVADO',str(r)+str(logs.output));self.assertEqual(r['http'],403)

    def test_intrusion_muestra_resultado_del_worker_no_solo_encolado(self):
        from surveillance.vigilancia_ui import actualizar_entregas_evento
        e={'id_evento':'abc','telegram_foto':'Encolado en el servicio central.'}
        with patch.object(t.servicio_telegram,'estado_entrega',side_effect=[{'estado':'ERROR','detalle':'Telegram: error HTTP 400: foto rechazada','enviado':False},{}]):
            r=actualizar_entregas_evento(e)
        self.assertIn('HTTP 400',r['telegram_foto']);self.assertEqual(r['telegram_foto_estado'],'ERROR')

    def test_api_publica_arranca_worker_al_recibir_evento(self):
        with patch.object(t,'servicio_telegram',self.s),patch.object(self.s,'iniciar') as iniciar:
            r=t.notificar_evento('INTRUSION','Intrusión','Persona detectada',nivel='ALTO',referencia='intrusion:1')
            iniciar.assert_called_once();self.assertEqual(r['estado'],'PENDIENTE')
            self.assertEqual(self.s.cola.get_nowait()['tipo'],'vigilancia')

    def test_error_con_url_no_expone_credenciales(self):
        import requests
        error=requests.exceptions.ConnectionError('Falló https://api.telegram.org/botTOKEN_PRIVADO/sendPhoto chat=998877')
        with patch.object(t,'_credenciales',return_value=('TOKEN_PRIVADO','998877')),patch('requests.post',side_effect=error):
            with self.assertLogs(t.LOG,level='INFO') as logs:r=t._enviar('sendMessage',{'text':'Comprobación'})
        self.assertIn('ConnectionError',r['detalle'])
        for secreto in ('TOKEN_PRIVADO','998877'):
            self.assertNotIn(secreto,str(r)+str(logs.output))


if __name__=='__main__':unittest.main()
