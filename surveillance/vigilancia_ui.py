"""Pantalla de vigilancia y editor de polígonos; Tk solo consume resultados."""
from copy import deepcopy
from pathlib import Path
import json
import time
import tkinter as tk
from tkinter import ttk, messagebox

from PIL import Image, ImageTk
import cv2

from core.config_manager import cargar_configuracion, guardar_configuracion
from ui.tareas_ui import TrabajosUI
from ui.ui_theme import crear_panel, lienzo_visual, SPACING_MD
from surveillance.vigilancia_yolo import servicio_vigilancia, validar_poligono, listar_eventos
from integrations.telegram.telegram_service import estado_telegram, probar_telegram


def actualizar_entregas_evento(evento):
    from integrations.telegram.telegram_service import servicio_telegram,referencia_evento_visual
    e=dict(evento)
    resumen=[]
    for parte,sufijo in (('foto','foto'),('video','video')):
        estado=servicio_telegram.estado_entrega(referencia_evento_visual(e,video=parte=='video'))
        if estado:
            e['telegram_'+parte]=estado['detalle']
            e['telegram_'+parte+'_estado']=estado['estado']
            e['telegram_'+parte+'_enviado']=estado.get('enviado',False)
            if estado.get('registrado_sql'):e['sql_estado']='Registrado'
            enviados=[{'foto':'Foto enviada','recorte':'Recorte enviado','texto':'Texto enviado','video':'Clip enviado'}.get(k,'Detalle enviado')
                for k,v in estado.get('partes',{}).items() if v.get('enviado')]
            resumen.append(' · '.join(enviados)+(' · Confirmado' if estado['estado']=='ENVIADA' else ' · '+estado['detalle']) if enviados else estado['detalle'])
    if resumen:e['telegram_resumen']=' / '.join(resumen)
    return e


def pintar_frame(canvas, frame):
    """Letterboxing: el editor y el vídeo conservan la misma relación de aspecto."""
    if frame is None:return None
    h,w=frame.shape[:2];cw,ch=max(2,canvas.winfo_width()),max(2,canvas.winfo_height())
    escala=min(cw/w,ch/h);nw,nh=max(1,int(w*escala)),max(1,int(h*escala))
    x,y=(cw-nw)/2,(ch-nh)/2
    foto=ImageTk.PhotoImage(Image.fromarray(cv2.cvtColor(frame,cv2.COLOR_BGR2RGB)).resize((nw,nh)))
    canvas.delete('all');canvas.create_image(x,y,image=foto,anchor='nw');canvas._foto=foto
    return x,y,nw,nh


