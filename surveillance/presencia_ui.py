"""Panel de presencia; Tkinter consulta snapshots y nunca procesa vídeo."""
from tkinter import ttk,messagebox
from datetime import datetime
import time
from core.config_manager import cargar_configuracion,guardar_configuracion
from surveillance.presencia_empleados import servicio_presencia,obtener_historial


class PresenciaUI:
    def __init__(self,padre,root,tabla):
        self.padre=padre;self.root=root;self.servicio=servicio_presencia;self.campos={}
        from ui.ui_components import ModuleHeader
        from ui.ui_theme import lienzo_visual,COLORES
        ModuleHeader(padre,'Presencia de empleados','Observación de personas e identificación mediante SFace. No representa un control de asistencia.')
        self.titulo=ttk.Label(padre,text='',style='CardTitle.TLabel');self.titulo.pack(anchor='w')
        barra=ttk.Frame(padre);barra.pack(fill='x',pady=8)
        ttk.Button(barra,text='Iniciar presencia',command=self.iniciar,style='Primary.TButton').pack(side='left')
        ttk.Button(barra,text='Detener',command=self.servicio.parar,style='Secondary.TButton').pack(side='left',padx=6)
        avanzado=ttk.Frame(padre)
        def alternar():
            if avanzado.winfo_manager():avanzado.pack_forget()
            else:avanzado.pack(fill='x',after=barra)
        ttk.Button(barra,text='Configuración avanzada',command=alternar,style='Ghost.TButton').pack(side='left')
        cfg=cargar_configuracion()['vigilancia']
        for i,(key,label) in enumerate((('camera_source_employees','Fuente USB / URL'),('camera_name_employees','Nombre de cámara'),
            ('room_name','Habitación'),('presence_confidence','Confianza YOLO'),('presence_face_interval','Intervalo facial (s)'),('presence_exit_timeout','Tiempo para salida (s)'))):
            f=ttk.Frame(avanzado);f.grid(row=i//3,column=i%3,sticky='ew',padx=5,pady=4)
            ttk.Label(f,text=label).pack(anchor='w');w=ttk.Entry(f,width=28);w.insert(0,str(cfg[key]));w.pack(fill='x');self.campos[key]=w
            avanzado.columnconfigure(i%3,weight=1)
        ttk.Button(avanzado,text='Guardar ajustes',command=self.guardar).grid(row=2,column=2,sticky='e',pady=6)
        self.estado=ttk.Label(padre,text='Sin observación actual.');self.estado.pack(anchor='w')
        kpis=ttk.Frame(padre);kpis.pack(fill='x',pady=8);self.kpis={}
        for key,label in (('personas','Personas'),('identificados','Identificados'),('desconocidos','Desconocidos'),('pendientes','Sin identidad'),('fps','FPS')):
            f=ttk.LabelFrame(kpis,text=label,padding=8);f.pack(side='left',fill='x',expand=True,padx=3)
            v=ttk.Label(f,text='—',style='CardTitle.TLabel');v.pack();self.kpis[key]=v
        contenido=ttk.Frame(padre);contenido.pack(fill='both',expand=True)
        self.canvas=lienzo_visual(contenido,height=290,background=COLORES['video'],highlightthickness=0)
        self.canvas.pack(side='left',fill='both',expand=True,padx=(0,8))
        lateral=ttk.Frame(contenido,width=310);lateral.pack(side='right',fill='y')
        ttk.Label(lateral,text='Presentes ahora',style='CardTitle.TLabel').pack(anchor='w')
        self.presentes=tabla(lateral,('track','identidad','similitud','desde'),('Track','Empleado / estado','SFace','Desde'),(50,235,65,65));self.presentes.configure(height=10)
        ttk.Label(padre,text='Eventos recientes',style='CardTitle.TLabel').pack(anchor='w',pady=(8,3))
        self.eventos=tabla(padre,('fecha','evento','track','empleado','estado','duracion'),
            ('Fecha y hora','Evento','Track','Empleado','Estado','Duración (s)'),(155,235,50,180,160,90));self.eventos.configure(height=4)
        self.firma=None;self.actualizar()

    def guardar(self):
        try:
            if self.servicio.obtener_estado()['activo']:raise ValueError('Detenga la cámara de presencia antes de cambiar sus ajustes.')
            c=cargar_configuracion();v=c['vigilancia']
            for k,w in self.campos.items():
                s=w.get().strip()
                v[k]=(int(s) if s.isdecimal() else s) if k=='camera_source_employees' else float(s) if k.startswith('presence_') else s
            guardar_configuracion(c);self.estado.configure(text='Ajustes guardados.')
            return True
        except Exception as e:messagebox.showerror('Presencia',str(e),parent=self.root);return False

    def iniciar(self):
        if self.guardar():
            try:self.servicio.iniciar(cargar_configuracion()['vigilancia'])
            except Exception as e:messagebox.showerror('Presencia',str(e),parent=self.root)

    def actualizar(self):
        if not self.padre.winfo_exists():return
        from surveillance.presencia_empleados import obtener_conteo_actual,obtener_personas_presentes
        from surveillance.vigilancia_ui import pintar_frame
        state=self.servicio.obtener_estado();counts=obtener_conteo_actual()
        ahora=time.monotonic()
        if not hasattr(self,'cfg_nombre') or ahora-self._config_leida>3:
            self.cfg_nombre=cargar_configuracion()['vigilancia'];self._config_leida=ahora
        cfg=self.cfg_nombre
        self.titulo.configure(text=cfg['camera_name_employees']+' · '+cfg['room_name'])
        self.estado.configure(text=state['estado']+' · '+state['detalle'])
        for k,w in self.kpis.items():
            value=state['fps'] if k=='fps' else counts[k]
            w.configure(text=f'{value:.1f}' if k=='fps' else '—' if value is None else str(value))
        if state['frame'] is not None and self.canvas.winfo_viewable():pintar_frame(self.canvas,state['frame'])
        elif state['frame'] is None:
            self.canvas.delete('all');self.canvas.create_text(20,25,text=state['detalle'],anchor='nw',fill='white')
        rows=obtener_personas_presentes();events=obtener_historial()[:40]
        firma=(repr(rows),repr(events))
        if firma!=self.firma:
            self.firma=firma
            for table in (self.presentes,self.eventos):table.delete(*table.get_children())
            for t in rows:
                nombre=((t.get('codigo_empleado') or '')+' · '+t['nombre']) if t.get('nombre') else t['estado_identidad']
                score=t.get('similitud_facial')
                self.presentes.insert('','end',values=(t['track_id'],nombre,f'{score:.2f}' if score is not None else '—',datetime.fromisoformat(t['presente_desde']).strftime('%H:%M:%S')))
            for e in events:
                self.eventos.insert('','end',values=(datetime.fromisoformat(e['fecha_hora']).strftime('%d/%m %H:%M:%S'),e['tipo_evento'].replace('_',' '),e['track_id'],e.get('nombre') or '—',e['estado_identidad'],e.get('duracion') if e.get('duracion') is not None else '—'))
        self.root.after(250,self.actualizar)
