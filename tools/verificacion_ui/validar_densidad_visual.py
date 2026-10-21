"""Recorrido visual en dos resoluciones, sin escribir registros ni activar cámara o voz."""
from pathlib import Path
import json
import runpy
import sys
import time
import tkinter as tk
from tkinter import ttk
from unittest.mock import patch
from contextlib import ExitStack
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from PIL import ImageGrab
from ui import interfaz
from ai.anomalies import deteccion_anomalias
from inventory.mapa_almacen import MapaAlmacenUI
from ui.inventario_ui import InventarioUI
from ui.prediccion_ui import PrediccionUI
from ui.anomalias_ui import AnomaliasUI
from integrations.reporting.reportes_ui import ReportesUI
from tools.verificacion_ui.validar_tablas_presentacion import widgets

vistas={};errores=[]
SALIDA=Path('verificacion_ui/densidad');SALIDA.mkdir(exist_ok=True)


def registrar(clase,clave):
    original=clase.__init__
    def iniciar(self,*a,**kw):original(self,*a,**kw);vistas[clave]=self
    return iniciar


def revisar(root,*a,**kw):
    root.report_callback_exception=lambda tipo,e,tb:errores.append(str(e))
    root.attributes('-topmost',True)
    def actualizar(segundos=.15):
        limite=time.monotonic()+segundos
        while time.monotonic()<limite:root.update();time.sleep(.02)
    informe={}
    try:
        actualizar(3)
        notebook=next(w for w in widgets(root) if isinstance(w,ttk.Notebook) and any(w.tab(p,'text')=='Productos' for p in w.tabs()))
        paginas={notebook.tab(p,'text'):p for p in notebook.tabs()}
        anom=vistas['anomalias'];avanzados=anom.controles['movimiento'].master.master
        assert not avanzados.winfo_manager()
        toggle=next(w for w in widgets(root) if isinstance(w,ttk.Button) and w.cget('text')=='Filtros avanzados ▼')
        toggle.invoke();actualizar();assert avanzados.winfo_manager()
        anom.controles['movimiento'].set('Salida');toggle.invoke()
        assert anom.controles['movimiento'].get()=='Salida'
        anom.controles['movimiento'].set('Todos')
        # Vista previa usa los mismos datos y exportadores, sin exportar archivos.
        reporte=vistas['reportes']
        limite=time.monotonic()+10
        while reporte.trabajo.ocupado and time.monotonic()<limite:actualizar()
        reporte.previa()
        while reporte.trabajo.ocupado and time.monotonic()<limite:actualizar()
        assert reporte.reporte is not None
        for ancho,alto in ((1366,768),(1920,1080)):
            root.state('normal');root.geometry(f'{ancho}x{alto}+0+0');root.lift();actualizar(.3)
            resultados=[]
            for nombre,pagina in paginas.items():
                notebook.select(pagina);actualizar(.2)
                tablas=[w for w in widgets(root) if isinstance(w,ttk.Treeview) and w.winfo_ismapped()]
                filas=[]
                for t in tablas:
                    disponible=max(0,min(t.winfo_rooty()+t.winfo_height(),root.winfo_rooty()+alto-30)-max(t.winfo_rooty(),root.winfo_rooty()+85))
                    filas.append({'columnas':list(t['columns']),'visibles':list(t['displaycolumns']),
                        'ancho':t.winfo_width(),'alto':t.winfo_height(),'pixeles_visibles':disponible,
                        'inicio_y':t.winfo_rooty()-root.winfo_rooty()})
                resultados.append({'modulo':nombre,'tablas':filas})
                if nombre in ('Productos','Historial','Alertas','Mapa','Análisis IA','Predicción','Anomalías','Reportes','Configuración'):
                    x,y=root.winfo_rootx(),root.winfo_rooty()
                    ImageGrab.grab(bbox=(x,y,x+ancho,y+alto)).save(SALIDA/f'{ancho}_{nombre.replace(" ","_")}.png')
                if nombre=='Historial':
                    hist=next(t for t in tablas if 'observacion' in t['columns'])
                    assert len(hist['displaycolumns'])==9
                    assert 'observacion' not in hist['displaycolumns']
                    assert hist.get_children()
                if nombre=='Productos':
                    assert filas and filas[0]['pixeles_visibles']>=100,filas
            informe[str(ancho)]=resultados
        assert not errores,errores
        (SALIDA/'revision.json').write_text(json.dumps(informe,ensure_ascii=False,indent=2),encoding='utf-8')
        print('Recorrido de '+str(len(paginas))+' módulos en 1366x768 y 1920x1080 correcto. Historial: 9 columnas; filtros avanzados conservan valores; vista previa de Reportes disponible. Capturas en '+str(SALIDA))
    finally:interfaz.cerrar_audio();root.destroy()


if __name__=='__main__':
    with ExitStack() as stack:
        for clase,clave in ((InventarioUI,'inventario'),(MapaAlmacenUI,'mapa'),(AnomaliasUI,'anomalias'),(ReportesUI,'reportes'),(PrediccionUI,'prediccion')):
            stack.enter_context(patch.object(clase,'__init__',registrar(clase,clave)))
        stack.enter_context(patch.object(deteccion_anomalias,'guardar_hallazgos',return_value=None))
        from integrations.telegram.telegram_service import servicio_telegram
        stack.enter_context(patch.object(servicio_telegram,'iniciar',return_value=None))
        stack.enter_context(patch.object(interfaz,'precalentar_voz',return_value=None))
        stack.enter_context(patch.object(tk.Misc,'mainloop',revisar))
        runpy.run_path('main.py',run_name='__main__')
