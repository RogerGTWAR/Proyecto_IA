"""Controles Arduino; todo I/O ocurre fuera del hilo de Tkinter."""
from tkinter import ttk
from ui.tareas_ui import TrabajosUI
from integrations.arduino.led_service import servicio_led, detectar_puertos


class ArduinoUI:
    def __init__(self, padre, root, puerto):
        self.root = root
        self.puerto = puerto
        self.trabajo = TrabajosUI(root)
        ttk.Label(padre, text='Guarde la configuración antes de conectar. Simulación no requiere habilitar hardware.',
                  wraplength=780).pack(anchor='w', pady=8)
        f = ttk.Frame(padre); f.pack(fill='x')
        for titulo, accion in [('Detectar puertos', self.detectar),
                               ('Conectar', lambda: self.ejecutar(servicio_led.conectar)),
                               ('Desconectar', lambda: self.ejecutar(servicio_led.desconectar)),
                               ('Reconectar', lambda: self.ejecutar(servicio_led.reconectar))]:
            ttk.Button(f, text=titulo, command=accion).pack(side='left', padx=3)
        f = ttk.Frame(padre); f.pack(fill='x', pady=8)
        ttk.Label(f, text='Número LED:').pack(side='left')
        self.numero = ttk.Spinbox(f, from_=1, to=24, width=5); self.numero.set('1'); self.numero.pack(side='left', padx=6)
        ttk.Button(f, text='Probar LED', command=self.probar).pack(side='left', padx=3)
        ttk.Button(f, text='Apagar todos', command=lambda: self.ejecutar(servicio_led.apagar_todos)).pack(side='left', padx=3)
        ttk.Button(f, text='Comprobar conexión', command=lambda: self.ejecutar(servicio_led.comprobar)).pack(side='left', padx=3)
        self.resultado=ttk.Label(padre,wraplength=780);self.resultado.pack(anchor='w')
        self.estado = ttk.Label(padre, wraplength=780); self.estado.pack(anchor='w', pady=8)
        from ui.service_state_ui import StateBinding
        self.binding=StateBinding(root,self.mostrar_estado,self.estado)


    def ejecutar(self, fn):
        self.trabajo.ejecutar(fn, lambda r: self.resultado.configure(text=r.get('mensaje', r.get('detalle', ''))))

    def detectar(self):
        def mostrar(puertos):
            self.puerto.configure(values=puertos)
            self.resultado.configure(text='Puertos: ' + (', '.join(puertos) or 'No se encontraron puertos disponibles.'))
        self.trabajo.ejecutar(detectar_puertos, mostrar)

    def probar(self):
        from tkinter import messagebox
        try:
            numero = int(self.numero.get())
            from integrations.arduino.led_service import validar_led
            validar_led(numero)
        except ValueError as exc:
            messagebox.showerror('Arduino', str(exc), parent=self.root); return
        self.ejecutar(lambda: servicio_led.probar_led(numero))

    def mostrar_estado(self,snapshot):
        from core.system_state import format_service_state
        value=snapshot['ARDUINO'];view=format_service_state(value)
        self.estado.configure(text=view['text']+' · '+value['message'],foreground=view['color'])

    def actualizar(self):
        from core.system_state import state_manager
        self.mostrar_estado(state_manager.snapshot())
