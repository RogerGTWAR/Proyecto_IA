from ui.ui_components import insertar_fila
from core.formato_numerico import format_numero, format_moneda
"""Pantallas de inventario; reutilizan el sistema visual y servicios actuales."""
from ui.ui_theme import SPACING_XS, SPACING_SM, SPACING_MD, SPACING_CARD, SPACING_LG, SPACING_XL
from decimal import Decimal
from pathlib import Path
import tkinter as tk
from tkinter import ttk,messagebox,filedialog
from ui.ui_theme import crear_panel,crear_kpi,crear_pagina,COLORES,FONTS
from inventory.inventario_service import (buscar_inventario,listar_unidades,guardar_unidad,guardar_producto,
    obtener_ficha,activar_producto,listar_motivos,guardar_motivo,consultar,estadisticas_inventario,
    sugerir_lotes,decimal_inventario)
from inventory.productos import (listar_categorias,listar_ubicaciones,crear_categoria,actualizar_categoria,
    eliminar_categoria,registrar_ubicacion,actualizar_ubicacion,eliminar_ubicacion)
from inventory.movimientos import (listar_empleados_activos,registrar_entrada,registrar_salida,
    registrar_transferencia,registrar_ajuste,buscar_movimientos)
from inventory.conteo_inventario import listar_conteo_ubicacion,guardar_conteo,aplicar_conteo,listar_conteos,cargar_conteo,resumir_conteo
from ui.ui_components import organizar_acciones
from inventory.organizacion_fisica import describir_posicion

def boton(padre,texto,fn,estilo='Secondary'):
    return ttk.Button(padre,text=texto,command=fn,style=estilo+'.TButton')

