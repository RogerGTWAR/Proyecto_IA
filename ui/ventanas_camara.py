"""Ventanas Tkinter para registro y escáner, sin lógica de reconocimiento."""

import threading
import tkinter as tk
from tkinter import ttk

import cv2
from PIL import Image, ImageTk
from ui.ui_theme import (COLOR_ACTION, COLOR_BG, COLOR_DANGER, COLOR_HEADER,
                      COLOR_PANEL, COLOR_SUCCESS, COLORES, FONTS, marco_visual, etiqueta_visual)


def redimensionar_con_aspecto(frame, max_width=640, max_height=480):
    alto, ancho = frame.shape[:2]
    escala = min(max_width / ancho, max_height / alto)
    nuevo = (max(1, int(ancho * escala)), max(1, int(alto * escala)))
    if nuevo == (ancho, alto):
        return frame
    interpolacion = cv2.INTER_AREA if escala < 1 else cv2.INTER_LINEAR
    return cv2.resize(frame, nuevo, interpolation=interpolacion)


class VentanaCamara:
    """Recibe frames desde workers y actualiza Tk solamente mediante after()."""

    def __init__(self, padre, tipo, persona, al_cerrar, al_info=None):
        self.tipo = tipo
        self.al_cerrar = al_cerrar
        self.al_info = al_info
        self._bloqueo = threading.Lock()
        self._ultimo_frame = None
        self._info_pendiente = {}
        self._info_mostrada = {}
        self._cerrada = False
        self._cierre_solicitado = False
        self._after_id = None
 
        self.ventana = tk.Toplevel(padre)
        self.ventana.title("Registro facial" if tipo == "registro" else "Escáner facial")
        self.ventana.geometry(f"{min(960, padre.winfo_screenwidth()-80)}x{min(740, padre.winfo_screenheight()-100)}")
        self.ventana.minsize(720, 580)
        self.ventana.configure(bg=COLOR_BG)
        self.ventana.protocol("WM_DELETE_WINDOW", lambda: self.solicitar_cierre("cancelar"))
        self.ventana.bind("<Escape>", lambda _e: self.solicitar_cierre(
            "cancelar" if tipo == "registro" else "finalizar"))
        self.ventana.bind("<KeyPress-q>", lambda _e: self.solicitar_cierre("cancelar"))
        self.ventana.bind("<KeyPress-Q>", lambda _e: self.solicitar_cierre("cancelar"))

        cabecera = marco_visual(self.ventana, bg=COLOR_HEADER, height=62)
        cabecera.pack(fill="x")
        etiqueta_visual(cabecera, text="REGISTRO FACIAL" if tipo == "registro" else "ESCÁNER FACIAL",
                 bg=COLOR_HEADER, fg="white", font=("Segoe UI", 17, "bold")).pack(anchor="w", padx=24, pady=(13, 0))

        cuerpo = ttk.Frame(self.ventana, padding=(20, 16), style="App.TFrame")
        cuerpo.pack(fill="both", expand=True)
        panel_video = marco_visual(cuerpo, bg=COLORES["video"], width=640, height=360)
        panel_video.pack(fill="both", expand=True)
        panel_video.pack_propagate(False)
        self.video = etiqueta_visual(panel_video, bg=COLORES["video"], fg="white", text="Iniciando cámara...",
                              font=("Segoe UI", 12))
        self.video.pack(fill="both", expand=True)

        info = ttk.Frame(cuerpo, padding=(16, 12), style="Card.TFrame")
        info.pack(fill="x", pady=(12, 0))
        self.variables = {
            "persona": tk.StringVar(value=persona or "-"),
            "codigo": tk.StringVar(value="-"),
            "cargo": tk.StringVar(value="-"),
            "confianza": tk.StringVar(value="-"),
            "estado": tk.StringVar(value="Buscando rostro..."),
            "contador": tk.StringVar(value="0 / 15"),
            "distancia": tk.StringVar(value="-"),
            "detalle": tk.StringVar(value="-"),
            "debug": tk.StringVar(value="-"),
            "metricas":tk.StringVar(value="-"),
            "telegram":tk.StringVar(value="Sin evento notificado"),
            "instruccion": tk.StringVar(value="Mire al frente"),
        }
        filas = (["Persona", "persona"], ["Fotografías", "contador"], ["Estado", "estado"],
                 ["Instrucción", "instruccion"]) if tipo == "registro" else (
                 ["Persona", "persona"], ["Código", "codigo"], ["Puntuación", "confianza"], ["Estado", "estado"])
        if tipo == "escaner":
            filas = (("Persona","persona"),("C\u00f3digo","codigo"),("Cargo","cargo"),
                     ("Similitud / score","confianza"),("Estado","estado"),("Telegram","telegram"),
                     ("Tama\u00f1o aparente","distancia"),("Calidad","detalle"),("FPS / Motor","metricas"))
        if tipo=='cnn_actual':filas=(("Subject","persona"),("Confianza","confianza"),("Estado","estado"))
        for indice,(etiqueta,clave) in enumerate(filas):
            grupo=ttk.Frame(info,style="Card.TFrame")
            grupo.grid(row=indice//2,column=indice%2,sticky="nsew",padx=6,pady=4)
            ttk.Label(grupo,text=etiqueta,font=("Segoe UI",9,"bold")).pack(anchor="w")
            ttk.Label(grupo,textvariable=self.variables[clave],wraplength=300).pack(anchor="w",fill="x")
        info.columnconfigure(0,weight=1,uniform='detalle');info.columnconfigure(1,weight=1,uniform='detalle')
        if tipo=='escaner':
            self.debug_visible=tk.BooleanVar(value=False)
            tecnico=ttk.Frame(cuerpo,padding=8,style="Card.TFrame")
            etiqueta_tecnica=ttk.Label(tecnico,textvariable=self.variables['debug'],wraplength=800)
            etiqueta_tecnica.pack(fill='x')
            tecnico.bind('<Configure>',lambda e:etiqueta_tecnica.configure(wraplength=max(200,e.width-20)))
            def alternar_debug():
                if self.debug_visible.get():tecnico.pack(fill='x',pady=(6,0))
                else:tecnico.pack_forget()
            ttk.Checkbutton(cuerpo,text='Mostrar informaci\u00f3n t\u00e9cnica',variable=self.debug_visible,command=alternar_debug).pack(anchor='w',pady=(6,0))

        botones = ttk.Frame(cuerpo, style="App.TFrame")
        botones.pack(pady=(4, 0))
        if tipo in ("escaner","cnn_actual"):
            ttk.Button(botones, text="Finalizar análisis",
                       command=lambda: self.solicitar_cierre("finalizar"),
                       style="Primary.TButton", cursor="hand2").pack(side="left", padx=6)
        ttk.Button(botones, text="Cancelar",
                   command=lambda: self.solicitar_cierre("cancelar"),
                   style="Secondary.TButton", cursor="hand2").pack(side="left", padx=6)

        self.ventana.transient(padre)
        self.ventana.lift()
        self.ventana.focus_force()
        self._after_id = self.ventana.after(15, self._actualizar)

    def publicar_frame(self, frame):
        with self._bloqueo:
            self._ultimo_frame = frame

    @property
    def cierre_solicitado(self):
        return self._cierre_solicitado

    def publicar_info(self, **datos):
        with self._bloqueo:
            self._info_pendiente.update(datos)

    def _actualizar(self):
        if self._cerrada:
            return
        with self._bloqueo:
            frame, self._ultimo_frame = self._ultimo_frame, None
            datos, self._info_pendiente = self._info_pendiente, {}
        if frame is not None:
            frame = redimensionar_con_aspecto(frame, max(1,self.video.winfo_width()), max(1,self.video.winfo_height()))
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            foto = ImageTk.PhotoImage(Image.fromarray(rgb))
            self.video.configure(image=foto, text="")
            self.video.image = foto
        for clave, valor in datos.items():
            valor = '\u2014' if valor is None else str(valor)
            if clave=='estado':valor={'SIN_ROSTRO':'BUSCANDO','SIN_CALIBRAR':'BASE NO CALIBRADA','BASE_NO_CALIBRADA':'BASE NO CALIBRADA',
                'IMAGEN_BORROSA':'CALIDAD BAJA: falta nitidez','ANGULO_O_OCLUSION':'CALIDAD BAJA: ángulo u oclusión',
                'ILUMINACION_DEFICIENTE':'CALIDAD BAJA: iluminación','ROSTRO_MUY_PEQUENO':'CALIDAD BAJA: acércate',
                'BASE_FACIAL_VACIA':'Base facial no cargada','PREDICCION_BAJA':'VERIFICANDO','RESULTADO_TARDIO':'VERIFICANDO'}.get(valor,valor)
            if clave in self.variables and self._info_mostrada.get(clave) != valor:
                self.variables[clave].set(valor)
                self._info_mostrada[clave] = valor
        if datos and self.al_info is not None:
            self.al_info(dict(self._info_mostrada))
        self._after_id = self.ventana.after(33, self._actualizar)

    def solicitar_cierre(self, modo):
        if self._cerrada or self._cierre_solicitado:
            return
        self._cierre_solicitado = True
        self.publicar_info(estado="Finalizando..." if modo == "finalizar" else "Cancelando...")
        self.al_cerrar(modo)

    def cerrar(self):
        if self._cerrada:
            return
        self._cerrada = True
        if self._after_id is not None:
            try: self.ventana.after_cancel(self._after_id)
            except tk.TclError: pass
            self._after_id = None
        try: self.ventana.destroy()
        except tk.TclError: pass
