"""Recorrido local de Mapa, configuración y JARVIS; SQL solo de lectura."""
from pathlib import Path
import json
import sys
import time
import tkinter as tk
from tkinter import ttk
from unittest.mock import patch
from copy import deepcopy
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from PIL import ImageGrab
from ui.ui_theme import configurar_estilos, crear_pagina
from ui.interfaz import _tabla
from inventory.mapa_almacen import MapaAlmacenUI,ubicaciones_mapa
from ui.configuracion_ui import ConfiguracionUI
from integrations.arduino.led_service import servicio_led,resolver_filas,resolver_producto,LED_ENCENDIDO,LED_APAGADO
from core.config_manager import DEFAULTS
from inventory.inventario_service import buscar_inventario
from jarvis import agente_inventario as agente


def main():
    root=tk.Tk();root.geometry('1366x768+0+0');configurar_estilos(root)
    errores=[];root.report_callback_exception=lambda t,e,tb:errores.append(str(e))
    salida=Path('verificacion_ui/arduino');salida.mkdir(exist_ok=True)
    def actualizar(segundos=.25):
        fin=time.monotonic()+segundos
        while time.monotonic()<fin:root.update();time.sleep(.015)
    try:
        nb=ttk.Notebook(root);nb.pack(fill='both',expand=True)
        pm=crear_pagina(nb);nb.add(pm.pagina,text='Mapa')
        mapa=MapaAlmacenUI(pm,root,_tabla)
        pc=crear_pagina(nb);nb.add(pc.pagina,text='Configuración')
        config=ConfiguracionUI(pc,root)
        posiciones=resolver_filas([dict(u,posicion=p) for u in ubicaciones_mapa() for p in (1,2)])
        assert sorted(r['led'] for r in posiciones)==list(range(1,25))
        productos=buscar_inventario()
        producto=next(p for p in productos if 'tornillo' in p['nombre'].lower())
        filas=resolver_producto(producto['id_producto']);assert filas
        u=filas[0];mapa.seleccionar_posicion(u['id_ubicacion'],u['posicion'])
        mapa.boton_led.invoke();actualizar(1)
        assert servicio_led.estado_conexion()['leds'][u['led']]==LED_ENCENDIDO
        tarjeta=next(t for t in mapa.espacios if t.led_numero==u['led'])
        assert 'ON' in tarjeta.cget('text')
        for ancho,alto in ((1366,768),(1920,1080)):
            root.geometry(f'{ancho}x{alto}+0+0');actualizar()
            x,y=root.winfo_rootx(),root.winfo_rooty()
            ImageGrab.grab(bbox=(x,y,x+ancho,y+alto)).save(salida/f'mapa_{ancho}.png')
        mapa.apagar_leds();actualizar(.5)
        assert set(servicio_led.estado_conexion()['leds'].values())=={LED_APAGADO}
        sesion='validacion_led_sql';agente.reiniciar_contexto(sesion)
        ubicacion=agente.procesar_consulta('ubicacion de '+producto['codigo'],True,sesion)
        assert not ubicacion['acciones_ui']
        assert any(a['tipo']=='led_producto' for a in ubicacion['acciones_opcionales'])
        assert set(servicio_led.estado_conexion()['leds'].values())=={LED_APAGADO}
        encendido=agente.procesar_consulta('Enciende la luz',True,sesion)
        assert encendido['intencion']=='led',encendido
        assert all(servicio_led.estado_conexion()['leds'][f['led']]==LED_ENCENDIDO for f in filas)
        apagado=agente.procesar_consulta('Apaga la luz',True,sesion)
        assert apagado['intencion']=='led'
        nb.select(pc.pagina);root.geometry('1366x768+0+0');actualizar()
        assert ('arduino','puerto') in config.controles
        assert config.controles[('arduino','modo')][0].get()=='simulacion'
        x,y=root.winfo_rootx(),root.winfo_rooty()
        ImageGrab.grab(bbox=(x,y,x+1366,y+768)).save(salida/'configuracion_1366.png')
        assert servicio_led._serial is None
        assert not errores,errores
        informe=dict(posiciones_sql=len(posiciones),leds=[f['led'] for f in filas],
                     producto=producto['nombre'],ubicacion=ubicacion['respuesta'],
                     encendido=encendido['respuesta'],apagado=apagado['respuesta'],
                     errores_tk=errores,hardware_conectado=False)
        (salida/'revision.json').write_text(json.dumps(informe,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps(informe,ensure_ascii=False))
    finally:
        servicio_led.apagar_todos();root.destroy()


if __name__=='__main__':
    with patch.object(servicio_led,'_config',lambda:deepcopy(DEFAULTS['arduino'])):
        main()
