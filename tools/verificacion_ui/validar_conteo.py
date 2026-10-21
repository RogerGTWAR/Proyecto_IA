"""Interfaz con catálogo SQL; guardado sustituido y sin aplicar ajustes reales."""
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from copy import deepcopy
from datetime import datetime
import time
import json
from unittest.mock import patch,Mock
import tkinter as tk
from tkinter import ttk
import ttkbootstrap as tb
from PIL import ImageGrab
from ui.inventario_ui import ConteoUI
from ui import inventario_ui as modulo
from ui.interfaz import _tabla
from ui.ui_theme import crear_pagina,configurar_estilos


def widgets(p):
    for w in p.winfo_children():yield w;yield from widgets(w)


def main():
    salida=Path('verificacion_ui/conteo');salida.mkdir(parents=True,exist_ok=True)
    root=tb.Window(themename='flatly');root.title('Verificación visual del conteo');root.attributes('-topmost',True)
    configurar_estilos(root);errores=[]
    root.report_callback_exception=lambda t,e,tb:errores.append(str(e))
    pagina=crear_pagina(root);pagina.pagina.pack(fill='both',expand=True)
    guardados={};cabeceras={};aplicar=Mock()
    ubicaciones={u['id_ubicacion']:u for u in modulo.listar_ubicaciones()}
    empleados={e['id_empleado']:e for e in modulo.listar_empleados_activos()}
    def guardar(emp,ubic,filas,id_conteo=None):
        n=id_conteo or 1;guardados[n]=deepcopy(filas);u=ubicaciones[ubic];e=empleados[emp]
        cabeceras[n]=dict(id_conteo=n,id_empleado=emp,id_ubicacion=ubic,estado='BORRADOR',
            codigo_ubicacion=u['codigo_ubicacion'],estante=u.get('estante'),nivel=u.get('nivel'),fecha=datetime.now(),
            empleado=(e['nombres']+' '+e.get('apellidos','')).strip())
        return n
    def actualizar(seg=.25):
        fin=time.monotonic()+seg
        while time.monotonic()<fin:root.update();time.sleep(.015)
    def esperar():
        fin=time.monotonic()+10
        while pantalla.trabajo.ocupado and time.monotonic()<fin:actualizar(.1)
        assert not pantalla.trabajo.ocupado
    def captura(nombre,ventana=root):
        ventana.lift();actualizar(.25);x,y=ventana.winfo_rootx(),ventana.winfo_rooty()
        ImageGrab.grab(bbox=(x,y,x+ventana.winfo_width(),y+ventana.winfo_height())).save(salida/nombre)
    with patch.object(modulo,'guardar_conteo',side_effect=guardar),patch.object(modulo,'listar_conteos',side_effect=lambda:list(cabeceras.values())),patch.object(modulo,'aplicar_conteo',aplicar):
        try:
            pantalla=ConteoUI(pagina,root,_tabla,lambda:None)
            root.geometry('1366x768+0+0');actualizar();captura('inicio_1366.png')
            pantalla.cargar();esperar();actualizar()
            assert pantalla.filas
            for i,f in pantalla.filas.items():
                pantalla.t.selection_set(i);actualizar(.05)
                cantidad=f['cantidad_sistema']
                if i=='0' and cantidad>0:cantidad=max(0,cantidad-1)
                pantalla.fisico.delete(0,'end');pantalla.fisico.insert(0,str(cantidad));pantalla.editar()
                actualizar(.65);esperar()
            for ancho,alto in ((1366,768),(1920,1080)):
                root.geometry(f'{ancho}x{alto}+0+0');actualizar();captura(f'conteo_{ancho}.png')
            assert len(guardados)==1
            pantalla.aplicar();actualizar();w=next(w for w in root.winfo_children() if isinstance(w,tk.Toplevel))
            w.attributes('-topmost',True);captura('revision.png',w)
            next(w for w in widgets(w) if isinstance(w,ttk.Button) and w['text']=='Cancelar').invoke()
            aplicar.assert_not_called();assert not errores,errores
            informe=dict(errores=errores,registros=len(pantalla.filas),borradores_en_memoria=len(guardados),
                fuente='Catálogo y existencias SQL; cantidades físicas introducidas solo para verificar la interfaz',
                guardado_sql=False,ajustes_reales=False)
            (salida/'revision.json').write_text(json.dumps(informe,ensure_ascii=False,indent=2),encoding='utf-8')
            print('Conteo en ambas resoluciones, editor y revisión: correctos. Sin guardado ni ajustes reales.')
        finally:root.destroy()


if __name__=='__main__':main()