def modal(root,titulo,ancho=760,alto=650):
    w=tk.Toplevel(root); w.title(titulo); w.transient(root)
    alto=min(alto,root.winfo_screenheight()-90)
    x=max(0,root.winfo_rootx()+(root.winfo_width()-ancho)//2)
    y=max(0,root.winfo_rooty()+(root.winfo_height()-alto)//2)
    w.geometry(f'{ancho}x{alto}+{x}+{y}'); w.minsize(500,400)
    ttk.Label(w,text=titulo.upper(),style='HeaderTitle.TLabel',padding=SPACING_CARD).pack(fill='x')
    cuerpo=crear_pagina(w); cuerpo.pagina.pack(fill='both',expand=True)
    pie=ttk.Frame(w,padding=SPACING_MD); pie.pack(fill='x')
    return w,cuerpo,pie

def campo(padre,texto,fila,valor='',opciones=None,vertical=True):
    contenedor=ttk.Frame(padre) if vertical else padre
    if vertical:
        contenedor.grid(row=fila,column=0,columnspan=2,sticky='ew',pady=(0,SPACING_MD))
        ttk.Label(contenedor,text=texto).pack(anchor='w',pady=(0,SPACING_XS))
    else:ttk.Label(padre,text=texto).grid(row=fila,column=0,sticky='w',pady=SPACING_SM,padx=(0,SPACING_MD))
    if opciones is None:
        c=ttk.Entry(contenedor); c.insert(0,'' if valor is None else str(valor))
    else:
        c=ttk.Combobox(contenedor,values=opciones,state='readonly'); c.set(str(valor or ''))
    if vertical:c.pack(fill='x')
    else:c.grid(row=fila,column=1,sticky='ew',pady=SPACING_SM)
    padre.columnconfigure(1,weight=1)
    return c

def seguro(root,fn):
    def ejecutar():
        try: return fn()
        except Exception as e: messagebox.showerror('Inventario',str(e),parent=root)
    return ejecutar

class InventarioUI:
    def __init__(self,padre,root,tabla,al_cambiar):
        self.padre=padre; self.root=root; self.tabla_factory=tabla; self.al_cambiar=al_cambiar
        from ui.ui_components import ModuleHeader
        ModuleHeader(padre,'Inventario de productos','Stock por ubicación, lotes opcionales y cantidades decimales')
        fila=ttk.Frame(padre,style='App.TFrame'); fila.pack(fill='x',pady=(0,SPACING_MD))
        self.kpis={k:tk.StringVar(value='—') for k in ('productos','stock','bajo','agotados','valor')}
        for i,(titulo,k) in enumerate([('Productos','productos'),('Stock total','stock'),('Stock bajo','bajo'),('Agotados','agotados'),('Valor a precio registrado','valor')]):
            crear_kpi(fila,titulo,self.kpis[k]).grid(row=0,column=i,sticky='nsew',padx=SPACING_XS); fila.columnconfigure(i,weight=1,uniform='kpi')
        filtros=crear_panel(padre,SPACING_MD); filtros.pack(fill='x',pady=(0,SPACING_MD))
        self.busqueda=campo(filtros,'Código, nombre, descripción, categoría o ubicación',0,vertical=False)
        self.estado=campo(filtros,'Estado',1,'Todos',['Todos','Con stock','Stock bajo','Agotados','Inactivos'],vertical=False)
        self.categoria=campo(filtros,'Categoría',2,'Todas',['Todas'],vertical=False)
        self.almacen=campo(filtros,'Almacén',3,'Todos',['Todos'],vertical=False)
        self.zona=campo(filtros,'Zona',4,'Todas',['Todas'],vertical=False)
        self.ubicacion=campo(filtros,'Ubicación',5,'Todas',['Todas'],vertical=False)
        # Búsqueda completa y cinco filtros en una fila, dejando espacio a la tabla.
        etiquetas=[w for w in filtros.winfo_children() if isinstance(w,ttk.Label)]
        etiquetas[0].grid_configure(row=0,column=0,columnspan=5,pady=(0,SPACING_XS))
        self.busqueda.grid_configure(row=1,column=0,columnspan=4,pady=(SPACING_XS,SPACING_SM))
        boton(filtros,'Limpiar filtros',seguro(root,self.limpiar)).grid(row=1,column=4,sticky='ew',padx=(SPACING_SM,0),pady=(SPACING_XS,SPACING_SM))
        for etiqueta in etiquetas:etiqueta.configure(style='CardTitle.TLabel')
        for i,control in enumerate((self.estado,self.categoria,self.almacen,self.zona,self.ubicacion)):
            etiquetas[i+1].grid_configure(row=2,column=i,columnspan=1,pady=(0,SPACING_XS))
            control.configure(width=12)
            control.grid_configure(row=3,column=i,columnspan=1,padx=(0,SPACING_MD))
        for columna in range(5): filtros.columnconfigure(columna,weight=1,uniform='filtros')
        acciones=ttk.Frame(padre); acciones.pack(fill='x',pady=(0,SPACING_MD))
        self.botones_seleccion=[]
        for texto,fn in [('+ Nuevo producto',self.nuevo_producto),('Editar',self.editar),('Ver ubicación',self.ver_ubicacion)]:
            b=boton(acciones,texto,seguro(root,fn),'Primary' if texto=='+ Nuevo producto' else 'Secondary')
            b.pack(side='left',padx=SPACING_XS)
            if texto!='+ Nuevo producto':self.botones_seleccion.append(b)
        mas=ttk.Menubutton(acciones,text='Más acciones ▼',style='Secondary.TMenubutton')
        self.menu_mas=tk.Menu(mas,tearoff=False)
        for texto,fn in [('Ficha del producto',self.ficha),('Desactivar / reactivar',self.activar),('Análisis de rotación',self.rotacion)]:
            self.menu_mas.add_command(label=texto,command=seguro(root,fn))
        mas.configure(menu=self.menu_mas);mas.pack(side='left',padx=SPACING_XS)
        campos=('codigo','nombre','categoria','unidad','stock_actual','stock_minimo','estado_inventario','precio','valor_stock')
        self.tabla=tabla(padre,campos,('Código','Producto','Categoría','Unidad','Stock','Mínimo','Estado','Precio','Valor'),(115,230,150,100,100,100,110,110,120))
        from ui.ui_theme import tono_estado
        for estado in ('NORMAL','BAJO','CRÍTICO','AGOTADO','INACTIVO'):
            tono=tono_estado(estado);self.tabla.tag_configure(estado,background=COLORES[tono+'_bg'],foreground=COLORES[tono+'_text'])
        self.tabla.bind('<Double-1>',self.abrir_ficha_doble)
        self.tabla.bind('<<TreeviewSelect>>',self.actualizar_acciones)
        self.menu_contextual=tk.Menu(self.tabla,tearoff=False)
        for texto,fn in [('Editar',self.editar),('Ver ficha',self.ficha),('Ver ubicación',self.ver_ubicacion),('Desactivar / reactivar',self.activar)]:
            self.menu_contextual.add_command(label=texto,command=seguro(root,fn))
        self.tabla.bind('<Button-3>',self.abrir_menu_contextual)
        catalogos=ttk.Frame(padre);catalogos.pack(fill='x',pady=(SPACING_SM,0))
        catalogo=ttk.Menubutton(catalogos,text='Catálogos ▼',style='Secondary.TMenubutton')
        self.menu_catalogos=tk.Menu(catalogo,tearoff=False)
        for tipo in ('Categorías','Unidades','Ubicaciones','Motivos'):
            self.menu_catalogos.add_command(label=tipo,command=seguro(root,lambda t=tipo:self.catalogo(t)))
        catalogo.configure(menu=self.menu_catalogos);catalogo.pack(side='right')
        self.datos={}; self.categorias={}; self.ubicaciones={}; self.pendiente=None
        self.actualizar_acciones()
        self.busqueda.bind('<KeyRelease>',self.programar)
        self.busqueda.bind('<Return>',self.buscar_ahora)
        self.busqueda.bind('<KP_Enter>',self.buscar_ahora)
        for c in (self.estado,self.categoria,self.almacen,self.zona,self.ubicacion): c.bind('<<ComboboxSelected>>',lambda _:seguro(root,self.refrescar)())

    def programar(self,_=None):
        if getattr(_,'keysym',None) in ('Return','KP_Enter'):return
        if self.pendiente: self.root.after_cancel(self.pendiente)
        self.pendiente=self.root.after(300,seguro(self.root,self.refrescar))

    def buscar_ahora(self,_=None):
        seguro(self.root,self.refrescar)()
        return 'break'

    def actualizar_acciones(self,_=None):
        seleccion=self.tabla.selection()
        habilitar=bool(seleccion and int(seleccion[0]) in self.datos)
        estado='normal' if habilitar else 'disabled'
        for b in self.botones_seleccion:b.configure(state=estado)
        for i in (0,1):self.menu_mas.entryconfigure(i,state=estado)
        for i in range(4):self.menu_contextual.entryconfigure(i,state=estado)

    def abrir_menu_contextual(self,event):
        fila=self.tabla.identify_row(event.y)
        if not fila:return
        self.tabla.selection_set(fila);self.actualizar_acciones()
        try:self.menu_contextual.tk_popup(event.x_root,event.y_root)
        finally:self.menu_contextual.grab_release()

    def abrir_ficha_doble(self,event):
        fila=self.tabla.identify_row(event.y)
        if fila:
            self.tabla.selection_set(fila);seguro(self.root,self.ficha)()

    def refrescar(self,registros=None):
        if self.pendiente:self.root.after_cancel(self.pendiente)
        self.pendiente=None
        cats=listar_categorias(); us=listar_ubicaciones()
        self.categorias={c['nombre']:c['id_categoria'] for c in cats}
        self.ubicaciones={u['codigo_ubicacion']:u['id_ubicacion'] for u in us}
        self.categoria.configure(values=['Todas']+list(self.categorias))
        self.ubicacion.configure(values=['Todas']+list(self.ubicaciones))
        self.almacen.configure(values=['Todos']+sorted({u['almacen'] for u in us if u.get('almacen')}))
        self.zona.configure(values=['Todas']+sorted({u['zona'] for u in us if u.get('zona')}))
        datos=registros if registros is not None else buscar_inventario(self.busqueda.get(),self.estado.get(),self.categorias.get(self.categoria.get()),self.ubicaciones.get(self.ubicacion.get()),None if self.almacen.get()=='Todos' else self.almacen.get(),None if self.zona.get()=='Todas' else self.zona.get())
        self.datos={p['id_producto']:p for p in datos}; self.tabla.delete(*self.tabla.get_children())
        for p in datos: insertar_fila(self.tabla, '', 'end',iid=str(p['id_producto']),tags=(p['estado_inventario'],),values=tuple(p[c] for c in self.tabla['columns']))
        self.actualizar_acciones()
        self.kpis['productos'].set(str(len(datos)))
        self.kpis['stock'].set(format_numero(sum((p['stock_actual'] for p in datos),Decimal(0))))
        self.kpis['bajo'].set(str(sum(p['estado_inventario'] in ('BAJO','CRÍTICO') for p in datos)))
        self.kpis['agotados'].set(str(sum(p['estado_inventario']=='AGOTADO' for p in datos)))
        self.kpis['valor'].set(f"C$ {sum((p['valor_stock'] for p in datos),Decimal(0)):,.2f}")

    def limpiar(self):
        self.busqueda.delete(0,'end'); self.estado.set('Todos'); self.categoria.set('Todas'); self.almacen.set('Todos'); self.zona.set('Todas'); self.ubicacion.set('Todas'); self.refrescar()

    def ver_ubicacion(self):
        from inventory.mapa_almacen import ubicaciones_producto,describir_ubicacion
        p=self.seleccionado();filas=ubicaciones_producto(p['id_producto'])
        w,c,pie=modal(self.root,'Ubicación · '+p['nombre'],900,540)
        ttk.Label(c,text=p['nombre'],style='Seccion.TLabel').pack(anchor='w',pady=(0,SPACING_SM))
        t=self.tabla_factory(c,('ubicacion','codigo','cantidad','unidad'),
            ('Estante, nivel y posición','Código','Cantidad','Unidad'),(380,150,100,100));t.configure(height=6)
        for u in filas:
            descripcion=describir_ubicacion(u)
            if u.get('posicion') is not None and 'Posición' not in descripcion:descripcion+=f", Posición {u['posicion']}"
            insertar_fila(t,'','end',values=(descripcion,u['codigo_ubicacion'],u['cantidad'],u['unidad_medida']))
        aviso='Sin ubicación física registrada.' if not filas else 'Actualmente agotado; conserva su posición asignada.' if all(float(u['cantidad'])==0 for u in filas) else f'{len(filas)} ubicación(es) asignada(s).'
        ttk.Label(c,text=aviso,wraplength=780).pack(anchor='w',pady=SPACING_MD)
        if filas:
            def abrir_mapa():self.root.mostrar_producto_en_mapa(p['id_producto']);w.destroy()
            boton(pie,'Ver en mapa',seguro(w,abrir_mapa),'Primary').pack(side='left')
        boton(pie,'Cerrar',w.destroy).pack(side='right')

    def seleccionado(self):
        s=self.tabla.selection()
        if not s: raise ValueError('Seleccione un producto.')
        return self.datos[int(s[0])]

    def editar(self): self.nuevo_producto(self.seleccionado())

    def activar(self):
        p=self.seleccionado(); activo=not bool(p['estado'])
        if messagebox.askyesno('Producto',('Reactivar' if activo else 'Desactivar')+' '+p['nombre']+'?',parent=self.root): activar_producto(p['id_producto'],activo); self.al_cambiar()

    def nuevo_producto(self,producto=None):
        cats=listar_categorias(); units=listar_unidades()
        if not cats or not units: raise ValueError('Primero cree categorías y unidades activas.')
        w,c,pie=modal(self.root,'Editar producto' if producto else 'Nuevo producto',700,700)
        p=producto or {}; nombres={a['nombre']:a['id_categoria'] for a in cats}; unidades={a['nombre']:a['id_unidad'] for a in units}
        from core.config_manager import obtener
        p=dict(p); p.setdefault('stock_minimo',obtener('inventario','stock_minimo'))
        campos={}
        for i,(k,texto,v,opts) in enumerate([('codigo','Código (vacío: generar)',p.get('codigo',''),None),('nombre','Nombre',p.get('nombre',''),None),('descripcion','Descripción',p.get('descripcion',''),None),('categoria','Categoría',p.get('categoria',cats[0]['nombre']),list(nombres)),('unidad','Unidad',p.get('unidad',p.get('unidad_medida',units[0]['nombre'])),list(unidades)),('precio','Precio registrado',p.get('precio',0),None),('minimo','Stock mínimo',p.get('stock_minimo',0),None),('barras','Código de barras (opcional)',p.get('codigo_barras',''),None),('qr','Código QR (opcional)',p.get('codigo_qr',''),None),('imagen','Ruta de imagen (opcional)',p.get('imagen_producto',''),None)]): campos[k]=campo(c,texto,i,v,opts)
        lotes=tk.BooleanVar(value=bool(p.get('control_lotes',False))); ttk.Checkbutton(c,text='Control de lotes',variable=lotes).grid(row=10,column=1,sticky='w',pady=SPACING_SM)
        def elegir_imagen():
            ruta=filedialog.askopenfilename(parent=w,filetypes=[('Imágenes','*.png *.jpg *.jpeg *.webp')])
            if ruta: campos['imagen'].delete(0,'end'); campos['imagen'].insert(0,ruta)
        boton(c,'Seleccionar imagen',elegir_imagen).grid(row=11,column=1,sticky='w')
        ttk.Label(c,text='El stock inicial se registra con una entrada después de crear el producto.',wraplength=520).grid(row=12,column=0,columnspan=2,pady=SPACING_MD)
        def guardar():
            guardar_producto(campos['codigo'].get(),campos['nombre'].get(),campos['descripcion'].get(),nombres[campos['categoria'].get()],unidades[campos['unidad'].get()],campos['precio'].get(),campos['minimo'].get(),id_producto=p.get('id_producto'),control_lotes=lotes.get(),codigo_barras=campos['barras'].get(),codigo_qr=campos['qr'].get(),imagen_producto=campos['imagen'].get())
            w.destroy(); self.al_cambiar()
        boton(pie,'Cancelar',w.destroy).pack(side='left'); boton(pie,'Guardar',seguro(w,guardar),'Success').pack(side='right')

    def ficha(self, producto_id=None):
        p=obtener_ficha(producto_id if producto_id is not None else self.seleccionado()['id_producto']); w,c,pie=modal(self.root,'Ficha · '+p['codigo'],950,740)
        for i,(texto,valor) in enumerate([('Código',p['codigo']),('Nombre',p['nombre']),('Descripción',p['descripcion'] or 'Sin descripción'),('Categoría',p['categoria']),('Unidad',p['unidad']),('Stock total',p['stock_actual']),('Stock mínimo',p['stock_minimo']),('Estado',p['estado_inventario']),('Precio registrado',p['precio']),('Valor a precio registrado',p['valor_stock']),('Último movimiento',str(p['ultimo_movimiento'][0]) if p['ultimo_movimiento'] else 'Sin movimientos')]):
            ttk.Label(c,text=f'{texto}: {valor}',wraplength=800).pack(anchor='w',pady=SPACING_XS)
        r=p['prediccion']; texto=r.get('mensaje','Datos insuficientes')
        if r['datos_suficientes']:
            dias=r['dias_restantes_promedio']; texto=f"Consumo: {r['consumo_promedio_diario']:.2f}/día · Días restantes: {dias:.1f}" if dias is not None else 'Consumo no calculable'
            texto+=f"\nReabastecimiento sugerido: {r['cantidad_recomendada']} · Objetivo de {r['dias_objetivo']} días de consumo."
        ttk.Label(c,text=texto,wraplength=800).pack(anchor='w',pady=SPACING_MD)
        if p['imagen_producto']:
            try:
                from PIL import Image,ImageTk
                im=Image.open(Path(p['imagen_producto'])); im.thumbnail((180,130)); foto=ImageTk.PhotoImage(im)
                label=ttk.Label(c,image=foto); label.image=foto; label.pack(anchor='w')
            except (OSError,ValueError): ttk.Label(c,text='Imagen no disponible.').pack(anchor='w')
        ttk.Label(c,text='Ubicaciones',style='Seccion.TLabel').pack(anchor='w',pady=(SPACING_MD,SPACING_XS))
        t=self.tabla_factory(c,('ubicacion','posicion','cantidad'),('Estante / nivel','Posición','Cantidad'),(250,85,150))
        t.configure(height=4)
        for u in p['ubicaciones']: insertar_fila(t, '','end',values=(describir_posicion(u),u['posicion'],u['cantidad']))
        ttk.Label(c,text='Lotes y vencimientos',style='Seccion.TLabel').pack(anchor='w',pady=SPACING_SM)
        t=self.tabla_factory(c,('codigo_lote','cantidad','fecha_vencimiento','estado_vencimiento','dias_vencimiento'),('Lote','Cantidad','Vencimiento','Estado','Días'),(140,110,150,180,90)); t.configure(height=4)
        for l in p['lotes']: insertar_fila(t, '','end',values=tuple(l[k] if l[k] is not None else 'No aplica' for k in t['columns']))
        ttk.Label(c,text='Alertas: '+('\n'.join(a['mensaje'] for a in p['alertas']) or 'Sin alertas activas'),wraplength=800).pack(anchor='w',pady=SPACING_MD)
        boton(pie,'Cerrar',w.destroy).pack(side='right')

    def catalogo(self,tipo):
        w,c,pie=modal(self.root,tipo,850,650)
        claves={'Categorías':('nombre','descripcion'),'Unidades':('nombre','abreviatura','activo'),'Ubicaciones':('codigo_ubicacion','seccion','almacen','zona'),'Motivos':('nombre','tipo')}
        cols=claves[tipo]; t=self.tabla_factory(c,cols,cols,[170]*len(cols)); t.configure(height=8); datos={}
        def cargar():
            filas={'Categorías':listar_categorias,'Unidades':lambda:listar_unidades(True),'Ubicaciones':listar_ubicaciones,'Motivos':listar_motivos}[tipo]()
            t.delete(*t.get_children()); datos.clear()
            for i,f in enumerate(filas): datos[str(i)]=f; insertar_fila(t, '','end',iid=str(i),values=tuple(f.get(k) or '' for k in cols))
        def editor(actual=None):
            e,ec,ep=modal(w,'Editar '+tipo if actual else 'Nuevo · '+tipo,650,650); a=actual or {}; entradas={}
            campos={'Categorías':('nombre','descripcion'),'Unidades':('nombre','abreviatura'),'Ubicaciones':('codigo_ubicacion','seccion','pasillo','estante','nivel','descripcion','almacen','zona'),'Motivos':('nombre','tipo')}[tipo]
            tipos=[r['nombre'] for r in consultar('SELECT nombre FROM tipos_movimiento WHERE estado=1 AND fecha_eliminacion IS NULL')]
            for i,k in enumerate(campos): entradas[k]=campo(ec,k.replace('_',' ').capitalize(),i,a.get(k,''),tipos if k=='tipo' else None)
            active=tk.BooleanVar(value=bool(a.get('activo',True)))
            if tipo=='Unidades': ttk.Checkbutton(ec,text='Activa',variable=active).grid(row=len(campos),column=1)
            def guardar():
                v={k:x.get() for k,x in entradas.items()}
                if tipo=='Categorías':
                    if a: actualizar_categoria(a['id_categoria'],v['nombre'],v['descripcion'])
                    else: crear_categoria(v['nombre'],v['descripcion'])
                elif tipo=='Unidades': guardar_unidad(v['nombre'],v['abreviatura'],a.get('id_unidad'),active.get())
                elif tipo=='Motivos': guardar_motivo(v['nombre'],v['tipo'])
                else:
                    args=(v['codigo_ubicacion'],v['seccion'],v['pasillo'],v['estante'],v['nivel'],v['descripcion'])
                    if a: actualizar_ubicacion(a['id_ubicacion'],*args); identificador=a['id_ubicacion']
                    else:
                        registrar_ubicacion(*args); identificador=consultar('SELECT id_ubicacion FROM ubicaciones WHERE codigo_ubicacion=? AND fecha_eliminacion IS NULL',v['codigo_ubicacion'])[0]['id_ubicacion']
                    from core.database import conectar
                    cn=conectar()
                    try: cn.cursor().execute('UPDATE ubicaciones SET almacen=?,zona=? WHERE id_ubicacion=?',v['almacen'] or None,v['zona'] or None,identificador); cn.commit()
                    except Exception: cn.rollback(); raise
                    finally: cn.close()
                e.destroy(); cargar(); self.refrescar()
            boton(ep,'Cancelar',e.destroy).pack(side='left'); boton(ep,'Guardar',seguro(e,guardar),'Success').pack(side='right')
        def editar():
            if not t.selection(): raise ValueError('Seleccione un registro.')
            editor(datos[t.selection()[0]])
        boton(pie,'Agregar',lambda:editor(),'Success').pack(side='left')
        if tipo!='Motivos': boton(pie,'Editar',seguro(w,editar),'Primary').pack(side='left',padx=SPACING_SM)
        boton(pie,'Cerrar',w.destroy).pack(side='right'); cargar()

    def rotacion(self):
        w,c,pie=modal(self.root,'Consumo y baja rotación',900,680)
        periodo=campo(c,'Periodo (días)',0,'30',['7','30','60','90'])
        marco=ttk.Frame(c); marco.grid(row=1,column=0,columnspan=2,sticky='nsew')
        nota=ttk.Label(marco,text='',wraplength=780); nota.pack(anchor='w',pady=SPACING_MD)
        t=self.tabla_factory(marco,('codigo','nombre','cantidad'),('Código','Producto','Salidas'),(140,350,150)); t.configure(height=7)
        baja=ttk.Label(marco,text='',wraplength=780); baja.pack(anchor='w',pady=SPACING_MD)
        def cargar():
            r=estadisticas_inventario(int(periodo.get())); t.delete(*t.get_children())
            for p in r['mas_consumidos']: insertar_fila(t, '','end',values=(p['codigo'],p['nombre'],p['cantidad']))
            nota.configure(text=r['rotacion']+('\nSin datos suficientes de salidas en este periodo.' if not r['mas_consumidos'] else ''))
            baja.configure(text='Baja rotación: '+(', '.join(p['nombre'] for p in r['baja_rotacion']) or 'Sin productos en este periodo.'))
        periodo.bind('<<ComboboxSelected>>',lambda _:seguro(w,cargar)()); cargar(); boton(pie,'Cerrar',w.destroy).pack(side='right')

def abrir_movimiento(root,tipo,al_cambiar):
    w,c,pie=modal(root,tipo+' de inventario',850,740)
    empleados=listar_empleados_activos(); productos=buscar_inventario(); ubicaciones=listar_ubicaciones()
    es={f"{e['codigo_empleado']} · {e['nombres']} {e['apellidos']}":e['id_empleado'] for e in empleados}
    ps={p['codigo']+' · '+p['nombre']:p for p in productos}; us={describir_posicion(u):u['id_ubicacion'] for u in ubicaciones}
    emp=campo(c,'Empleado responsable',0,opciones=list(es)); producto=campo(c,'Producto',1,opciones=list(ps))
    origen=campo(c,'Ubicación origen',2,opciones=list(us)); destino=campo(c,'Ubicación destino',3,opciones=list(us))
    if tipo=='Entrada': origen.configure(state='disabled')
    if tipo in ('Salida','Ajuste'): destino.configure(state='disabled')
    cantidad=campo(c,'Cantidad física' if tipo=='Ajuste' else 'Cantidad',4)
    motivos=listar_motivos(tipo) if tipo!='Ajuste' else []
    ms={m['nombre']:m['id_motivo'] for m in motivos}
    motivo=campo(c,'Motivo',5,opciones=list(ms)); referencia=campo(c,'Referencia (opcional)',6)
    costo=campo(c,'Costo unitario (entrada, opcional)',7)
    if tipo!='Entrada': costo.configure(state='disabled')
    lote=campo(c,'Lote seleccionado',8,opciones=[]); codigo=campo(c,'Código de lote (entrada)',9)
    vencimiento=campo(c,'Vencimiento YYYY-MM-DD (opcional)',10)
    observacion=campo(c,'Observación',11)
    nota=ttk.Label(c,text='',wraplength=700); nota.grid(row=12,column=0,columnspan=2,sticky='w',pady=SPACING_MD)
    def vista_ubicaciones():
        from inventory.mapa_almacen import MapaAlmacenUI
        ventana,cuerpo,pie=modal(root,'Origen y destino en el mapa',950,650)
        def tabla(padre,columnas,titulos,anchos):
            t=ttk.Treeview(padre,columns=columnas,show='headings',height=5)
            for k,titulo,ancho in zip(columnas,titulos,anchos): t.heading(k,text=titulo); t.column(k,width=ancho)
            t.pack(fill='both',expand=True); return t
        m=MapaAlmacenUI(cuerpo,ventana,tabla)
        m.mostrar_movimiento(us.get(origen.get()),us.get(destino.get()))
        ttk.Label(pie,text=f'Origen: {origen.get() or "No seleccionado"} → Destino: {destino.get() or "No seleccionado"}').pack(anchor='w')
    boton(c,'Ver origen / destino en mapa',seguro(w,vista_ubicaciones)).grid(row=13,column=0,columnspan=2,pady=SPACING_SM)
    lm={}
    def actualizar(_=None):
        lm.clear(); lote.set('')
        p=ps.get(producto.get())
        if not p: return
        control=bool(p['control_lotes'])
        codigo.configure(state='normal' if control and tipo=='Entrada' else 'disabled')
        vencimiento.configure(state='normal' if control and tipo=='Entrada' else 'disabled')
        lote.configure(state='readonly' if control and tipo!='Entrada' else 'disabled')
        if control and origen.get():
            filas=sugerir_lotes(p['id_producto'],us[origen.get()])
            lm.update({f"{l['codigo_lote']} · {format_numero(l['cantidad'])} · {l['fecha_vencimiento'] or 'sin vencimiento'} · {l['estado_vencimiento']}":l for l in filas})
            lote.configure(values=list(lm))
            nota.configure(text='Sugerencia FEFO/FIFO: '+(next(iter(lm)) if lm else 'sin stock de lotes')+'\nSeleccione el lote explícitamente; no se aplicará automáticamente.')
        else: nota.configure(text=f"Stock total: {format_numero(p['stock_actual'])} · Unidad: {p['unidad']}")
        ubicacion_elegida=us.get(destino.get() if tipo in ('Entrada','Transferencia') else origen.get())
        if ubicacion_elegida:
            ocupacion=consultar('''SELECT u.capacidad_productos,COUNT(DISTINCT e.id_producto) ocupados
                FROM ubicaciones u LEFT JOIN existencias e ON e.id_ubicacion=u.id_ubicacion AND e.fecha_eliminacion IS NULL
                WHERE u.id_ubicacion=? GROUP BY u.capacidad_productos''',ubicacion_elegida)[0]
            nota.configure(text=nota.cget('text')+f"\n{ocupacion['ocupados']}/{ocupacion['capacidad_productos']} espacios ocupados"+(' · COMPLETO; admite cantidades de productos ya asignados.' if ocupacion['ocupados']>=ocupacion['capacidad_productos'] else ''))
    producto.bind('<<ComboboxSelected>>',actualizar); origen.bind('<<ComboboxSelected>>',actualizar)
    destino.bind('<<ComboboxSelected>>',actualizar)
    def guardar():
        if emp.get() not in es or producto.get() not in ps: raise ValueError('Seleccione empleado y producto.')
        p=ps[producto.get()]; opts={}; texto=observacion.get()
        if p['control_lotes']:
            if tipo=='Entrada': opts.update(codigo_lote=codigo.get(),fecha_vencimiento=vencimiento.get())
            else:
                if lote.get() not in lm: raise ValueError('Seleccione el lote.')
                l=lm[lote.get()]; opts['id_lote']=l['id_lote']
                if l['estado_vencimiento']=='VENCIDO' and tipo!='Ajuste':
                    if not messagebox.askyesno('Lote vencido','El lote está vencido. ¿Confirma este movimiento?',parent=w): return
                    opts['permitir_vencido']=True
        if tipo!='Ajuste':
            if not motivo.get(): raise ValueError('Seleccione un motivo.')
            opts.update(id_motivo=ms[motivo.get()],referencia=referencia.get())
        if tipo=='Entrada':
            if destino.get() not in us: raise ValueError('Seleccione el destino.')
            registrar_entrada(es[emp.get()],p['id_producto'],us[destino.get()],cantidad.get(),texto,costo_unitario=costo.get(),**opts)
        elif tipo=='Salida':
            if origen.get() not in us: raise ValueError('Seleccione el origen.')
            registrar_salida(es[emp.get()],p['id_producto'],us[origen.get()],cantidad.get(),texto,**opts)
        elif tipo=='Transferencia':
            if origen.get() not in us or destino.get() not in us: raise ValueError('Seleccione origen y destino.')
            registrar_transferencia(es[emp.get()],p['id_producto'],us[origen.get()],us[destino.get()],cantidad.get(),texto,**opts)
        else:
            if origen.get() not in us: raise ValueError('Seleccione la ubicación a ajustar.')
            if not texto.strip(): raise ValueError('Indique la razón del ajuste.')
            registrar_ajuste(es[emp.get()],p['id_producto'],us[origen.get()],cantidad.get(),texto,**opts)
        w.destroy(); al_cambiar()
    boton(pie,'Cancelar',w.destroy).pack(side='left'); boton(pie,'Guardar movimiento',seguro(w,guardar),'Success').pack(side='right')

class ConteoUI:
    def __init__(self,padre,root,tabla,al_cambiar):
        from ui.tareas_ui import TrabajosUI
        self.root=root;self.padre=padre;self.tabla_factory=tabla;self.al_cambiar=al_cambiar
        self.filas={};self.guardado=None;self.ubicacion_cargada=None;self.cerrado=False;self.cargando=False
        self.revision=0;self.revision_guardada=-1;self.autoguardado=None;self.trabajo=TrabajosUI(root)
        from ui.ui_components import ModuleHeader
        ModuleHeader(padre,'Conteo físico de inventario','Seleccione una ubicación, registre las cantidades y revise las diferencias antes de aplicar.')
        paso1=crear_panel(padre,SPACING_MD);paso1.pack(fill='x',pady=(0,SPACING_SM))
        ttk.Label(paso1,text='1. Seleccione la ubicación a contar',style='CardTitle.TLabel').pack(anchor='w')
        f=ttk.Frame(paso1);f.pack(fill='x',pady=SPACING_SM)
        ubicaciones=listar_ubicaciones(); empleados=listar_empleados_activos()
        self.us={self.nombre_ubicacion(u):u['id_ubicacion'] for u in ubicaciones}
        self.es={e['codigo_empleado']+' · '+(e['nombres']+' '+e.get('apellidos','')).strip():e['id_empleado'] for e in empleados}
        for col,titulo in ((0,'Ubicación'),(1,'Empleado responsable')):ttk.Label(f,text=titulo).grid(row=0,column=col,sticky='w')
        self.u=ttk.Combobox(f,values=list(self.us),state='readonly');self.e=ttk.Combobox(f,values=list(self.es),state='readonly')
        for col,w in enumerate((self.u,self.e)):w.grid(row=1,column=col,sticky='ew',padx=(0,SPACING_SM));f.columnconfigure(col,weight=1)
        if self.us:self.u.current(0)
        if self.es:self.e.current(0)
        self.b_cargar=boton(f,'Cargar inventario de esta ubicación',seguro(root,self.cargar),'Primary');self.b_cargar.grid(row=1,column=2,sticky='e')
        self.contexto=ttk.Label(paso1,text='Seleccione ubicación y responsable para comenzar.');self.contexto.pack(anchor='w')
        self.u.bind('<<ComboboxSelected>>',lambda _:self.contexto_cambiado())
        self.e.bind('<<ComboboxSelected>>',lambda _:self.responsable_cambiado())
        ttk.Label(padre,text='2. Registre el conteo físico',style='CardTitle.TLabel').pack(anchor='w',pady=(SPACING_SM,0))
        self.resumen=ttk.Label(padre,text='El inventario aparecerá al cargar la ubicación.',wraplength=1100);self.resumen.pack(anchor='w',pady=SPACING_XS)
        self.progreso=ttk.Progressbar(padre,maximum=1,value=0);self.progreso.pack(fill='x',pady=(0,SPACING_SM))
        self.t=tabla(padre,('codigo','nombre','posicion','cantidad_sistema','cantidad_fisica','diferencia','estado_conteo'),
            ('Código','Producto','Posición','Stock sistema','Conteo físico','Diferencia','Estado'),(110,280,80,115,115,100,120))
        self.t.configure(height=3)
        for estado,tono in [('CORRECTO','success'),('FALTANTE','danger'),('SOBRANTE','warning'),('PENDIENTE','info')]:
            self.t.tag_configure(estado,background=COLORES[tono+'_bg'],foreground=COLORES[tono+'_text'])
        self.t.bind('<<TreeviewSelect>>',lambda _:self.seleccionar())
        self.t.bind('<Double-1>',lambda _:self.enfocar_editor())
        self.t.bind('<Return>',lambda _:self.enfocar_editor())
        self.editor=crear_panel(padre,SPACING_SM)
        self.producto_seleccionado=ttk.Label(self.editor,text='',wraplength=600);self.producto_seleccionado.pack(side='left',fill='x',expand=True)
        ttk.Label(self.editor,text='Cantidad física:').pack(side='left',padx=SPACING_SM)
        self.fisico=ttk.Entry(self.editor,width=14);self.fisico.pack(side='left')
        self.fisico.bind('<Return>',lambda _:seguro(root,self.editar)())
        self.b_editar=boton(self.editor,'Guardar conteo',seguro(root,self.editar),'Primary');self.b_editar.pack(side='left',padx=SPACING_SM)
        self.paso3=crear_panel(padre,SPACING_MD);self.paso3.pack(fill='x',pady=SPACING_SM)
        ttk.Label(self.paso3,text='3. Revise diferencias y aplique ajustes',style='CardTitle.TLabel').pack(anchor='w')
        self.revision_texto=ttk.Label(self.paso3,text='Complete todas las filas para revisar los ajustes.',wraplength=1100);self.revision_texto.pack(anchor='w',pady=SPACING_XS)
        acciones=ttk.Frame(self.paso3);acciones.pack(fill='x')
        self.b_guardar=boton(acciones,'Guardar borrador',seguro(root,self.guardar));self.b_guardar.pack(side='left')
        self.b_aplicar=boton(acciones,'Revisar y aplicar ajustes',seguro(root,self.aplicar),'Primary');self.b_aplicar.pack(side='right')
        self.estado=ttk.Label(padre,text='Sin conteo iniciado.',wraplength=1100);self.estado.pack(anchor='w',pady=SPACING_XS)
        self.panel_borradores=crear_panel(padre,SPACING_SM)
        ttk.Label(self.panel_borradores,text='Borradores',style='CardTitle.TLabel').pack(side='left',padx=(0,SPACING_SM))
        self.borradores=ttk.Combobox(self.panel_borradores,values=[],state='readonly',width=65);self.borradores.pack(side='left',fill='x',expand=True)
        self.borradores.bind('<<ComboboxSelected>>',lambda _:seguro(root,self.cargar_borrador)())
        self.mapa_borradores={}; self.actualizar_borradores()
        self.controles()

    @staticmethod
    def nombre_ubicacion(u):
        try:nombre=describir_posicion(u).replace(' - ',' · ')
        except (ValueError,TypeError,KeyError):nombre=u['codigo_ubicacion']
        return nombre+' · '+u['codigo_ubicacion']

    def vigente(self):return self.ubicacion_cargada is not None and self.us.get(self.u.get())==self.ubicacion_cargada

    def controles(self):
        editable=bool(self.filas) and self.vigente() and not self.cerrado and not self.cargando
        r=resumir_conteo(list(self.filas.values()))
        completo=editable and r['contados']==r['registros']
        self.b_guardar.configure(state='normal' if editable and not self.trabajo.ocupado else 'disabled')
        self.b_aplicar.configure(state='normal' if completo and not self.trabajo.ocupado and self.revision==self.revision_guardada else 'disabled')
        self.b_cargar.configure(state='disabled' if self.trabajo.ocupado else 'normal')
        for w in (self.u,self.e,self.borradores):w.configure(state='disabled' if self.trabajo.ocupado or self.cargando else 'readonly')
        if not editable:self.editor.pack_forget()

    def contexto_cambiado(self):
        if self.filas and not self.cerrado and not self.vigente() and self.revision!=self.revision_guardada:
            self.u.set(next(n for n,i in self.us.items() if i==self.ubicacion_cargada))
            self.estado.configure(text='Espere el guardado del progreso actual antes de cambiar de ubicación.')
        if self.filas and not self.vigente():self.estado.configure(text='Cargue el inventario de la nueva ubicación antes de contar. '+('El conteo anterior está cerrado.' if self.cerrado else 'El borrador anterior se conserva.'))
        self.controles()

    def responsable_cambiado(self):
        if self.filas and not self.cerrado and self.vigente():
            self.revision+=1;self.programar_guardado()

    def error(self,e):
        self.cargando=False;self.estado.configure(text=str(e)+' No se aplicaron ajustes desde esta operación.')
        self.controles()

    def actualizar_borradores(self,filas=None):
        if filas is None:
            try:filas=listar_conteos()
            except Exception:return
        filas=[c for c in filas if c['estado']=='BORRADOR']
        # Una etiqueta puede representar varios borradores creados en el mismo
        # minuto. Se muestran segundos y un ordinal legible, nunca el ID SQL.
        self.mapa_borradores={}
        for c in filas:
            fecha=c['fecha'].strftime('%d/%m/%Y %H:%M:%S')
            base=f"{self.nombre_ubicacion(c)} · {fecha} · {c['empleado']}";etiqueta=base;n=2
            while etiqueta in self.mapa_borradores:etiqueta=base+f' · Registro {n}';n+=1
            self.mapa_borradores[etiqueta]=c
        self.borradores.configure(values=list(self.mapa_borradores))
        self.borradores.set('Continuar borrador…')
        if filas:self.panel_borradores.pack(fill='x',pady=SPACING_SM)
        else:self.panel_borradores.pack_forget()

    def cargar_borrador(self):
        if self.borradores.get() not in self.mapa_borradores: raise ValueError('Seleccione un borrador.')
        self.validar_cambio()
        numero=self.mapa_borradores[self.borradores.get()]['id_conteo'];self.cargando=True;self.controles()
        def mostrar(datos):
            c,filas=datos
            if c['estado']!='BORRADOR':self.error(ValueError('Este conteo ya está cerrado.'));return
            nombre=next((n for n,i in self.us.items() if i==c['id_ubicacion']),None)
            if nombre is None:self.error(ValueError('La ubicación del borrador ya no está activa.'));return
            self.u.set(nombre);self.e.set(next((n for n,i in self.es.items() if i==c['id_empleado']),'Seleccione un responsable activo'))
            self.iniciar_filas(filas,c['id_ubicacion'],numero)
            self.estado.configure(text='Borrador recuperado. Continúe contando las filas pendientes.')
        self.trabajo.ejecutar(lambda:cargar_conteo(numero),mostrar,self.error)

    def validar_cambio(self):
        if self.trabajo.ocupado:raise ValueError('Espere a que termine el guardado o la carga actual.')
        if self.filas and not self.cerrado and self.revision!=self.revision_guardada:
            raise ValueError('Guarde el borrador actual antes de abrir otro conteo.')
        if self.autoguardado is not None:self.root.after_cancel(self.autoguardado);self.autoguardado=None

    def cargar(self):
        if self.u.get() not in self.us: raise ValueError('Seleccione una ubicación.')
        if self.e.get() not in self.es:raise ValueError('Seleccione un empleado responsable activo.')
        self.validar_cambio();ubicacion=self.us[self.u.get()];self.cargando=True;self.controles()
        self.estado.configure(text='Cargando inventario de la ubicación…')
        def mostrar(filas):
            for f in filas:f['contado']=False
            self.iniciar_filas(filas,ubicacion,None)
            self.estado.configure(text='Pendiente de conteo. Seleccione una fila o haga doble clic para ingresar la cantidad.' if filas else 'Esta ubicación no tiene productos o lotes activos para contar.')
        self.trabajo.ejecutar(lambda:listar_conteo_ubicacion(ubicacion),mostrar,self.error)

    def iniciar_filas(self,filas,ubicacion,numero):
        for f in filas:
            f['_valor_previo_sin_verificar']=numero is not None and f.get('contado') is None
            f['contado']=bool(f.get('contado'))
        self.guardado=numero;self.ubicacion_cargada=ubicacion;self.cerrado=False;self.cargando=False
        self.revision=0;self.revision_guardada=0
        self.filas={str(i):f for i,f in enumerate(filas)};self.editor.pack_forget();self.mostrar()

    def mostrar(self):
        seleccion=self.t.selection()
        self.t.configure(height=max(2,min(5,len(self.filas))))
        self.t.delete(*self.t.get_children())
        for i,f in self.filas.items():
            diferencia=f['cantidad_fisica']-f['cantidad_sistema'] if f['contado'] else None
            estado='PENDIENTE' if diferencia is None else 'CORRECTO' if diferencia==0 else 'FALTANTE' if diferencia<0 else 'SOBRANTE'
            nombre=f['nombre']+(f" · Lote {f['codigo_lote']}" if f.get('codigo_lote') else '')
            insertar_fila(self.t,'','end',iid=i,tags=(estado,),columnas=('codigo','nombre','posicion','cantidad_sistema','cantidad_fisica','diferencia_visual','estado_conteo'),values=(f['codigo'],nombre,f.get('posicion') or 'Sin registrar',f['cantidad_sistema'],
                format_numero(f['cantidad_fisica']) if f['contado'] else 'Pendiente',('+' if diferencia is not None and diferencia>0 else '')+format_numero(diferencia) if diferencia is not None else '—',estado))
        if seleccion and seleccion[0] in self.filas:self.t.selection_set(seleccion[0])
        r=resumir_conteo(list(self.filas.values()))
        self.contexto.configure(text=f"Ubicación: {self.u.get() if self.vigente() else 'Seleccione la ubicación cargada'} · Productos: {r['productos']} · "+('Cerrado' if self.cerrado else 'Pendiente de conteo' if r['contados']<r['registros'] else 'Conteo completado'))
        self.resumen.configure(text=f"Productos: {r['productos']} · Contados: {r['contados']} / {r['registros']} registros · Sin diferencia: {r['correctos']} · Faltantes: {r['faltantes']} · Sobrantes: {r['sobrantes']}")
        diferencias='; '.join(u+' '+format_numero(v['diferencia']) for u,v in r['por_unidad'].items())
        if r['contados']:self.resumen.configure(text=self.resumen['text']+f" · Diferencia {'total' if r['contados']==r['registros'] else 'parcial'}: {diferencias}")
        self.progreso.configure(maximum=max(1,r['registros']),value=r['contados'])
        if r['registros'] and r['contados']==r['registros']:
            totales=' · '.join(f"{u}: sistema {format_numero(v['sistema'])} / físico {format_numero(v['fisico'])} / diferencia {format_numero(v['diferencia'])}" for u,v in r['por_unidad'].items())
            self.revision_texto.configure(text=f"{'Conteo cerrado' if self.cerrado else 'Conteo completado'}. {totales}\nAjustes {'realizados' if self.cerrado else 'necesarios'}: {r['faltantes']+r['sobrantes']} · Sin cambios: {r['correctos']}")
        else:self.revision_texto.configure(text=f"Complete todos los registros antes de aplicar ajustes. Pendientes: {r['registros']-r['contados']}.")
        self.controles()

    def seleccionar(self):
        if not self.t.selection() or self.cerrado or not self.vigente() or self.cargando:self.editor.pack_forget();return
        f=self.filas.get(self.t.selection()[0])
        if f is None:return
        self.editor.pack(fill='x',before=self.paso3,pady=SPACING_XS)
        self.producto_seleccionado.configure(text=f"{f['nombre']}"+(f" · Lote {f['codigo_lote']}" if f.get('codigo_lote') else '')+f"\nStock sistema: {format_numero(f['cantidad_sistema'])}")
        self.fisico.delete(0,'end')
        if f['contado'] or f.get('_valor_previo_sin_verificar'):
            valor=Decimal(str(f['cantidad_fisica']))
            self.fisico.insert(0,format_numero(valor) if valor==valor.quantize(Decimal('.01')) else str(valor))

    def enfocar_editor(self):
        self.seleccionar()
        if self.editor.winfo_manager():self.fisico.focus_set();self.fisico.selection_range(0,'end')

    def editar(self):
        if self.cerrado:raise ValueError('El conteo está finalizado; inicie uno nuevo para cambiar cantidades.')
        if not self.vigente() or self.cargando:raise ValueError('Cargue la ubicación seleccionada antes de contar.')
        if not self.t.selection(): raise ValueError('Seleccione un producto/lote.')
        f=self.filas[self.t.selection()[0]]
        f['cantidad_fisica']=decimal_inventario(self.fisico.get(),'Cantidad física');f['contado']=True
        self.revision+=1;self.mostrar();self.programar_guardado()

    def programar_guardado(self):
        if self.autoguardado is not None:self.root.after_cancel(self.autoguardado)
        self.estado.configure(text='Conteo registrado. Guardando progreso…')
        self.autoguardado=self.root.after(400,self.guardar_automaticamente)

    def guardar_automaticamente(self):
        try:self.guardar(automatico=True)
        except (ValueError,RuntimeError) as e:self.error(e)

    def guardar(self,automatico=False):
        from copy import deepcopy
        self.autoguardado=None
        if not self.padre.winfo_exists():return
        if self.cerrado:raise ValueError('El conteo está cerrado.')
        if self.trabajo.ocupado:
            self.autoguardado=self.root.after(150,self.guardar_automaticamente if automatico else lambda:seguro(self.root,self.guardar)());return
        if not self.filas:raise ValueError('Primero cargue productos de una ubicación.')
        if self.e.get() not in self.es or self.u.get() not in self.us: raise ValueError('Seleccione empleado y ubicación.')
        if self.us[self.u.get()]!=self.ubicacion_cargada: raise ValueError('La ubicación cambió. Cárguela de nuevo antes de guardar.')
        empleado=self.es[self.e.get()];ubicacion=self.ubicacion_cargada;filas=deepcopy(list(self.filas.values()));numero=self.guardado;revision=self.revision
        def guardar():
            numero_guardado=guardar_conteo(empleado,ubicacion,filas,id_conteo=numero)
            try:borradores=listar_conteos()
            except Exception:borradores=None
            return numero_guardado,borradores
        def mostrar(resultado):
            numero,borradores=resultado
            self.guardado=numero;self.revision_guardada=revision
            self.estado.configure(text='Guardado automáticamente.' if automatico else 'Borrador guardado. Puede continuar después.')
            if borradores is not None:self.actualizar_borradores(borradores)
            self.controles()
            if self.revision!=revision:self.programar_guardado()
        self.trabajo.ejecutar(guardar,mostrar,self.error)
        self.controles()

    def aplicar(self):
        from datetime import datetime
        from copy import deepcopy
        if self.cerrado:raise ValueError('El conteo ya fue finalizado.')
        r=resumir_conteo(list(self.filas.values()))
        if not r['registros'] or r['contados']!=r['registros']:raise ValueError('Complete todos los productos/lotes antes de revisar los ajustes.')
        if not self.vigente():raise ValueError('La ubicación seleccionada no corresponde al conteo cargado.')
        if self.e.get() not in self.es:raise ValueError('Seleccione un responsable activo antes de revisar.')
        if self.trabajo.ocupado or not self.guardado or self.revision!=self.revision_guardada:
            raise ValueError('Espere el guardado automático o guarde el borrador antes de revisar.')
        w,cuerpo,pie=modal(self.root,'Revisión del conteo físico',1000,610);w.grab_set()
        numero=self.guardado;responsable=self.e.get();ajustes=r['faltantes']+r['sobrantes'];aplicando=[False]
        filas_revisadas=deepcopy(list(self.filas.values()));empleado_revisado=self.es[responsable]
        from core.audit_service import use_context, capture_context, audit, run_in_context
        with use_context(origin='desktop'):
            trace=capture_context()
            audit.record('UI','COUNT_ADJUSTMENTS_PREPARED','CONFIRMATION_REQUIRED',
                         entity_type='conteo',entity_id=numero,data={'adjustments':ajustes})
        aviso='No hay diferencias. Se cerrará el conteo sin generar movimientos.' if ajustes==0 else 'Se generará 1 ajuste de inventario.' if ajustes==1 else f'Se generarán {ajustes} ajustes de inventario.'
        ttk.Label(cuerpo,text=f"{self.u.get()}\nResponsable: {responsable}\n{aviso}",wraplength=920).pack(anchor='w',pady=SPACING_SM)
        t=self.tabla_factory(cuerpo,('producto','sistema','fisico','diferencia','movimiento'),('Producto / lote','Sistema','Físico','Diferencia','Movimiento a generar'),(300,110,110,110,210))
        t.configure(height=5)
        for f in self.filas.values():
            d=f['cantidad_fisica']-f['cantidad_sistema']
            movimiento=('Ajuste salida ' if d<0 else 'Ajuste entrada ')+format_numero(abs(d)) if d else 'Sin movimiento'
            insertar_fila(t,'','end',columnas=('producto','sistema','fisico','diferencia_visual','movimiento'),values=(f['nombre']+(f" · Lote {f['codigo_lote']}" if f.get('codigo_lote') else ''),format_numero(f['cantidad_sistema']),format_numero(f['cantidad_fisica']),('+' if d>0 else '')+format_numero(d),movimiento))
        ttk.Label(cuerpo,text='Las existencias se modificarán solo al confirmar. Si el stock cambió desde la carga, se rechazará la operación completa.',wraplength=900).pack(anchor='w',pady=SPACING_SM)
        def cancelar():
            if not aplicando[0]:
                with use_context(trace):audit.record('UI','COUNT_ADJUSTMENTS','CANCELLED',entity_type='conteo',entity_id=numero)
                w.destroy()
        def confirmar():
            with use_context(trace):audit.record('UI','COUNT_ADJUSTMENTS','CONFIRMED',entity_type='conteo',entity_id=numero)
            aplicando[0]=True;confirmacion.configure(state='disabled');cancelacion.configure(state='disabled')
            def completado(_):
                self.cerrado=True;self.mostrar();self.editor.pack_forget();w.destroy()
                self.estado.configure(text=f"Conteo finalizado correctamente. Ajustes realizados: {ajustes} · Sin cambios: {r['correctos']} · Fecha: {datetime.now():%d/%m/%Y %H:%M:%S} · Empleado: {responsable}")
                self.actualizar_borradores();self.al_cambiar()
            def fallar(error):
                aplicando[0]=False;confirmacion.configure(state='normal');cancelacion.configure(state='normal');self.error(error)
                messagebox.showerror('Conteo físico',str(error),parent=w)
            self.trabajo.ejecutar(lambda:run_in_context(trace,aplicar_conteo,numero,esperado=filas_revisadas,empleado_esperado=empleado_revisado),completado,fallar)
            self.controles()
        cancelacion=boton(pie,'Cancelar',cancelar);cancelacion.pack(side='left')
        confirmacion=boton(pie,'Confirmar ajustes',confirmar,'Primary');confirmacion.pack(side='right')
        w.protocol('WM_DELETE_WINDOW',cancelar)
