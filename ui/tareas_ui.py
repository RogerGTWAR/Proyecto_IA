"""Trabajos de I/O: los workers publican en cola, Tk consume en su hilo."""
import queue
import threading
import traceback
from tkinter import messagebox

class TrabajosUI:
    def __init__(self,root):
        self.root=root; self.cola=queue.Queue(); self.ocupado=False
        self.cerrado=False
        self.after=self.root.after(80,self.consumir)
        self.root.bind('<Destroy>',lambda event:self.cerrar() if event.widget is self.root else None,add='+')
    def ejecutar(self,fn,al_terminar,al_error=None):
        if self.ocupado: return False
        self.ocupado=True
        def tarea():
            try: self.cola.put((al_terminar,fn(),None,al_error))
            except Exception as e: traceback.print_exc(); self.cola.put((al_terminar,None,e,al_error))
        threading.Thread(target=tarea,daemon=True).start(); return True
    def consumir(self):
        if self.cerrado:return
        try:
            while True:
                fn,r,e,al_error=self.cola.get_nowait(); self.ocupado=False
                if e and al_error: al_error(e)
                elif e: messagebox.showerror('Operación',str(e),parent=self.root)
                else: fn(r)
        except queue.Empty: pass
        if self.root.winfo_exists(): self.after=self.root.after(80,self.consumir)

    def cerrar(self):
        self.cerrado=True
        try:self.root.after_cancel(self.after)
        except Exception:pass
