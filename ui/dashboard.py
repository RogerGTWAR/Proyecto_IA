from ui.ui_components import insertar_fila
from core.formato_numerico import format_numero, format_moneda
"""Dashboard de solo lectura: reutiliza consultas y no altera inventario ni SQL."""
from ui.ui_theme import SPACING_XS, SPACING_SM, SPACING_MD, SPACING_CARD, SPACING_LG, SPACING_XL

from collections import Counter, defaultdict, deque
from datetime import datetime, timedelta
from decimal import Decimal
import queue
import threading
import tkinter as tk
from tkinter import ttk

from inventory.alertas import listar_alertas
from ai.anomalies.deteccion_anomalias import listar_anomalias
from inventory.empleados import listar_empleados
from inventory.movimientos import buscar_movimientos
from inventory.productos import listar_productos
from ui.ui_theme import COLORES, FONTS, crear_panel, crear_kpi, crear_badge, lienzo_visual


def resumir(productos, empleados, alertas, movimientos, anomalias):
    """None significa fuente fallida; una lista vacía es una consulta válida sin filas."""
    kpi={k:None for k in ('productos','stock','bajo','agotados','alertas','empleados','movimientos','anomalias','valor','movimientos_dia')}
    criticos=[]; categorias=defaultdict(float); tipos=Counter(); actividad=Counter()
    if productos is not None:
        kpi.update(productos=len(productos),stock=sum(float(p['stock_actual'] or 0) for p in productos),
                   bajo=sum(str(p['estado_stock']).lower() in {'stock bajo','bajo','crítico'} for p in productos),
                   agotados=sum(str(p['estado_stock']).lower()=='agotado' for p in productos))
        kpi['valor']=sum((Decimal(str(p.get('precio',0) or 0))*Decimal(str(p['stock_actual'] or 0)) for p in productos),Decimal(0))
        criticos=sorted([p for p in productos if str(p['estado_stock']).lower() in {'stock bajo','bajo','crítico','agotado'}],
                        key=lambda p:(float(p['stock_actual'] or 0),p['nombre']))
        for p in productos: categorias[p['categoria'] or 'Sin categoría']+=float(p['stock_actual'] or 0)
    if empleados is not None: kpi['empleados']=sum(bool(e['estado']) for e in empleados)
    if alertas is not None: kpi['alertas']=sum(a['estado']=='Pendiente' for a in alertas)
    if movimientos is not None:
        kpi['movimientos']=len({m['id_movimiento'] for m in movimientos})
        kpi['movimientos_dia']=len({m['id_movimiento'] for m in movimientos if isinstance(m.get('fecha_movimiento'),datetime) and m['fecha_movimiento'].date()==datetime.now().date()})
        for m in movimientos:
            if m['tipo_movimiento'] in {'Entrada','Salida'}:
                tipos[m['tipo_movimiento']]+=float(m['cantidad'] or 0)
                actividad[m['producto']]+=float(m['cantidad'] or 0)
    if anomalias is not None and 'mensaje' not in anomalias: kpi['anomalias']=anomalias['anomalias_detectadas']
    return {'kpi':kpi,'criticos':criticos,'categorias':dict(categorias),
            'entradas_salidas':dict(tipos),'mayor_movimiento':actividad.most_common(5)}


def cargar_datos(ahora=None):
    ahora=ahora or datetime.now()
    resultado={'errores':{},'fecha':ahora,'base':'Comprobando...'}
    from core.system_state import state_manager,format_service_state
    resultado['services']=state_manager.snapshot()
    resultado['base']=format_service_state(resultado['services']['SQL'])['text']
    consultas={'productos':listar_productos,'empleados':listar_empleados,'alertas':lambda:listar_alertas(refrescar=False),
        'movimientos':lambda:buscar_movimientos(fecha_desde=(ahora-timedelta(days=29)).date().isoformat(),fecha_hasta=ahora.date().isoformat()),
        'anomalias':lambda:{'anomalias_detectadas':len(listar_anomalias())}}
    if resultado['services']['SQL']['status'] in ('OFFLINE','ERROR','DISABLED'):
        resultado['errores']['base']=resultado['services']['SQL']['message']
        for clave in consultas:resultado[clave]=None
        consultas={}
    for clave,funcion in consultas.items():
        try:resultado[clave]=funcion()
        except Exception:resultado[clave]=None;resultado['errores'][clave]='Consulta no disponible.'
    resultado.update(resumir(*(resultado[k] for k in ('productos','empleados','alertas','movimientos','anomalias'))))
    return resultado


