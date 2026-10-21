"""Captura únicamente la ventana propia de la prueba, verificando su HWND."""
import ctypes
import time
from ctypes import wintypes
from pathlib import Path
from PIL import ImageGrab

def capturar(ventana,ruta):
    ventana.update_idletasks()
    anterior=ventana.attributes("-topmost")
    try:
        ventana.attributes("-topmost",True); ventana.update(); time.sleep(.15); ventana.update()
        x,y=ventana.winfo_rootx(),ventana.winfo_rooty()
        ancho,alto=ventana.winfo_width(),ventana.winfo_height()
        user=ctypes.windll.user32
        user.GetAncestor.argtypes=[wintypes.HWND,wintypes.UINT]; user.GetAncestor.restype=wintypes.HWND
        user.WindowFromPoint.argtypes=[wintypes.POINT]; user.WindowFromPoint.restype=wintypes.HWND
        propio=user.GetAncestor(ventana.winfo_id(),2)
        for px in (x+2,x+ancho//2,x+ancho-3):
            for py in (y+2,y+alto//2,y+alto-3):
                if user.GetAncestor(user.WindowFromPoint(wintypes.POINT(px,py)),2)!=propio:
                    raise RuntimeError("Captura omitida: la ventana de prueba está cubierta.")
        destino=Path(ruta); destino.parent.mkdir(exist_ok=True,parents=True)
        ImageGrab.grab(bbox=(x,y,x+ancho,y+alto)).save(destino)
    finally: ventana.attributes("-topmost",anterior)
