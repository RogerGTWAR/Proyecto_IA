from ui.ui_components import insertar_fila
from core.formato_numerico import format_numero
"""Mapa lógico, derivado de ubicaciones reales; no representa distancias físicas."""
from ui.ui_theme import SPACING_XS, SPACING_SM, SPACING_MD, SPACING_CARD, SPACING_LG, SPACING_XL
from inventory.inventario_service import consultar
from inventory.organizacion_fisica import PRODUCTOS_POR_NIVEL, describir_posicion, numero_led, numero_fisico
from ui.ui_theme import marco_visual, etiqueta_visual, COLORES as PALETA

def ubicaciones_mapa():
    return consultar('''SELECT u.*, COALESCE(s.productos,0) productos
        FROM ubicaciones u LEFT JOIN (
          SELECT e.id_ubicacion,COUNT(DISTINCT e.id_producto) productos
          FROM existencias e JOIN productos p ON p.id_producto=e.id_producto
          WHERE e.fecha_eliminacion IS NULL
            AND p.estado=1 AND p.fecha_eliminacion IS NULL GROUP BY e.id_ubicacion
        ) s ON s.id_ubicacion=u.id_ubicacion
        WHERE u.estado=1 AND u.fecha_eliminacion IS NULL ORDER BY u.codigo_ubicacion''')

def productos_ubicacion(id_ubicacion):
    return consultar('''SELECT p.id_producto,p.codigo,p.nombre,e.cantidad,p.unidad_medida,e.posicion
        FROM existencias e JOIN productos p ON p.id_producto=e.id_producto
        WHERE e.id_ubicacion=? AND e.fecha_eliminacion IS NULL
        AND p.estado=1 AND p.fecha_eliminacion IS NULL ORDER BY e.posicion''',id_ubicacion)

def ubicaciones_producto(id_producto):
    return consultar('''SELECT u.*,e.cantidad,e.posicion,p.unidad_medida FROM existencias e
        JOIN ubicaciones u ON u.id_ubicacion=e.id_ubicacion
        JOIN productos p ON p.id_producto=e.id_producto
        WHERE e.id_producto=? AND e.fecha_eliminacion IS NULL
        AND u.estado=1 AND u.fecha_eliminacion IS NULL
        AND p.estado=1 AND p.fecha_eliminacion IS NULL ORDER BY u.codigo_ubicacion''',id_producto)

def describir_ubicacion(u):
    if str(u.get('codigo_ubicacion','')).startswith('E') and u.get('estante') and u.get('nivel'):
        return describir_posicion(u).replace(' - ', ', ')
    campos=(('almacen','Almacén'),('zona','Zona'),('seccion','Sección'),
            ('pasillo','Pasillo'),('estante','Estante'),('nivel','Nivel'))
    partes=[f'{titulo} {u[c]}' for c,titulo in campos if u.get(c)]
    return ', '.join(partes) or u['codigo_ubicacion']

def buscar_productos_mapa(texto):
    """Usar los mismos nombres, plurales y códigos que entiende el agente."""
    from inventory.inventario_service import buscar_inventario
    from jarvis.nlp_jarvis import procesador_nlp
    filas=buscar_inventario(texto)
    if not filas and texto.strip():
        filas=procesador_nlp.resolver_producto(procesador_nlp.interpretar(texto),buscar_inventario())
    return filas