class GraficoBarras(ttk.Frame):
    def __init__(self,padre,titulo,nota):
        super().__init__(padre,style='Card.TFrame',padding=SPACING_CARD)
        ttk.Label(self,text=titulo,font=FONTS['boton']).pack(anchor='w')
        ttk.Label(self,text=nota,style='CardTitle.TLabel').pack(anchor='w',pady=(SPACING_XS,SPACING_SM))
        self.canvas=lienzo_visual(self,bg=COLORES['tarjeta'],height=150,highlightthickness=0)
        self.canvas.pack(fill='x'); self.datos=[]; self.mensaje='Sin datos suficientes'
        self.canvas.bind('<Configure>',lambda _:self.dibujar())
    def actualizar(self,datos,mensaje='Sin datos suficientes'):
        self.datos=list(datos); self.mensaje=mensaje; self.dibujar()
    def dibujar(self):
        c=self.canvas; c.delete('all'); ancho=max(c.winfo_width(),240)
        positivos=[float(v) for _,v in self.datos if float(v)>0]
        if not positivos:
            c.create_text(ancho/2,70,text=self.mensaje,fill=COLORES['secundario'],font=FONTS['cuerpo']); return
        maximo=max(positivos); cantidad=len(self.datos); c.configure(height=max(130,cantidad*28))
        izquierda=min(160,ancho*.42); disponible=max(40,ancho-izquierda-65)
        for i,(nombre,valor) in enumerate(self.datos):
            y=i*28+18; texto=str(nombre)
            texto=texto if len(texto)<22 else texto[:19]+'…'
            c.create_text(4,y,text=texto,anchor='w',fill=COLORES['texto'],font=FONTS['pequena'])
            c.create_rectangle(izquierda,y-7,izquierda+float(valor)/maximo*disponible,y+7,fill=COLORES['acento'] if i%2 else COLORES['azul'],outline='')
            c.create_text(izquierda+float(valor)/maximo*disponible+8,y,text=f'{valor:g}',anchor='w',fill=COLORES['texto'],font=FONTS['pequena'])


