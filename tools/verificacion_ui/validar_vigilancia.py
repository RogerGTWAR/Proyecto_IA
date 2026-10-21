"""Editor y controles Tk con cámara sustituida; no envía mensajes ni crea alertas SQL."""
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
import json
import tempfile
import time
import tkinter as tk
from tkinter import ttk
import ttkbootstrap as tb
from unittest.mock import patch
import numpy as np
from PIL import ImageGrab
from core import config_manager
from ui.interfaz import _tabla
from ui.ui_theme import configurar_estilos,crear_pagina
from surveillance.vigilancia_ui import VigilanciaUI
from surveillance.vigilancia_yolo import servicio_vigilancia,validar_poligono


class Captura:
    def __init__(self,*args):
        self.error=None;self.n=0
        self.imagen=np.zeros((360,640,3),np.uint8);self.imagen[:,:,0]=np.arange(640,dtype=np.uint16)[None,:]%255
    def iniciar(self):return self
    def leer(self):time.sleep(.02);self.n+=1;return self.n,self.imagen
    def cerrar(self):pass


def widgets(p):
    for h in p.winfo_children():yield h;yield from widgets(h)


def main():
    salida=Path('verificacion_ui/vigilancia');salida.mkdir(exist_ok=True)
    root=tb.Window(themename='flatly');root.geometry('1366x768+0+0');configurar_estilos(root)
    root.attributes('-topmost',True);root.lift()
    errores=[];root.report_callback_exception=lambda t,e,tb:errores.append(str(e))
    def actualizar(seg=.3):
        fin=time.monotonic()+seg
        while time.monotonic()<fin:root.update();time.sleep(.015)
    try:
        pagina=crear_pagina(root);pagina.pagina.pack(fill='both',expand=True)
        ui=VigilanciaUI(pagina,root,_tabla);actualizar()
        assert not servicio_vigilancia.obtener_estado()['activo']
        original=servicio_vigilancia.iniciar
        def iniciar(cfg,preview=False,**kw):return original(cfg,preview,captura_factory=Captura,**kw)
        with patch.object(servicio_vigilancia,'iniciar',side_effect=iniciar):
            ui.configurar_zona();actualizar(.7)
            editor=ui.editor;editor.attributes('-topmost',True);editor.lift()
            canvas=next(w for w in widgets(editor) if isinstance(w,tk.Canvas))
            next(w for w in widgets(editor) if isinstance(w,ttk.Button) and w.cget('text')=='Limpiar').invoke()
            for x,y in ((.3,.2),(.8,.2),(.8,.85),(.3,.85)):
                canvas.event_generate('<Button-1>',x=int(canvas.winfo_width()*x),y=int(canvas.winfo_height()*y));actualizar(.1)
            actualizar()
            x,y=editor.winfo_rootx(),editor.winfo_rooty()
            ImageGrab.grab(bbox=(x,y,x+editor.winfo_width(),y+editor.winfo_height())).save(salida/'editor_zona.png')
            boton=next(w for w in widgets(editor) if isinstance(w,ttk.Button) and w.cget('text')=='Guardar zona')
            boton.invoke();actualizar(.5)
        assert len(ui.cfg['zone_polygon'])==4,ui.cfg['zone_polygon']
        validar_poligono(ui.cfg['zone_polygon'])
        assert config_manager.cargar_configuracion()['vigilancia']['zone_polygon']==ui.cfg['zone_polygon']
        for ancho,alto in ((1366,768),(1920,1080)):
            root.geometry(f'{ancho}x{alto}+0+0');root.lift();actualizar()
            x,y=root.winfo_rootx(),root.winfo_rooty()
            ImageGrab.grab(bbox=(x,y,x+ancho,y+alto)).save(salida/f'vigilancia_{ancho}.png')
        assert not servicio_vigilancia.obtener_estado()['activo']
        assert not errores,errores
        informe={'errores_tk':errores,'vertices_guardados':4,'fuente':'captura sustituida','telegram_enviado':False,'sql_eventos_creados':0}
        (salida/'revision.json').write_text(json.dumps(informe,indent=2),encoding='utf-8')
        print('Editor: cuatro vértices guardados; vigilancia inactiva al abrir; controles visibles; sin envíos ni eventos SQL.')
    finally:
        servicio_vigilancia.parar()
        if servicio_vigilancia.hilo:servicio_vigilancia.hilo.join(2)
        root.destroy()


if __name__=='__main__':
    with tempfile.TemporaryDirectory() as d,patch.object(config_manager,'ARCHIVO',Path(d)/'config.json'):
        main()
