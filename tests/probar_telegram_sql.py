"""Integración SQL transaccional: todas las escrituras se revierten y HTTP se sustituye."""
import json
import tempfile
import unittest
import uuid
from pathlib import Path
from copy import deepcopy
from unittest.mock import patch
from core.database import conectar
from core.config_manager import DEFAULTS
from integrations.telegram.telegram_service import ServicioTelegram


class ConexionTransaccional:
    def __init__(self,c):self.c=c
    def cursor(self):return self.c.cursor()
    def commit(self):pass
    def rollback(self):self.c.rollback()
    def close(self):pass


class TelegramSQL(unittest.TestCase):
    def setUp(self):
        self.c=conectar();self.addCleanup(self.c.close);self.addCleanup(self.c.rollback)
        self.s=ServicioTelegram();self.ref='verificacion:'+uuid.uuid4().hex
        cfg=deepcopy(DEFAULTS);cfg['telegram']['habilitado']=True
        p=patch('core.database.conectar',return_value=ConexionTransaccional(self.c));p.start();self.addCleanup(p.stop)
        p=patch('core.config_manager.cargar_configuracion',return_value=cfg);p.start();self.addCleanup(p.stop)

    def test_referencia_unica_y_entrega_persistida(self):
        for _ in range(2):self.s._guardar('inventario','Stock bajo','Stock: 4.00','ALTA',{},None,None,self.ref)
        with patch('integrations.telegram.telegram_service._enviar',return_value=dict(enviado=True,detalle='Confirmado')) as enviar:
            self.s.entregar(self.ref);self.s.entregar(self.ref);self.assertEqual(enviar.call_count,1)
        fila=self.c.cursor().execute('SELECT estado,intentos,contenido FROM notificaciones_telegram WHERE referencia=?',self.ref).fetchone()
        self.assertEqual(fila.estado,'ENVIADA');self.assertEqual(fila.intentos,1)
        self.assertTrue(json.loads(fila.contenido)['_partes']['texto']['enviado'])

    def test_reintentar_video_conserva_foto_en_sql(self):
        with tempfile.TemporaryDirectory() as directorio:
            foto=Path(directorio)/'captura.png';foto.touch();video=Path(directorio)/'clip.mp4';video.touch()
            self.s._guardar('vigilancia','Intrusión','Zona restringida','ALTA',{},str(foto),str(video),self.ref)
            respuestas=[dict(enviado=True,detalle='Foto confirmada'),dict(enviado=False,reintentable=True,detalle='HTTP 503'),dict(enviado=True,detalle='Clip confirmado')]
            with patch('integrations.telegram.telegram_service._enviar',side_effect=respuestas) as enviar:
                self.assertEqual(self.s.entregar(self.ref)['estado'],'ERROR')
                self.s._procesar_evento({'_entrega':self.ref})
                self.assertEqual([c.args[0] for c in enviar.call_args_list],['sendPhoto','sendVideo','sendVideo'])
            fila=self.c.cursor().execute('SELECT estado,intentos FROM notificaciones_telegram WHERE referencia=?',self.ref).fetchone()
            self.assertEqual(fila.estado,'ENVIADA');self.assertEqual(fila.intentos,2)

    def test_video_espera_la_foto_principal(self):
        foto_ref=self.ref+':foto';video_ref=self.ref+':video'
        with tempfile.TemporaryDirectory() as directorio:
            foto=Path(directorio)/'captura.jpg';foto.touch();video=Path(directorio)/'clip.mp4';video.touch()
            self.s._guardar('vigilancia','Intrusión','Entrada a zona restringida','ALTA',{},str(foto),None,foto_ref)
            self.s._guardar('vigilancia','Clip','Entrada a zona restringida','ALTA',{'solo_video':True,'foto_referencia':foto_ref},None,str(video),video_ref)
            with patch('integrations.telegram.telegram_service._enviar',return_value=dict(enviado=True,detalle='Confirmado')) as enviar:
                self.assertEqual(self.s.entregar(video_ref)['estado'],'PENDIENTE');enviar.assert_not_called()
                self.s.entregar(foto_ref);self.s.entregar(video_ref)
                self.assertEqual([c.args[0] for c in enviar.call_args_list],['sendPhoto','sendVideo'])


if __name__=='__main__':unittest.main()