class Dashboard:
    def __init__(self,padre,ventana,tabla_factory,acciones,estado_facial,estado_jarvis):
        self.padre=padre; padre.dashboard=self; self.ventana=ventana; self.cerrado=False; self.cargando=False; self.pendiente=False
        self.cola=queue.Queue(); self.after=None; self.actividad=deque(maxlen=200); self.reconocidos_por_codigo={}; self.alertas_faciales=None
        from core.event_bus import event_bus
        self.eventos=queue.Queue(maxsize=1)
        def avisar(event):
            if event.type in ('PREDICCION_GENERADA','EVIDENCIA_ACTUALIZADA'):return
            try:self.eventos.put_nowait(True)
            except queue.Full:pass
        self.suscripcion_eventos=event_bus.subscribe('*',avisar,name='dashboard:'+str(id(self)))
        self.ultimo_evento_ui=0
        self.valores={k:tk.StringVar(value='—') for k in ('productos','stock','bajo','agotados','alertas','empleados','reconocidos','movimientos','anomalias','valor','movimientos_dia')}
        self.estados_servicio={k:tk.StringVar() for k in ('SQL','CAMARA','TELEGRAM','JARVIS','SFACE','YOLO','ARDUINO','TTS','VOSK')}
        self.estado_base=self.estados_servicio['SQL']; self.actualizacion=tk.StringVar(value='Consultando datos reales...')
        self.badges_servicio={}
        from ui.ui_components import ModuleHeader,Tooltip
        ModuleHeader(padre,'Dashboard principal','Estado del almacén · movimientos de los últimos 30 días')
        estados=crear_panel(padre); estados.pack(fill='x',pady=(0,SPACING_MD))
        for i,(nombre,variable) in enumerate(tuple((n,self.estados_servicio[k]) for k,n in (('SQL','Base de datos'),('CAMARA','Cámara'),('TELEGRAM','Telegram'),('JARVIS','JARVIS'),('SFACE','SFace'),('YOLO','YOLO'),('ARDUINO','Arduino'),('TTS','TTS'),('VOSK','Vosk')))):
            bloque=ttk.Frame(estados,style='Card.TFrame'); bloque.grid(row=i//3,column=i%3,sticky='ew',padx=(0,SPACING_LG))
            ttk.Label(bloque,text=nombre,style='CardTitle.TLabel').pack(side='left',padx=(0,8))
            badge=crear_badge(bloque,variable);badge.pack(side='left',pady=2)
            self.badges_servicio[next(k for k,v in self.estados_servicio.items() if v is variable)]=badge
            estados.columnconfigure(i%3,weight=1)
        self.boton=ttk.Button(estados,text='Actualizar resumen',style='Secondary.TButton',cursor='hand2',command=self.actualizar)
        self.boton.grid(row=0,column=3,sticky='e')
        zona=ttk.Frame(padre,style='App.TFrame'); zona.pack(fill='x')
        tarjetas=(('Productos activos','productos','inventario activo','info'),('Stock total','stock','cantidad agregada','info'),
                  ('Stock bajo','bajo','sin incluir agotados','warning'),('Agotados','agotados','sin existencias','danger'),
                  ('Alertas activas','alertas','pendientes de atención','warning'),('Empleados activos','empleados','personal registrado','info'),
                  ('Reconocidos recientes','reconocidos','personas únicas · sesión / 24 h','success'),('Movimientos recientes','movimientos','operaciones únicas · 30 días','info'),
                  ('Anomalías detectadas','anomalias','análisis histórico de salidas','warning'),
                  ('Valor del inventario','valor','a precio registrado · C$','info'),
                  ('Movimientos del día','movimientos_dia','operaciones únicas · hoy','info'))
        self.etiquetas_kpi={}
        for i,(titulo,clave,nota,tono) in enumerate(tarjetas):
            card=crear_kpi(zona,titulo,self.valores[clave],'',tono)
            Tooltip(card,nota)
            valor_label=card.winfo_children()[2]; valor_label.configure(wraplength=245)
            self.etiquetas_kpi[clave]=valor_label
            card.grid(row=i//4,column=i%4,sticky='nsew',padx=(0 if i%4==0 else SPACING_MD,0),pady=(0,SPACING_MD))
            zona.columnconfigure(i%4,weight=1,uniform='dashboard_kpi')
        accesos=crear_panel(padre); accesos.pack(before=zona,fill='x',pady=(0,SPACING_MD))
        ttk.Label(accesos,text='ACCESOS RÁPIDOS',font=FONTS['boton']).pack(anchor='w',pady=(0,SPACING_MD))
        fila=ttk.Frame(accesos); fila.pack(fill='x')
        for i,(texto,callback,variante) in enumerate(acciones):
            boton=ttk.Button(fila,text=texto,command=(callback),
                            style=variante+'.TButton',cursor='hand2')
            boton.grid(row=0,column=i,sticky='ew',padx=(0 if i==0 else SPACING_SM,0))
            boton
            fila.columnconfigure(i,weight=1)
        ttk.Label(padre,textvariable=self.actualizacion,style='Subtitulo.TLabel',wraplength=800).pack(anchor='w',pady=(0,SPACING_MD))
        graficos=ttk.Frame(padre,style='App.TFrame'); graficos.pack(fill='x',pady=(0,SPACING_MD))
        self.graficos=[]
        for i,(titulo,nota) in enumerate((('Entradas vs salidas','Cantidad registrada · últimos 30 días'),('Mayor movimiento','Entradas + salidas · últimos 30 días'),('Stock por categoría','Suma de stock actual · hasta 5 categorías'))):
            grafico=GraficoBarras(graficos,titulo,nota); grafico.grid(row=0,column=i,sticky='nsew',padx=(0 if i==0 else SPACING_MD,0))
            graficos.columnconfigure(i,weight=1,uniform='graficos'); self.graficos.append(grafico)
        self.tablas={}; self.vacios={}
        for clave,titulo,columnas,titulos,anchos in (
            ('movimientos','Últimos movimientos · 30 días',('fecha_movimiento','tipo_movimiento','producto','empleado','cantidad'),('Fecha','Tipo','Producto','Empleado','Cantidad'),(155,100,210,210,100)),
            ('criticos','Productos críticos',('codigo','nombre','stock_actual','stock_minimo','estado_stock'),('Código','Producto','Stock actual','Stock mínimo','Estado'),(110,260,120,120,160)),
            ('menor_stock','Productos con menor stock',('codigo','nombre','stock_actual','stock_minimo','estado_stock'),('Código','Producto','Stock','Mínimo','Estado'),(110,260,120,120,160)),
            ('entradas','Últimas entradas · 30 días',('fecha_movimiento','producto','cantidad','ubicacion_destino'),('Fecha','Producto','Cantidad','Destino'),(155,250,120,200)),
            ('salidas','Últimas salidas · 30 días',('fecha_movimiento','producto','cantidad','ubicacion_origen'),('Fecha','Producto','Cantidad','Origen'),(155,250,120,200)),
            ('alertas','Alertas recientes',('fecha_generacion','tipo','nivel','mensaje','estado'),('Fecha','Tipo','Nivel','Mensaje','Estado'),(155,190,90,420,100)),
            ('facial','Actividad reciente del reconocimiento facial',('fecha','nombre','codigo','estado'),('Fecha','Empleado','Código','Resultado'),(170,250,140,180))):
            panel=crear_panel(padre); panel.pack(fill='x',pady=(0,SPACING_MD))
            ttk.Label(panel,text=titulo,font=(FONTS['seccion'][0],12,'bold')).pack(anchor='w',pady=(0,SPACING_SM))
            self.vacios[clave]=tk.StringVar(value='Sin datos suficientes')
            ttk.Label(panel,textvariable=self.vacios[clave],style='CardTitle.TLabel').pack(anchor='w',pady=(0,SPACING_SM))
            tabla=tabla_factory(panel,columnas,titulos,anchos,True); tabla.configure(height=4)
            self.tablas[clave]=tabla
        self._mostrar_facial()
        from ui.service_state_ui import StateBinding
        self.state_binding=StateBinding(ventana,self.mostrar_estados,padre)
        self._consumir()

    def mostrar_estados(self,snapshot):
        from core.system_state import format_service_state
        for name,var in self.estados_servicio.items():
            view=format_service_state(snapshot[name]);var.set(view['text'])
            self.badges_servicio[name].configure(foreground=view['color'])

    def actualizar(self):
        if self.cerrado: return
        if self.cargando: self.pendiente=True; return
        self.cargando=True; self.boton.configure(state='disabled'); self.actualizacion.set('Actualizando desde las consultas existentes...')
        def tarea():
            try: datos=cargar_datos()
            except Exception as error: datos={'fallo':str(error)}
            self.cola.put(datos)
        threading.Thread(target=tarea,name='dashboard-consultas',daemon=True).start()

    def _consumir(self):
        if self.cerrado: return
        import time
        if not self.eventos.empty() and time.monotonic()-self.ultimo_evento_ui>2:
            self.eventos.get_nowait();self.ultimo_evento_ui=time.monotonic()
            self.actualizar()
        try:
            datos=self.cola.get_nowait(); self.cargando=False; self.boton.configure(state='normal')
            if 'fallo' in datos:
                self.actualizacion.set('No disponible: '+datos['fallo'])
            else: self._mostrar(datos)
            if self.pendiente: self.pendiente=False; self.actualizar()
        except queue.Empty: pass
        self.after=self.ventana.after(100,self._consumir)

    def _llenar(self,clave,filas,campos,mensaje):
        tabla=self.tablas[clave]; tabla.delete(*tabla.get_children())
        for fila in filas:
            valores=[]
            for campo in campos:
                valor=fila.get(campo)
                valores.append(valor.strftime('%d/%m/%Y %H:%M') if isinstance(valor,datetime) else '—' if valor is None else valor)
            insertar_fila(tabla, '','end',values=tuple(valores))
        self.vacios[clave].set(mensaje if not filas else f'{len(filas)} registros más recientes')

    def _mostrar(self,d):
        for clave,valor in d['kpi'].items():
            texto='Sin datos suficientes' if clave=='anomalias' and d['anomalias'] is not None and valor is None else 'No disponible' if valor is None else f'C$ {valor:,.2f}' if clave=='valor' else format_numero(valor,agrupar=True) if clave=='stock' else f'{valor:,.0f}'
            self.valores[clave].set(texto)
            self.etiquetas_kpi[clave].configure(font=("Segoe UI",13 if valor is None else 22,"bold"))
        
        detalle=' · '.join(f'{k}: {v}' for k,v in d['errores'].items())
        self.actualizacion.set('Actualizado '+d['fecha'].strftime('%d/%m/%Y %H:%M:%S')+(' · Fuentes no disponibles: '+detalle if detalle else ' · Datos reales de SQL'))
        self._llenar('movimientos',(d['movimientos'] or [])[:8],('fecha_movimiento','tipo_movimiento','producto','empleado','cantidad'),'Sin datos suficientes · no hay movimientos en los últimos 30 días' if d['movimientos'] is not None else 'No disponible · consulta fallida')
        self._llenar('criticos',d['criticos'][:8],('codigo','nombre','stock_actual','stock_minimo','estado_stock'),'Sin productos críticos' if d['productos'] is not None else 'No disponible · consulta fallida')
        menores=sorted(d['productos'] or [],key=lambda p:p['stock_actual'])[:8]
        self._llenar('menor_stock',menores,('codigo','nombre','stock_actual','stock_minimo','estado_stock'),'Sin productos disponibles')
        for clave,tipo,campo in [('entradas','Entrada','ubicacion_destino'),('salidas','Salida','ubicacion_origen')]:
            filas=[m for m in d['movimientos'] or [] if m['tipo_movimiento']==tipo][:8]
            self._llenar(clave,filas,('fecha_movimiento','producto','cantidad',campo),'Sin datos suficientes · no hay movimientos de este tipo en 30 días')
        self._llenar('alertas',(d['alertas'] or [])[:8],('fecha_generacion','tipo','nivel','mensaje','estado'),'Sin alertas recientes' if d['alertas'] is not None else 'No disponible · consulta fallida')
        self.graficos[0].actualizar([(tipo,d['entradas_salidas'].get(tipo,0)) for tipo in ('Entrada','Salida')], 'Sin datos suficientes' if d['movimientos'] is not None else 'No disponible')
        self.graficos[1].actualizar(d['mayor_movimiento'],'Sin datos suficientes' if d['movimientos'] is not None else 'No disponible')
        self.graficos[2].actualizar(sorted(d['categorias'].items(),key=lambda p:p[1],reverse=True)[:5],'Sin datos suficientes' if d['productos'] is not None else 'No disponible')
        self.alertas_faciales = None if d['alertas'] is None else [
            {'fecha':a['fecha_generacion'],'nombre':'Sin identidad confirmada','codigo':None,'estado':a['tipo']}
            for a in d['alertas'] if a['tipo']=='Empleado no reconocido']
        self._mostrar_facial()

    def registrar_info_facial(self,info):
        # Invocado por el presentador en el hilo Tk, nunca por el motor de inferencia.
        if self.cerrado or str(info.get('estado','')).upper()!='RECONOCIDO': return
        codigo=info.get('codigo'); nombre=info.get('persona')
        if not codigo or codigo=='-' or not nombre or nombre=='-': return
        ahora=datetime.now()
        self.reconocidos_por_codigo[codigo]=ahora
        if self.actividad and self.actividad[0]['codigo']==codigo and (ahora-self.actividad[0]['fecha']).total_seconds()<30: return
        self.actividad.appendleft({'fecha':ahora,'nombre':nombre,'codigo':codigo,'estado':'RECONOCIDO'})
        self._mostrar_facial()

    def _mostrar_facial(self):
        limite=datetime.now()-timedelta(hours=24)
        recientes=[a for a in self.actividad if a['fecha']>=limite]
        self.reconocidos_por_codigo={c:f for c,f in self.reconocidos_por_codigo.items() if f>=limite}
        self.valores['reconocidos'].set(str(len(self.reconocidos_por_codigo)))
        actividad=sorted(recientes+(self.alertas_faciales or []),key=lambda a:a['fecha'] or datetime.min,reverse=True)
        self._llenar('facial',actividad[:8],('fecha','nombre','codigo','estado'),
                     'Sin datos suficientes · sin actividad de sesión ni alertas faciales' if self.alertas_faciales is not None else 'Sin actividad de sesión · alertas SQL no disponibles')
        if actividad:
            self.vacios['facial'].set('Reconocimientos: sesión actual / 24 h · No reconocidos: alertas guardadas en SQL')

    def cerrar(self):
        self.cerrado=True
        self.suscripcion_eventos.unsubscribe()
        self.state_binding.close()
        if self.after is not None:
            try: self.ventana.after_cancel(self.after)
            except tk.TclError: pass