class VigilanciaUI:
    def __init__(self,padre,root,tabla):
        self.contenedor=padre
        tabs=ttk.Notebook(padre);tabs.pack(fill='both',expand=True)
        intrusion=ttk.Frame(tabs,padding=8);presencia=ttk.Frame(tabs,padding=8)
        tabs.add(intrusion,text='Intrusión');tabs.add(presencia,text='Presencia de empleados')
        from surveillance.presencia_ui import PresenciaUI
        self.presencia_ui=PresenciaUI(presencia,root,tabla)
        padre=intrusion
        self.padre=padre;self.root=root;self.trabajo=TrabajosUI(root);self.servicio=servicio_vigilancia
        self.cfg=deepcopy(cargar_configuracion()['vigilancia']);self.campos={};self.historial=[];self.editor=None
        from ui.ui_components import ModuleHeader
        ModuleHeader(padre,'Vigilancia / Intrusión','Cámara en vivo y eventos de acceso a la zona configurada.')
        toggle=ttk.Button(padre,text='Configuración avanzada ▼',style='Ghost.TButton')
        toggle.pack(anchor='w',pady=(0,8))
        panel=crear_panel(padre,SPACING_MD)
        def alternar():
            visible=bool(panel.winfo_manager())
            if visible:panel.pack_forget()
            else:panel.pack(fill='x',after=toggle)
            toggle.configure(text='Configuración avanzada ▼' if visible else 'Configuración avanzada ▲')
        toggle.configure(command=alternar)
        campos=[('camera_source','Cámara: índice USB o URL'),('camera_name','Nombre de cámara'),
                ('yolo_model','Modelo YOLO local'),('confidence_threshold','Confianza mínima'),
                ('zone_name','Nombre de zona'),('cooldown_seconds','Cooldown (segundos)'),
                ('clip_before_seconds','Clip: segundos anteriores'),('clip_after_seconds','Clip: segundos posteriores')]
        for i,(k,titulo) in enumerate(campos):
            f=ttk.Frame(panel);f.grid(row=i//4,column=i%4,sticky='ew',padx=4,pady=4)
            ttk.Label(f,text=titulo).pack(anchor='w');w=ttk.Entry(f,width=23);w.insert(0,str(self.cfg[k]));w.pack(fill='x')
            self.campos[k]=w;panel.columnconfigure(i%4,weight=1)
        barra=ttk.Frame(padre);barra.pack(fill='x',pady=10)
        self.telegram=tk.BooleanVar(value=cargar_configuracion()['telegram']['vigilancia'])
        ttk.Checkbutton(barra,text='Telegram: categoría Vigilancia',variable=self.telegram).pack(side='left')
        ttk.Button(panel,text='Guardar ajustes',command=self.guardar,style='Secondary.TButton').grid(row=2,column=3,sticky='e',pady=8)
        ttk.Button(barra,text='Configurar zona',command=self.configurar_zona,style='Secondary.TButton').pack(side='left',padx=4)
        ttk.Button(barra,text='Iniciar vigilancia',command=self.iniciar,style='Primary.TButton').pack(side='left',padx=4)
        ttk.Button(barra,text='Detener',command=self.servicio.parar,style='Secondary.TButton').pack(side='left',padx=4)
        ttk.Button(panel,text='Probar Telegram',command=self.probar,style='Secondary.TButton').grid(row=2,column=2,sticky='e',pady=8)
        self.estado=ttk.Label(padre,text='Inactivo',wraplength=1050);self.estado.pack(anchor='w')
        self.zona=ttk.Label(padre,text='');self.zona.pack(anchor='w')
        from ui.ui_theme import COLORES
        self.canvas=lienzo_visual(padre,height=280,background=COLORES['video'],highlightthickness=0)
        self.canvas.pack(fill='both',expand=True,pady=10)
        ttk.Label(padre,text='Eventos recientes',style='CardTitle.TLabel').pack(anchor='w')
        self.tabla=tabla(padre,('fecha','tipo','categoria','camara','zona','track','identidad','sql','telegram'),
            ('Fecha y hora','Tipo','Categoría','Cámara','Zona','Track','Identidad','SQL','Telegram'),(160,165,110,160,140,55,180,110,270))
        self.tabla.configure(height=4)
        ttk.Button(padre,text='Actualizar eventos',command=self.cargar_historial).pack(anchor='w',pady=6)
        self.tabla.bind('<Double-1>',self.detalle)
        self.cargar_historial();self.actualizar()

    def leer(self):
        c=deepcopy(self.cfg)
        for k,w in self.campos.items():
            valor=w.get().strip()
            if k=='camera_source':valor=int(valor) if valor.isdecimal() else valor
            elif k in ('confidence_threshold','cooldown_seconds','clip_before_seconds','clip_after_seconds'):valor=float(valor)
            c[k]=valor
        if c['camera_source']!=self.cfg['camera_source']:c['zone_polygon']=[]
        c['camera_source_intrusion']=c['camera_source']
        c['telegram_enabled']=self.telegram.get()
        from surveillance.vigilancia_yolo import validar_configuracion
        return validar_configuracion(c)

    def persistir(self,c):
        config=cargar_configuracion();config['vigilancia']=c
        config['telegram']['vigilancia']=self.telegram.get()
        guardar_configuracion(config);self.cfg=c

    def guardar(self):
        try:
            if self.servicio.obtener_estado()['activo']:raise ValueError('Detenga la cámara antes de cambiar la configuración.')
            self.persistir(self.leer());self.estado.configure(text='Ajustes guardados.')
        except Exception as e:messagebox.showerror('Vigilancia',str(e),parent=self.root)

    def iniciar(self):
        try:
            if self.servicio.obtener_estado()['activo']:raise ValueError('La cámara ya está en uso.')
            c=self.leer();validar_poligono(c['zone_polygon']);c['intrusion_enabled']=True
            self.persistir(c);self.servicio.iniciar(c)
        except Exception as e:messagebox.showerror('Vigilancia',str(e),parent=self.root)

    def probar(self):
        self.trabajo.ejecutar(probar_telegram,lambda r:messagebox.showinfo('Telegram',r['detalle'],parent=self.root))

    def cargar_historial(self):
        def mostrar(filas):self.historial=filas;self.mostrar_eventos(filas)
        def cargar():
            filas=listar_eventos()
            from integrations.telegram.telegram_service import servicio_telegram,referencia_evento_visual,LOG
            try:servicio_telegram.recuperar_estados([referencia_evento_visual(e,video=v) for e in filas[:100] for v in (False,True)])
            except Exception:LOG.warning('No se pudo consultar SQL para el historial; se conserva la evidencia local.')
            return filas
        self.trabajo.ejecutar(cargar,mostrar)

    def mostrar_eventos(self,filas):
        from surveillance.identidad_vigilancia import texto_identidad
        self.filas=[actualizar_entregas_evento(e) for e in filas];self.tabla.delete(*self.tabla.get_children())
        filas=self.filas
        for i,e in enumerate(filas[:100]):
            from ui.ui_components import insertar_fila
            insertar_fila(self.tabla,iid=str(i),values=(e['fecha_hora'],e.get('tipo_evento','INTRUSIÓN'),
                e.get('categoria','Vigilancia'),e.get('camara','No disponible'),e['zona'],
                e['track_id'],texto_identidad(e),e.get('sql_estado','pendiente'),e.get('telegram_resumen',e.get('telegram_foto','pendiente'))))

    def detalle(self,_evento=None):
        seleccion=self.tabla.selection()
        if not seleccion:return
        e=self.filas[int(seleccion[0])];ventana=tk.Toplevel(self.root);ventana.title('Detalle de intrusión');ventana.geometry('760x500')
        from tkinter.scrolledtext import ScrolledText
        texto=ScrolledText(ventana,wrap='word');texto.pack(fill='both',expand=True,padx=12,pady=12)
        texto.insert('1.0',json.dumps(e,ensure_ascii=False,indent=2));texto.configure(state='disabled')
        def abrir():
            import os
            ruta=Path(e['metadata']).parent
            if ruta.is_dir():os.startfile(str(ruta))
        ttk.Button(ventana,text='Abrir carpeta de evidencia',command=abrir).pack(pady=8)

    def actualizar(self):
        if not self.padre.winfo_exists():return
        e=self.servicio.obtener_estado();telegram=estado_telegram()
        detalle=e['detalle']
        if not e['preview'] and e['activo']:detalle+=' · '+e.get('facial','')
        medida='FPS de vista previa' if e['preview'] else 'FPS de vigilancia'
        from core.system_state import state_manager,format_service_state
        snapshot=state_manager.snapshot()
        camera=format_service_state(snapshot['CAMARA_1']);yolo=format_service_state(snapshot['YOLO'])
        self.estado.configure(text=f"{self.cfg['camera_name']}: {camera['text']} · YOLO: {yolo['text']} · {e['fps']:.1f} {medida} · {detalle}",foreground=camera['color'])
        self.zona.configure(text=f"Zona: {len(self.cfg['zone_polygon'])} vértices · {telegram['detalle']}"+
            (' Envíos desactivados.' if not self.telegram.get() else ''))
        if e['frame'] is not None:pintar_frame(self.canvas,e['frame'])
        grabador=self.servicio.evidencia
        if grabador:
            with grabador.lock:actuales=deepcopy(list(grabador.recientes))
            ids={x['id_evento'] for x in actuales}
            filas=actuales+[x for x in self.historial if x['id_evento'] not in ids]
            filas=[actualizar_entregas_evento(x) for x in filas]
            firma=[(x['id_evento'],x.get('sql_estado'),x.get('telegram_resumen',x.get('telegram_foto')),x.get('clip'),
                    x.get('estado_identidad'),x.get('nombre')) for x in filas]
            if firma!=getattr(self,'_firma',None):self._firma=firma;self.mostrar_eventos(filas)
        self.root.after(100,self.actualizar)

    def configurar_zona(self):
        try:
            if self.editor and self.editor.winfo_exists():self.editor.lift();return
            if self.servicio.obtener_estado()['activo']:raise ValueError('Detenga vigilancia antes de configurar la zona.')
            c=self.leer();self.servicio.iniciar(c,preview=True)
        except Exception as e:messagebox.showerror('Zona',str(e),parent=self.root);return
        ventana=tk.Toplevel(self.root);self.editor=ventana;ventana.title('Configurar zona restringida');ventana.geometry('1000x650')
        ttk.Label(ventana,text='Marque los vértices en orden sobre la imagen. Se necesitan al menos tres; los lados no pueden cruzarse.',wraplength=900).pack(pady=8)
        canvas=lienzo_visual(ventana,background='#152536',highlightthickness=0);canvas.pack(fill='both',expand=True,padx=12)
        puntos=deepcopy(c['zone_polygon']);transformacion=[None];cerrado=[False]
        estado=ttk.Label(ventana,text='Abriendo cámara…');estado.pack(anchor='w',padx=12)
        def cerrar():
            cerrado[0]=True;self.servicio.parar();ventana.destroy()
        def guardar():
            try:
                if transformacion[0] is None:raise ValueError('Espere a que la cámara entregue una imagen.')
                validar_poligono(puntos);c['zone_polygon']=deepcopy(puntos);self.persistir(c);cerrar()
            except Exception as e:messagebox.showerror('Zona',str(e),parent=ventana)
        def clic(evento):
            if transformacion[0] is None:return
            x,y,w,h=transformacion[0];px,py=(evento.x-x)/w,(evento.y-y)/h
            if 0<=px<=1 and 0<=py<=1 and len(puntos)<20:puntos.append([px,py])
        canvas.bind('<Button-1>',clic)
        pie=ttk.Frame(ventana);pie.pack(fill='x',padx=12,pady=8)
        ttk.Button(pie,text='Guardar zona',command=guardar,style='Primary.TButton').pack(side='left',padx=4)
        ttk.Button(pie,text='Limpiar',command=puntos.clear).pack(side='left',padx=4)
        ttk.Button(pie,text='Cancelar',command=cerrar).pack(side='left',padx=4)
        ventana.protocol('WM_DELETE_WINDOW',cerrar)
        def refrescar():
            if cerrado[0] or not ventana.winfo_exists():return
            s=self.servicio.obtener_estado();estado.configure(text=s['detalle']+f' · {len(puntos)} vértices')
            transformacion[0]=pintar_frame(canvas,s['frame'])
            if transformacion[0]:
                x,y,w,h=transformacion[0];coords=[v for px,py in puntos for v in (x+px*w,y+py*h)]
                if len(puntos)>=3:canvas.create_polygon(*coords,fill='#ef4444',stipple='gray25',outline='#fca5a5',width=2)
                elif len(puntos)==2:canvas.create_line(*coords,fill='#fca5a5',width=2)
                for i,(px,py) in enumerate(puntos):
                    cx,cy=x+px*w,y+py*h;canvas.create_oval(cx-4,cy-4,cx+4,cy+4,fill='white')
                    canvas.create_text(cx+10,cy-10,text=str(i+1),fill='white')
            ventana.after(100,refrescar)
        refrescar()