class MapaAlmacenUI:
    """Presentación del mapa; conserva consultas, posiciones y servicio LED."""

    COLORES = {'libre': PALETA['fila_alterna'], 'NORMAL': PALETA['success_bg'], 'BAJO': PALETA['warning_bg'],
               'CRÍTICO': PALETA['danger_bg'], 'AGOTADO': PALETA['danger_bg'],
               'seleccion': PALETA['seleccion'], 'busqueda': PALETA['chat_usuario'],
               'borde': PALETA['borde'], 'azul': PALETA['azul'], 'led': PALETA['aviso']}

    def __init__(self, padre, root, tabla, ver_producto=None):
        import tkinter as tk
        from tkinter import ttk
        from ui.ui_theme import crear_panel
        from ui.tareas_ui import TrabajosUI
        self.padre, self.root = padre, root
        self.ver_producto = ver_producto
        self.resaltados, self.roles_ubicacion = set(), {}
        self.seleccion = self.posicion_led = None
        self.resultados_posiciones = set()
        self.trabajo_led = TrabajosUI(root)
        self.datos, self.contenido = [], []
        self._tooltip = None
        from ui.ui_components import ModuleHeader
        ModuleHeader(padre,'Mapa del almacén','Vista lógica de las ubicaciones registradas en el almacén.')
        filtros = crear_panel(padre, 8)
        filtros.pack(fill='x')
        self.almacen = ttk.Combobox(filtros, state='readonly', width=15)
        self.almacen.set('Todos')
        self.zona = ttk.Combobox(filtros, state='readonly', width=11)
        self.zona.set('Todas')
        self.busqueda = ttk.Entry(filtros)
        for i, (nombre, widget) in enumerate((('Almacén', self.almacen), ('Zona', self.zona),
                                             ('Buscar', self.busqueda))):
            ttk.Label(filtros, text=nombre, style='CardTitle.TLabel').grid(row=0, column=i*2, sticky='w', padx=(0, 5))
            widget.grid(row=0, column=i*2+1, sticky='ew', padx=(0, 10))
        filtros.columnconfigure(5, weight=1)
        ttk.Button(filtros, text='Buscar', command=self.buscar, style='Primary.TButton', padding=(8, 4)).grid(row=0, column=6)
        ttk.Button(filtros, text='↻ Actualizar', command=self.refrescar,
                   style='Secondary.TButton', padding=(8, 4)).grid(row=0, column=7, padx=(6, 0))
        for widget in (self.almacen, self.zona):
            widget.bind('<<ComboboxSelected>>', lambda _: self.refrescar())
        self.busqueda.bind('<Return>', lambda _: self.buscar())

        indicadores = ttk.Frame(padre, style='App.TFrame')
        indicadores.pack(fill='x', pady=(6, 4))
        self.indicadores = {}
        for i, nombre in enumerate(('Estantes', 'Niveles', 'Productos', 'Posiciones ocupadas', 'Agotados')):
            tarjeta = crear_panel(indicadores, 7)
            tarjeta.grid(row=0, column=i, sticky='nsew', padx=(0, 6 if i < 4 else 0))
            indicadores.columnconfigure(i, weight=1, uniform='kpi_mapa')
            valor = ttk.Label(tarjeta, text='—', font=('Segoe UI', 11, 'bold'))
            valor.pack(side='left')
            ttk.Label(tarjeta, text='Ocupadas' if nombre == 'Posiciones ocupadas' else nombre,
                      style='CardTitle.TLabel').pack(side='left', padx=(6, 0))
            self.indicadores[nombre] = valor
        leyenda = ttk.Frame(padre, style='App.TFrame')
        leyenda.pack(fill='x')
        for i, (nombre, color) in enumerate((('Disponible', self.COLORES['libre']),
                ('Asignado', self.COLORES['NORMAL']), ('Seleccionado', '#94B6E0'),
                ('Búsqueda', '#82D0C5'), ('Bajo', '#E5BF74'),
                ('Agotado', '#DF9EA5'), ('LED', self.COLORES['led']))):
            item = ttk.Frame(leyenda, style='App.TFrame')
            item.pack(side='left', padx=(0, 8))
            etiqueta_visual(item, text='■', foreground=color, background='#F3F6FA',
                     font=('Segoe UI', 9)).pack(side='left')
            ttk.Label(item, text=nombre, style='Subtitulo.TLabel', font=('Segoe UI', 8)).pack(side='left')
        self.resumen = ttk.Label(padre, text='', style='Subtitulo.TLabel', font=('Segoe UI', 9))
        self.resumen.pack(anchor='w', pady=(2, 4))

        self.distribucion = ttk.Frame(padre, style='App.TFrame')
        self.distribucion.pack(fill='both', expand=True)
        self.plano = ttk.Frame(self.distribucion, style='App.TFrame')
        self.panel_detalle = crear_panel(self.distribucion, 12)
        self.panel_detalle.configure(width=240)
        self.panel_detalle.grid_propagate(True)
        self.plano.grid(row=0, column=0, sticky='new', padx=(0, 10))
        self.panel_detalle.grid(row=0, column=1, sticky='new')
        self.distribucion.columnconfigure(0, weight=1)
        self.distribucion.columnconfigure(1, weight=0, minsize=240)
        self.panel_detalle.columnconfigure(0, weight=1)
        ttk.Label(self.panel_detalle, text='DETALLE', font=('Segoe UI', 10, 'bold')).grid(
            row=0, column=0, sticky='w', pady=(0, 6))
        self.detalle_contenido = ttk.Frame(self.panel_detalle)
        self.detalle_contenido.grid(row=1, column=0, sticky='ew')
        controles = ttk.Frame(self.panel_detalle)
        controles.grid(row=2, column=0, sticky='ew', pady=(8, 0))
        self.estado_led = ttk.Label(controles, text='○ LED apagado', wraplength=220)
        self.estado_led.pack(anchor='w', pady=(0, 5))
        self.boton_led = ttk.Button(controles, text='Seleccione una posición', state='disabled',
                                    command=self.encender_seleccion, style='Primary.TButton', padding=(8, 4))
        self.boton_led.pack(fill='x')
        self.boton_producto = ttk.Button(controles, text='Ver producto', state='disabled',
                                         command=self.abrir_producto, style='Secondary.TButton', padding=(8, 4))
        self.boton_producto.pack(fill='x', pady=(5, 0))
        arduino = ttk.Frame(controles)
        arduino.pack(fill='x', pady=(8, 5))
        ttk.Label(arduino, text='Arduino:', style='CardTitle.TLabel').pack(side='left')
        self.badge_arduino = ttk.Label(arduino, text='SIN VERIFICAR', padding=(6, 3),
                                       background='#EEF2F7', font=('Segoe UI', 8, 'bold'))
        self.badge_arduino.pack(side='right')
        ttk.Button(controles, text='Apagar todos', command=self.apagar_leds,
                   style='Secondary.TButton', padding=(8, 4)).pack(fill='x')
        self.mensaje_led = ttk.Label(controles, text='', wraplength=225, style='CardTitle.TLabel')
        self.mensaje_led.pack(anchor='w', pady=(4, 0))
        self.distribucion.bind('<Configure>', self._distribuir)
        self.plano.bind('<Configure>', lambda e: self.organizar_estantes(e.width))
        self.refrescar()
        self.actualizar_leds()

    def _distribuir(self, evento):
        lateral = evento.width >= 900
        if lateral == getattr(self, '_lateral', None):
            return
        self._lateral = lateral
        self.panel_detalle.grid_forget()
        self.plano.grid_configure(columnspan=1 if lateral else 2, padx=(0, 10 if lateral else 0))
        self.panel_detalle.grid(row=0 if lateral else 1, column=1 if lateral else 0,
                                columnspan=1 if lateral else 2, sticky='new', pady=(0 if lateral else 10, 0))
        self.distribucion.columnconfigure(1, minsize=240 if lateral else 0)

    def _ocultar_tooltip(self, _=None):
        if self._tooltip is not None:
            self._tooltip.destroy()
            self._tooltip = None

    def _tooltip_nombre(self, widget, texto):
        import tkinter as tk
        def mostrar(_):
            self._ocultar_tooltip()
            ventana = tk.Toplevel(self.root)
            ventana.overrideredirect(True)
            ventana.geometry(f'+{widget.winfo_rootx()}+{widget.winfo_rooty()+widget.winfo_height()+4}')
            etiqueta_visual(ventana, text=texto, wraplength=320, justify='left', padx=10, pady=6,
                     background='#16324F', foreground='white', font=('Segoe UI', 10)).pack()
            self._tooltip = ventana
        widget.bind('<Enter>', mostrar)
        widget.bind('<Leave>', self._ocultar_tooltip)
        widget.bind('<Destroy>', self._ocultar_tooltip, add='+')

    def refrescar(self):
        from tkinter import messagebox
        from jarvis.nlp_jarvis import normalizar_texto
        from inventory.inventario_service import buscar_inventario, estado_stock
        try:
            self._ocultar_tooltip()
            self.datos = ubicaciones_mapa()
            self.almacen.configure(values=['Todos'] + sorted({u['almacen'] for u in self.datos if u.get('almacen')}))
            self.zona.configure(values=['Todas'] + sorted({u['zona'] for u in self.datos if u.get('zona')}))
            texto = self.busqueda.get().strip()
            self.resultados_posiciones = set()
            if texto:
                productos = buscar_productos_mapa(texto)
                self.resaltados = set()
                for p in productos:
                    for u in ubicaciones_producto(p['id_producto']):
                        self.resaltados.add(u['id_ubicacion'])
                        self.resultados_posiciones.add((u['id_ubicacion'], int(u['posicion'])))
                lugares = {u['id_ubicacion'] for u in self.datos if normalizar_texto(texto) in
                           normalizar_texto(describir_ubicacion(u) + ' ' + u['codigo_ubicacion'])}
                self.resaltados.update(lugares)
                self.resultados_posiciones.update((uid, pos) for uid in lugares for pos in range(1, PRODUCTOS_POR_NIVEL + 1))
                self.roles_ubicacion.clear()
            self.contenido = consultar('''SELECT e.id_ubicacion,e.posicion,p.id_producto,p.codigo,p.nombre,e.cantidad,p.unidad_medida
                FROM existencias e JOIN productos p ON p.id_producto=e.id_producto
                WHERE e.fecha_eliminacion IS NULL AND p.estado=1 AND p.fecha_eliminacion IS NULL''')
            # El estado es el del producto global, según el motor actual de inventario.
            self.catalogo = {p['id_producto']: p for p in buscar_inventario()}
            for p in self.contenido:
                global_p = self.catalogo.get(p['id_producto'])
                p['estado_mapa'] = ('AGOTADO' if p['cantidad'] == 0 else
                                    estado_stock(global_p['stock_actual'], global_p['stock_minimo'])
                                    if global_p else 'NORMAL')
            self.visibles = [u for u in self.datos if
                (self.almacen.get() == 'Todos' or u.get('almacen') == self.almacen.get()) and
                (self.zona.get() == 'Todas' or u.get('zona') == self.zona.get())]
            ids_visibles = {u['id_ubicacion'] for u in self.visibles}
            if self.seleccion not in ids_visibles:
                self.seleccion = self.posicion_led = None
            grupos = {}
            for u in self.visibles:
                grupos.setdefault(u['estante'], []).append(u)
            for w in self.plano.winfo_children():
                w.destroy()
            self.tarjetas_estantes, self.espacios = [], []
            for clave, filas in sorted(grupos.items(), key=lambda par: numero_fisico(par[0])):
                self._crear_estante(clave, filas)
            self.organizar_estantes(self.plano.winfo_width())
            productos = [p for p in self.contenido if p['id_ubicacion'] in ids_visibles]
            valores = (len(grupos), len(self.visibles), len({p['id_producto'] for p in productos}),
                       f'{len(productos)}/{len(self.visibles)*PRODUCTOS_POR_NIVEL}',
                       len({p['id_producto'] for p in productos if p['estado_mapa'] == 'AGOTADO'}))
            for nombre, valor in zip(self.indicadores, valores):
                self.indicadores[nombre].configure(text=str(valor))
            self.resumen.configure(text=('No se encontró un producto o ubicación con ese criterio.' if texto and not
                (self.resaltados & ids_visibles) else f'{len(self.resultados_posiciones & {(u, p) for u in ids_visibles for p in range(1, PRODUCTOS_POR_NIVEL+1)})} posiciones encontradas.' if texto else 'Seleccione una posición o el encabezado de un nivel.'))
            self._mostrar_detalle()
            self._pintar_seleccion()
        except Exception as error:
            messagebox.showerror('Mapa', str(error), parent=self.root)

    def _crear_estante(self, clave, filas):
        import tkinter as tk
        from tkinter import ttk
        grupo = marco_visual(self.plano, background='white', highlightthickness=1,
                          highlightbackground=self.COLORES['borde'], padx=7, pady=7)
        self.tarjetas_estantes.append(grupo)
        cabecera = marco_visual(grupo, background='white')
        cabecera.pack(fill='x', pady=(0, 5))
        etiqueta_visual(cabecera, text=f'ESTANTE {numero_fisico(clave)}', font=('Segoe UI', 10, 'bold'),
                 background='white', foreground='#16324F').pack(side='left')
        ocupadas = sum(u['productos'] for u in filas)
        etiqueta_visual(cabecera, text=f'{ocupadas}/{len(filas)*PRODUCTOS_POR_NIVEL}', padx=6, pady=2,
                 background='#EEF3F8', foreground='#52677D', font=('Segoe UI', 8, 'bold')).pack(side='right')
        for u in sorted(filas, key=lambda fila: numero_fisico(fila['nivel']), reverse=True):
            cab = marco_visual(grupo, background='white', cursor='hand2')
            cab.pack(fill='x', pady=(1, 3))
            etiqueta = etiqueta_visual(cab, text=f'NIVEL {numero_fisico(u["nivel"])} · {u["productos"]}/{PRODUCTOS_POR_NIVEL}', background='white',
                                 foreground='#52677D', font=('Segoe UI', 9, 'bold'), cursor='hand2')
            etiqueta.pack(side='left')
            libres = max(0, PRODUCTOS_POR_NIVEL - u['productos'])
            badge = etiqueta_visual(cab, text=f'{libres} libre'+('s' if libres != 1 else ''),
                              background='#F1F4F8', foreground='#52677D', font=('Segoe UI', 8), padx=4)
            if libres:
                badge.pack(side='right')
            for w in (cab, etiqueta, badge):
                w.bind('<Button-1>', lambda e, uid=u['id_ubicacion']: self.mostrar_ubicacion(uid))
            posiciones = marco_visual(grupo, background='white')
            posiciones.pack(fill='x', pady=(0, 5))
            productos = {int(p['posicion']): p for p in self.contenido if p['id_ubicacion'] == u['id_ubicacion']}
            for pos in range(1, PRODUCTOS_POR_NIVEL + 1):
                p = productos.get(pos)
                led = numero_led(u['estante'], u['nivel'], pos)
                borde = marco_visual(posiciones, background='white', highlightthickness=2,
                                  highlightbackground=self.COLORES['borde'], takefocus=True, cursor='hand2')
                borde.grid(row=0, column=pos-1, sticky='nsew', padx=(0 if pos == 1 else 4, 4 if pos == 1 else 0))
                posiciones.columnconfigure(pos-1, weight=1, uniform='posiciones')
                interior = marco_visual(borde, padx=4, pady=6, highlightthickness=2)
                interior.pack(fill='both', expand=True)
                nombre = etiqueta_visual(interior, text=p['nombre'] if p else 'Espacio disponible', height=1,
                                  anchor='nw', justify='left', font=('Segoe UI', 9, 'bold'))
                nombre.pack(fill='x')
                fila_stock = marco_visual(interior)
                fila_stock.pack(fill='x', pady=(5, 4))
                fila_estado = marco_visual(interior)
                fila_estado.pack(fill='x')
                codigo = etiqueta_visual(fila_stock, text=p['codigo'] if p else u['codigo_ubicacion'],
                                  anchor='w', font=('Segoe UI', 8), foreground='#607287')
                codigo.pack(side='left')
                abreviaturas = {'Unidad': 'U', 'Litro': 'L', 'Kilogramo': 'kg', 'Metro': 'm',
                                'Paquete': 'paq.', 'Galón': 'gal.', 'Juego': 'jgo.',
                                'Tubo': 'tb.', 'Lata': 'lat.', 'Caja': 'cj.'}
                unidad = abreviaturas.get(p['unidad_medida'], p['unidad_medida']) if p else ''
                stock = etiqueta_visual(fila_stock, text=f"{format_numero(p['cantidad'])} {unidad}" if p else '—',
                                 font=('Segoe UI', 9, 'bold'), anchor='e')
                stock.pack(side='right', fill='x', expand=True, padx=(3, 0))
                estado = etiqueta_visual(fila_estado, text=p['estado_mapa'] if p else 'LIBRE',
                                  anchor='w', font=('Segoe UI', 8, 'bold'))
                estado.pack(side='left')
                pie = etiqueta_visual(fila_estado, text=f'P{pos}·LED{led:02}', anchor='e', font=('Segoe UI', 8))
                pie.pack(side='right', fill='x', expand=True, padx=(3, 0))
                borde.uid, borde.posicion, borde.producto = u['id_ubicacion'], pos, p
                borde.led_numero, borde.interior = led, interior
                borde.nombre, borde.pie = nombre, pie
                borde.etiquetas = [nombre, codigo, stock, estado, pie]
                borde.filas = [fila_stock, fila_estado]
                for label in (nombre, stock, pie):
                    label.configure(width=1)
                self.espacios.append(borde)
                for w in [borde, interior] + borde.etiquetas + borde.filas:
                    w.bind('<Button-1>', lambda e, uid=u['id_ubicacion'], posicion=pos: self.seleccionar_posicion(uid, posicion))
                    w.configure(cursor='hand2')
                for tecla in ('<Return>', '<space>'):
                    borde.bind(tecla, lambda e, uid=u['id_ubicacion'], posicion=pos: self.seleccionar_posicion(uid, posicion))
                self._tooltip_nombre(nombre, p['nombre'] if p else 'Posición disponible para asignar un producto.')
                nombre.bind('<Configure>', lambda e, w=nombre, texto=p['nombre'] if p else 'Espacio disponible': self._ajustar_nombre(w, texto, e.width))

    def _ajustar_nombre(self, widget, texto, ancho):
        from tkinter.font import Font
        fuente = Font(font=widget.cget('font'))
        ancho = max(40, ancho-2)
        mostrado = texto
        if fuente.measure(texto) > ancho:
            while mostrado and fuente.measure(mostrado+'…') > ancho:
                mostrado = mostrado[:-1]
            mostrado = mostrado.rstrip()+'…'
        widget.configure(text=mostrado)

    def organizar_estantes(self, ancho):
        # Tres columnas en las resoluciones solicitadas; no comprimir en ventanas menores.
        columnas = 3 if ancho >= 720 else 2 if ancho >= 480 else 1
        for c in range(3):
            self.plano.columnconfigure(c, weight=1 if c < columnas else 0,
                                       uniform='estantes' if c < columnas else '', minsize=0)
        # Retirar filas vacías que dejó la distribución inicial de una columna.
        for fila in range(len(getattr(self, 'tarjetas_estantes', []))):
            self.plano.rowconfigure(fila, weight=0, uniform='', minsize=0)
        for i, tarjeta in enumerate(getattr(self, 'tarjetas_estantes', [])):
            tarjeta.grid(row=i//columnas, column=i%columnas, sticky='nsew',
                         padx=4, pady=(0, 8))
            self.plano.rowconfigure(i//columnas, weight=0, uniform='filas_estantes')

    def _pintar_seleccion(self, estado=None):
        from integrations.arduino.led_service import servicio_led, LED_ENCENDIDO, LED_ERROR
        estado = estado or servicio_led.estado_conexion()
        for tarjeta in getattr(self, 'espacios', []):
            clave = (tarjeta.uid, tarjeta.posicion)
            seleccionada = self.posicion_led == clave
            encontrada = clave in self.resultados_posiciones or (
                not self.resultados_posiciones and tarjeta.uid in self.resaltados)
            fondo = self.COLORES[tarjeta.producto['estado_mapa'] if tarjeta.producto else 'libre']
            borde = self.COLORES['borde']
            if encontrada:
                fondo, borde = self.COLORES['busqueda'], '#69B5AB'
            if self.roles_ubicacion.get(tarjeta.uid):
                fondo = '#E7EFFB' if 'ORIGEN' in self.roles_ubicacion[tarjeta.uid] else self.COLORES['busqueda']
            if seleccionada:
                fondo, borde = self.COLORES['seleccion'], self.COLORES['azul']
            elif self.seleccion == tarjeta.uid and self.posicion_led is None:
                borde = self.COLORES['azul']
            activo = estado['leds'].get(tarjeta.led_numero) == LED_ENCENDIDO
            error = estado['leds'].get(tarjeta.led_numero) == LED_ERROR
            tarjeta.configure(highlightbackground=self.COLORES['led'] if activo else borde,
                               highlightcolor=self.COLORES['azul'], background=fondo)
            tarjeta.interior.configure(background=fondo, highlightbackground=borde,
                                        highlightcolor=borde)
            if not seleccionada and not (self.seleccion == tarjeta.uid and self.posicion_led is None):
                tarjeta.interior.configure(highlightbackground=fondo)
            for label in tarjeta.etiquetas:
                label.configure(background=fondo)
            for fila in tarjeta.filas:
                fila.configure(background=fondo)
            tarjeta.pie.configure(text=f'P{tarjeta.posicion}·LED{tarjeta.led_numero:02}'+('●' if activo else '!' if error else ''),
                                   foreground='#8D5D0A' if activo else '#52677D')
        self._actualizar_control_led(estado)

    def _mostrar_detalle(self):
        from tkinter import ttk
        for w in self.detalle_contenido.winfo_children():
            w.destroy()
        self.producto_seleccionado = None
        u = next((u for u in self.datos if u['id_ubicacion'] == self.seleccion), None)
        if getattr(self, '_lateral', False):
            self.plano.update_idletasks()
            estante = next((t.master.master for t in self.espacios if t.uid == self.seleccion), None)
            self.panel_detalle.grid_configure(pady=(estante.winfo_y() if estante else 0, 0))
        self.boton_producto.configure(state='disabled')
        if u is None:
            ttk.Label(self.detalle_contenido, text='Seleccione una posición del mapa para ver sus detalles.',
                      wraplength=208, justify='left', foreground='#607287').pack(anchor='w', pady=6)
            self.root.after_idle(self._alinear_detalle)
            return
        productos = [p for p in self.contenido if p['id_ubicacion'] == self.seleccion]
        p = next((p for p in productos if self.posicion_led and int(p['posicion']) == self.posicion_led[1]), None)
        def dato(titulo, valor, grande=False):
            ttk.Label(self.detalle_contenido, text=titulo, style='CardTitle.TLabel',
                      font=('Segoe UI', 8)).pack(anchor='w', pady=(6, 1))
            ttk.Label(self.detalle_contenido, text=valor, wraplength=208, justify='left',
                      font=('Segoe UI', 10 if grande else 9, 'bold' if grande else 'normal')).pack(anchor='w')
        if self.posicion_led:
            ttk.Label(self.detalle_contenido, text=p['nombre'] if p else 'Posición disponible',
                      font=('Segoe UI', 11, 'bold'), wraplength=208, justify='left').pack(anchor='w')
            if p:
                ttk.Label(self.detalle_contenido, text=p['codigo'], style='CardTitle.TLabel').pack(anchor='w', pady=(2, 0))
                self.producto_seleccionado = p['id_producto']
                self.boton_producto.configure(state='normal' if self.ver_producto else 'disabled')
            dato('Ubicación', f'E{numero_fisico(u["estante"])} · N{numero_fisico(u["nivel"])} · P{self.posicion_led[1]}')
            dato('Stock en esta posición', f'{format_numero(p["cantidad"])} {p["unidad_medida"]}' if p else 'Sin producto', True)
            dato('Estado del producto', p['estado_mapa'] if p else 'DISPONIBLE')
            led = numero_led(u['estante'], u['nivel'], self.posicion_led[1])
            dato('LED', f'LED {led:02}')
        else:
            ttk.Label(self.detalle_contenido, text=describir_ubicacion(u), font=('Segoe UI', 10, 'bold'),
                      wraplength=208).pack(anchor='w')
            for pos in range(1, PRODUCTOS_POR_NIVEL + 1):
                producto = next((p for p in productos if int(p['posicion']) == pos), None)
                bloque = ttk.Frame(self.detalle_contenido, padding=5, style='App.TFrame')
                bloque.pack(fill='x', pady=(6, 0))
                ttk.Label(bloque, text=f'POSICIÓN {pos}', style='Subtitulo.TLabel', font=('Segoe UI', 8, 'bold')).pack(anchor='w')
                ttk.Label(bloque, text=producto['nombre'] if producto else 'Disponible', wraplength=200,
                          style='Subtitulo.TLabel').pack(anchor='w')
                ttk.Button(bloque, text=f'{format_numero(producto["cantidad"])} {producto["unidad_medida"]}' if producto else 'Seleccionar',
                           command=lambda pos=pos: self.seleccionar_posicion(u['id_ubicacion'], pos),
                           style='Secondary.TButton', padding=(8, 4)).pack(anchor='w', pady=(3, 0))
        dato('Código de ubicación', u['codigo_ubicacion'])
        rol = self.roles_ubicacion.get(u['id_ubicacion'])
        if rol:
            dato('Movimiento', rol)
        self.root.after_idle(self._alinear_detalle)

    def _alinear_detalle(self):
        """Mantener el detalle completo dentro de una vista alta, sin mover tarjetas."""
        import tkinter as tk
        if not self.panel_detalle.winfo_exists() or not getattr(self, '_lateral', False):
            return
        self.panel_detalle.update_idletasks()
        estante = next((t.master.master for t in self.espacios if t.uid == self.seleccion), None)
        margen = estante.winfo_y() if estante else 0
        canvas = self.padre.master
        if isinstance(canvas, tk.Canvas):
            disponible = canvas.winfo_height() - (self.distribucion.winfo_rooty()-canvas.winfo_rooty())
            alto = self.panel_detalle.winfo_reqheight()
            if disponible >= alto:
                margen = min(margen, max(0, disponible-alto-8))
        self.panel_detalle.grid_configure(pady=(margen, 0))

    def mostrar_ubicacion(self, id_ubicacion):
        u = next((u for u in self.datos if u['id_ubicacion'] == id_ubicacion), None)
        if u is None:
            return False
        self.seleccion, self.posicion_led = id_ubicacion, None
        self._mostrar_detalle()
        self._pintar_seleccion()
        return True

    def seleccionar_posicion(self, id_ubicacion, posicion):
        if not self.mostrar_ubicacion(id_ubicacion):
            return False
        self.posicion_led = (id_ubicacion, int(posicion))
        self._mostrar_detalle()
        self._pintar_seleccion()
        self.root.after_idle(self._desplazar_seleccion)
        return True

    def _desplazar_seleccion(self):
        import tkinter as tk
        tarjeta = next((t for t in self.espacios if (t.uid, t.posicion) == self.posicion_led), None)
        if tarjeta is None or not tarjeta.winfo_exists():
            return
        # Utilizar el scroll de la página actual, sin ventanas ni otro mapa.
        canvas = getattr(self.padre, 'master', None)
        if isinstance(canvas, tk.Canvas):
            self.padre.update_idletasks()
            alto = max(1, self.padre.winfo_height())
            y = tarjeta.winfo_rooty() - self.padre.winfo_rooty()
            estante_y = tarjeta.master.master.winfo_rooty() - self.padre.winfo_rooty()
            inicio = canvas.canvasy(0)
            if estante_y < inicio or y + tarjeta.winfo_height() > inicio + canvas.winfo_height():
                canvas.yview_moveto(max(0, estante_y-16)/alto)

    def buscar(self):
        from jarvis.nlp_jarvis import normalizar_texto
        self.seleccion = self.posicion_led = None
        self.refrescar()
        candidatas = [t for t in self.espacios if (t.uid, t.posicion) in self.resultados_posiciones]
        texto = normalizar_texto(self.busqueda.get().strip())
        coincidencia = next((t for t in candidatas if t.producto and texto in
                            (normalizar_texto(t.producto['nombre']), normalizar_texto(t.producto['codigo']))),
                           candidatas[0] if candidatas else None)
        if coincidencia:
            self.seleccionar_posicion(coincidencia.uid, coincidencia.posicion)

    def abrir_producto(self):
        if self.ver_producto and self.producto_seleccionado is not None:
            self.ver_producto(self.producto_seleccionado)

    def _actualizar_control_led(self, estado):
        from integrations.arduino.led_service import LED_ENCENDIDO, LED_ERROR
        texto = 'SIMULACIÓN' if estado['modo'] == 'simulacion' else 'CONECTADO' if estado['estado'] == 'Conectado' else estado['estado'].upper()
        self.badge_arduino.configure(text=texto)
        self.boton_led.configure(state='disabled', text='Seleccione una posición')
        self.estado_led.configure(text='○ LED apagado')
        if self.posicion_led:
            uid, pos = self.posicion_led
            u = next((u for u in self.datos if u['id_ubicacion'] == uid), None)
            if u:
                led = numero_led(u['estante'], u['nivel'], pos)
                activo = estado['leds'].get(led) == LED_ENCENDIDO
                error = estado['leds'].get(led) == LED_ERROR
                self.boton_led.configure(state='normal', text=f'{"Apagar" if activo else "Encender"} LED {led:02}')
                self.estado_led.configure(text=f'● LED {led:02} encendido' if activo else f'LED {led:02} sin confirmar' if error else '○ LED apagado')

    def encender_seleccion(self):
        from integrations.arduino.led_service import servicio_led, LED_ENCENDIDO
        if not self.posicion_led:
            return
        uid, pos = self.posicion_led
        u = next(u for u in self.datos if u['id_ubicacion'] == uid)
        led = numero_led(u['estante'], u['nivel'], pos)
        activo = servicio_led.estado_conexion()['leds'].get(led) == LED_ENCENDIDO
        self.trabajo_led.ejecutar(lambda: servicio_led.apagar_led(led) if activo else servicio_led.encender_por_ubicacion(uid, pos),
                                 lambda r: self.mensaje_led.configure(text=r['mensaje']))

    def apagar_leds(self):
        from integrations.arduino.led_service import servicio_led
        self.trabajo_led.ejecutar(servicio_led.apagar_todos, lambda r: self.mensaje_led.configure(text=r['mensaje']))

    def actualizar_leds(self):
        from integrations.arduino.led_service import servicio_led
        if not self.padre.winfo_exists():
            return
        estado = servicio_led.estado_conexion()
        if getattr(self, '_revision_led', None) != estado['revision']:
            self._revision_led = estado['revision']
            self._pintar_seleccion(estado)
        self.root.after(200, self.actualizar_leds)

    def mostrar_producto_en_mapa(self, producto_id):
        filas = ubicaciones_producto(producto_id)
        self.roles_ubicacion.clear()
        self.almacen.set('Todos')
        self.zona.set('Todas')
        self.busqueda.delete(0, 'end')
        self.resaltados = {u['id_ubicacion'] for u in filas}
        self.seleccion = self.posicion_led = None
        self.refrescar()
        self.resultados_posiciones = {(u['id_ubicacion'], int(u['posicion'])) for u in filas}
        self.resumen.configure(text=f'{len(filas)} ubicaciones · Stock localizado: {format_numero(sum(u["cantidad"] for u in filas))}' if filas else 'Sin existencias localizadas.')
        if filas:
            self.seleccionar_posicion(filas[0]['id_ubicacion'], filas[0]['posicion'])
        self._pintar_seleccion()
        return bool(filas)

    def mostrar_movimiento(self, origen=None, destino=None):
        self.almacen.set('Todos')
        self.zona.set('Todas')
        self.busqueda.delete(0, 'end')
        self.roles_ubicacion = {}
        if origen is not None:
            self.roles_ubicacion[origen] = 'ORIGEN'
        if destino is not None:
            self.roles_ubicacion[destino] = 'ORIGEN Y DESTINO' if destino == origen else 'DESTINO'
        self.resaltados = set(self.roles_ubicacion)
        self.seleccion = self.posicion_led = None
        self.refrescar()
        self.resumen.configure(text='Origen: azul · Destino: turquesa. Seleccione un nivel para consultar su contenido.')

