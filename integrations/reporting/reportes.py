from core.formato_numerico import format_numero
"""Un solo conjunto filtrado alimenta vista previa, PDF y Excel."""
from datetime import datetime,date,timedelta
from decimal import Decimal
from pathlib import Path
from inventory.inventario_service import buscar_inventario,consultar
from inventory.movimientos import buscar_movimientos
from core.config_manager import obtener,ruta

TIPOS=('Inventario actual','Movimientos','Stock bajo','Agotados','Entradas','Salidas','Transferencias',
       'Historial de movimientos','Inventario por ubicación','Productos por categoría','Predicción de stock',
       'Anomalías','Alertas','Empleados','Vigilancia / Intrusiones','Reconocimiento facial','Resumen general')
FILTROS={t:('producto','categoria','ubicacion','almacen') for t in ('Inventario actual','Stock bajo','Agotados','Inventario por ubicación','Productos por categoría')}
for t in ('Entradas','Salidas','Transferencias'): FILTROS[t]=('desde','hasta','producto','categoria','ubicacion','almacen')
FILTROS['Historial de movimientos']=('desde','hasta','producto','categoria','ubicacion','almacen','movimiento')
FILTROS['Movimientos']=FILTROS['Historial de movimientos']
FILTROS['Vigilancia / Intrusiones']=('desde','hasta','estado')
FILTROS.update({'Predicción de stock':('producto','categoria','riesgo'),'Anomalías':('desde','hasta','producto','nivel','movimiento','estado'),
               'Alertas':('desde','hasta','producto','nivel','estado'),'Empleados':('estado',),'Reconocimiento facial':(),'Resumen general':()})
for t in ('Inventario actual','Productos por categoría'): FILTROS[t] += ('estado',)

def obtener_datos_reporte(tipo,filtros=None):
    if tipo not in TIPOS: raise ValueError('Reporte desconocido.')
    f={k:v for k,v in (filtros or {}).items() if v not in (None,'','Todos','Todas')}
    if any(k not in FILTROS[tipo] for k in f): raise ValueError('Filtro no aplicable a este reporte.')
    for k in ('desde','hasta'):
        if f.get(k): date.fromisoformat(f[k])
    if f.get('desde') and f.get('hasta') and f['desde']>f['hasta']: raise ValueError('Rango de fechas inválido.')
    filas=[]; mensaje=''; totales={}
    base=('codigo','nombre','categoria','unidad_medida','stock_actual','stock_minimo','estado_stock','ubicaciones')
    columnas=base
    if tipo in ('Inventario actual','Stock bajo','Agotados','Productos por categoría','Inventario por ubicación'):
        estado={'Stock bajo':'Stock bajo','Agotados':'Agotados'}.get(tipo,'Todos')
        ps=buscar_inventario(estado=estado,id_categoria=f.get('categoria'),id_ubicacion=f.get('ubicacion'),almacen=f.get('almacen'))
        if tipo=='Stock bajo': ps=[p for p in ps if p['stock_actual']>0]
        if f.get('producto'): ps=[p for p in ps if p['id_producto']==f['producto']]
        from inventory.mapa_almacen import ubicaciones_producto
        if tipo=='Inventario por ubicación':
            columnas=('codigo_ubicacion','almacen','zona','pasillo','estante','nivel','posicion','codigo','nombre','cantidad','unidad_medida')
            for p in ps:
                for u in ubicaciones_producto(p['id_producto']):
                    if f.get('ubicacion') and u['id_ubicacion']!=f['ubicacion']: continue
                    if f.get('almacen') and u.get('almacen')!=f['almacen']: continue
                    filas.append({**u,'codigo':p['codigo'],'nombre':p['nombre']})
        else:
            for p in ps:
                if f.get('estado') and p['estado_stock']!=f['estado']: continue
                p=dict(p)
                p['ubicaciones']='; '.join(u['codigo_ubicacion'] for u in ubicaciones_producto(p['id_producto'])) or 'Sin existencias ubicadas'
                filas.append(p)
        # Totales por unidad; no sumar litros con kilogramos.
        for p in filas:
            unidad=p['unidad_medida']; k='Stock '+unidad
            totales[k]=totales.get(k,Decimal(0))+p.get('cantidad',p.get('stock_actual',0))
    elif tipo in ('Entradas','Salidas','Transferencias','Historial de movimientos','Movimientos'):
        columnas=('fecha_movimiento','tipo_movimiento','producto','cantidad','unidad_medida','empleado','ubicacion_origen','ubicacion_destino','motivo','observacion')
        tipo_mov={'Entradas':'Entrada','Salidas':'Salida','Transferencias':'Transferencia'}.get(tipo,f.get('movimiento'))
        filas=buscar_movimientos(tipo_movimiento=tipo_mov,fecha_desde=f.get('desde'),fecha_hasta=f.get('hasta'),id_producto=f.get('producto'),id_categoria=f.get('categoria'),id_ubicacion=f.get('ubicacion'))
        unidades={p['codigo']:p['unidad_medida'] for p in consultar('SELECT codigo,unidad_medida FROM productos')}
        filas=[{**r,'unidad_medida':unidades.get(r['codigo_producto'])} for r in filas]
        if f.get('almacen'):
            codigos={u['codigo_ubicacion'] for u in consultar('SELECT codigo_ubicacion FROM ubicaciones WHERE almacen=?',f['almacen'])}
            filas=[r for r in filas if r['ubicacion_origen'] in codigos or r['ubicacion_destino'] in codigos]
    elif tipo=='Predicción de stock':
        from core.automatizacion_inventario import obtener_prediccion as predecir_agotamiento
        columnas=('producto','unidad_medida','stock_actual','consumo_promedio_diario','tendencia','dias_restantes_promedio','fecha_agotamiento','riesgo','mensaje')
        for p in buscar_inventario(id_categoria=f.get('categoria')):
            if f.get('producto') and p['id_producto']!=f['producto']: continue
            r=predecir_agotamiento(p['id_producto'],False)
            if not r.get('disponible',True):r.update(producto=p['nombre'],stock_actual=p['stock_actual'])
            r['unidad_medida']=p['unidad_medida']
            if not f.get('riesgo') or r['riesgo']==f['riesgo']: filas.append(r)
    elif tipo=='Anomalías':
        from ai.anomalies.deteccion_anomalias import listar_anomalias
        columnas=('fecha','producto','tipo_movimiento','cantidad','tipo_anomalia','nivel','score','motivo','estado')
        registradas=listar_anomalias(fecha_desde=f.get('desde'),fecha_hasta=f.get('hasta'),producto=f.get('producto'),nivel=f.get('nivel'),movimiento=f.get('movimiento'))
        filas=[a for a in registradas if not f.get('estado') or a['estado']==f['estado']]
        if not filas: mensaje='No hay anomalías registradas para los filtros seleccionados. Los movimientos nuevos se evalúan automáticamente.'
    elif tipo in ('Alertas','Vigilancia / Intrusiones'):
        columnas=('fecha','tipo_alerta','nivel','producto','mensaje','estado')
        cond=['a.fecha_eliminacion IS NULL']; args=[]
        for campo,valor in [('a.id_producto',f.get('producto')),('a.nivel',f.get('nivel'))]:
            if valor: cond.append(campo+'=?'); args.append(('Critica' if valor=='CRÍTICA' else valor.title()) if campo=='a.nivel' else valor)
        if f.get('desde'): cond.append('a.fecha_creacion>=?'); args.append(f['desde'])
        if f.get('hasta'): cond.append('a.fecha_creacion<DATEADD(day,1,CAST(? AS date))'); args.append(f['hasta'])
        if f.get('estado'): cond.append('a.atendida=?'); args.append(1 if f['estado']=='ATENDIDA' else 0)
        if tipo=='Vigilancia / Intrusiones':cond.append("LEFT(a.mensaje,10)='[intrusion:'")
        extra=',a.detalle_vigilancia' if tipo=='Vigilancia / Intrusiones' else ''
        filas=consultar("SELECT a.fecha_creacion fecha,ta.nombre tipo_alerta,p.nombre producto,a.nivel,a.mensaje,CASE WHEN a.atendida=1 THEN 'ATENDIDA' ELSE 'PENDIENTE' END estado"+extra+" FROM alertas a LEFT JOIN productos p ON p.id_producto=a.id_producto LEFT JOIN tipos_alerta ta ON ta.id_tipo_alerta=a.id_tipo_alerta WHERE "+' AND '.join(cond)+' ORDER BY a.fecha_creacion DESC',*args)
        if tipo=='Vigilancia / Intrusiones':
            import json
            from surveillance.identidad_vigilancia import texto_identidad
            columnas=('fecha','zona','camara','track_id','identidad','codigo_empleado','confianza','similitud_facial','estado','mensaje')
            for a in filas:
                try:detalle=json.loads(a.pop('detalle_vigilancia',None) or '{}')
                except ValueError:detalle={}
                for k in ('zona','camara','track_id','codigo_empleado','confianza','similitud_facial'):a[k]=detalle.get(k)
                a['identidad']=texto_identidad(detalle)
    elif tipo=='Empleados':
        from inventory.empleados import listar_empleados
        columnas=('codigo_empleado','nombres','apellidos','cargo','estado'); filas=listar_empleados()
        filas=[{**e,'estado':'ACTIVO' if e['estado'] else 'INACTIVO'} for e in filas if not f.get('estado') or bool(e['estado'])==(f['estado']=='ACTIVO')]
    elif tipo=='Reconocimiento facial':
        columnas=('fecha','persona','resultado')
        mensaje='Sin historial persistente de reconocimiento facial. Las relaciones de rostros registrados no representan reconocimientos realizados.'
    else:
        return _resumen_general()
    totales['Registros']=len(filas)
    r={'titulo':tipo,'generado':datetime.now(),'filtros':f,'columnas':columnas,'filas':filas,'totales':totales,
       'mensaje':mensaje or ('No hay información disponible para los filtros seleccionados.' if not filas else '')}
    return preparar_reporte(r)

ETIQUETAS={'codigo':'Código','codigo_producto':'Código','codigo_ubicacion':'Ubicación','categoria':'Categoría',
           'almacen':'Almacén','descripcion':'Descripción','stock_actual':'Stock total','stock_minimo':'Mínimo','unidad_medida':'Unidad','fecha_movimiento':'Fecha / hora',
           'dias_restantes_promedio':'Días estimados','consumo_promedio_diario':'Consumo / día','fecha_agotamiento':'Fecha estimada'}
ETIQUETAS.update({'estado_stock':'Estado','ubicaciones':'Ubicaciones con stock','stock_actual':'Stock actual',
    'unidad_medida':'Unidad','ubicacion_origen':'Origen','ubicacion_destino':'Destino','fecha':'Fecha / hora',
    'fecha_agotamiento':'Fecha estimada','observacion':'Observación','tipo_movimiento':'Tipo','nombre':'Producto',
    'tipo_anomalia':'Tipo anomalía','tipo_alerta':'Tipo de alerta','valor':'Valor'})

def preparar_reporte(reporte):
    """Derivar presentación una sola vez; nunca consultar SQL desde los exportadores."""
    from collections import Counter,defaultdict
    r=dict(reporte); filas=r['filas']; tipo=r['titulo']
    indicadores={'Registros':len(filas)}; graficos=[]; notas=list(r.get('notas',[]))
    def grafico(titulo,conteos,unidad='Registros'):
        if conteos and any(v>0 for v in conteos.values()):
            orden=sorted(conteos.items(),key=lambda x:(-x[1],str(x[0])))
            puntos=orden[:8]
            if len(orden)>8: puntos.append(('Otros',sum(v for _,v in orden[8:])))
            graficos.append({'titulo':titulo,'unidad':unidad,'datos':puntos})
    if 'stock_minimo' in r['columnas']:
        indicadores.pop('Registros')
        indicadores.update({'Productos':len(filas),'Stock bajo':sum(0<p['stock_actual']<=p['stock_minimo'] for p in filas),
            'Agotados':sum(p['stock_actual']==0 for p in filas)})
        if filas and all(p.get('precio') is not None for p in filas):
            indicadores['Valor a precio registrado']=sum((Decimal(str(p['precio']))*Decimal(str(p['stock_actual'])) for p in filas),Decimal(0))
            notas.append('La valoración utiliza el precio registrado del producto; no representa costo contable.')
        categorias=defaultdict(lambda:defaultdict(Decimal))
        for p in filas: categorias[p['unidad_medida']][p.get('categoria') or 'Sin categoría']+=Decimal(str(p['stock_actual']))
        for u,datos in sorted(categorias.items()): grafico('Stock por categoría',datos,u)
        notas.append('Stock total del producto en todas sus ubicaciones activas. Los filtros de ubicación seleccionan productos; no recortan su stock global. Use Inventario por ubicación para cantidades locales.')
    elif 'tipo_movimiento' in r['columnas'] and tipo!='Anomalías':
        por_tipo=defaultdict(set)
        for p in filas: por_tipo[p['tipo_movimiento']].add(p['id_movimiento'])
        cantidades={k:len(v) for k,v in por_tipo.items()}
        indicadores.update(cantidades)
        indicadores.update({'Operaciones únicas':len({p['id_movimiento'] for p in filas})})
        if indicadores['Operaciones únicas']==len(filas): indicadores.pop('Registros')
        grafico('Movimientos por tipo',cantidades,'Operaciones únicas')
        por_producto=defaultdict(set)
        for p in filas: por_producto[p['producto']].add(p['id_movimiento'])
        grafico('Productos con mayor movimiento', {k:len(v) for k,v in por_producto.items()},'Operaciones')
        notas.append('Cada fila corresponde a un detalle. Los gráficos cuentan operaciones únicas; las transferencias no representan consumo.')
    elif tipo=='Predicción de stock':
        indicadores.update({'Con historial suficiente':sum(bool(p.get('datos_suficientes')) for p in filas),
            'Riesgo alto / crítico':sum(p['riesgo'] in ('ALTO','CRÍTICO') for p in filas)})
        grafico('Productos por riesgo',Counter(p['riesgo'] for p in filas),'Productos')
        notas.append('Las predicciones son estimaciones basadas en el historial disponible. Sin historial suficiente, no se calcula una fecha de agotamiento.')
    elif tipo=='Anomalías':
        indicadores.update(Counter(p['nivel'] for p in filas))
        indicadores['Pendientes']=sum(p.get('estado')=='PENDIENTE' for p in filas)
        grafico('Anomalías por nivel',Counter(p['nivel'] for p in filas))
        notas.append('El score representa el nivel de desviación respecto al patrón histórico y no una probabilidad de fraude.')
    elif tipo=='Alertas':
        indicadores.update({'Pendientes':sum(p['estado']=='PENDIENTE' for p in filas)})
        grafico('Alertas por tipo',Counter(p.get('tipo_alerta') or 'Sin tipo' for p in filas))
    elif tipo=='Empleados':
        indicadores.update({'Activos':sum(p['estado']=='ACTIVO' for p in filas)})
    elif tipo=='Inventario por ubicación':
        notas.append('Asignaciones físicas registradas: estante, nivel y posición. Cada nivel admite dos productos distintos; un producto agotado conserva su espacio asignado.')
    r.update(indicadores=r.get('indicadores',indicadores),graficos=r.get('graficos',graficos),notas=list(dict.fromkeys(notas)))
    return r

def _resumen_general():
    """Composición ejecutiva a partir de los mismos reportes, sin cálculos de IA paralelos."""
    inventario=obtener_datos_reporte('Inventario actual')
    alertas=obtener_datos_reporte('Alertas',{'estado':'PENDIENTE'})
    ahora=inventario['generado']
    movimientos=obtener_datos_reporte('Historial de movimientos',{'desde':(ahora-timedelta(days=29)).date().isoformat(),'hasta':ahora.date().isoformat()})
    prediccion=obtener_datos_reporte('Predicción de stock')
    from ai.anomalies.deteccion_anomalias import listar_anomalias
    anomalias=listar_anomalias()
    indicadores={k:v for k,v in inventario['indicadores'].items() if k!='Registros'}
    indicadores.update({'Alertas pendientes':len(alertas['filas']),
        'Movimientos · 30 días':movimientos['indicadores']['Operaciones únicas'],
        'Anomalías registradas':len(anomalias),
        'Riesgo alto / crítico':prediccion['indicadores']['Riesgo alto / crítico']})
    indicadores.update({k:v for k,v in inventario['totales'].items() if k.startswith('Stock ')})
    from core.estado_sistema import _pruebas
    estados=[{'componente':k,'estado':v['estado'],'comprobado':v.get('comprobado')} for k,v in _pruebas.items()]
    riesgos=sorted([p for p in prediccion['filas'] if p['riesgo'] in ('ALTO','CRÍTICO')],key=lambda p:p['dias_restantes_promedio'] if p['dias_restantes_promedio'] is not None else float('inf'))[:5]
    secciones=[{'titulo':'Últimos movimientos · 30 días','columnas':('fecha_movimiento','tipo_movimiento','producto','cantidad','unidad_medida'),'filas':movimientos['filas'][:5]},
        {'titulo':'Productos que requieren atención','columnas':('nombre','stock_actual','unidad_medida','estado_stock'),'filas':[p for p in inventario['filas'] if p['estado_stock']!='NORMAL'][:5]},
        {'titulo':'Riesgos de agotamiento','columnas':('producto','dias_restantes_promedio','riesgo'),'filas':riesgos},
        {'titulo':'Anomalías recientes','columnas':('fecha','producto','nivel','estado'),'filas':anomalias[:5]},
        {'titulo':'Últimas comprobaciones disponibles','columnas':('componente','estado','comprobado'),'filas':estados}]
    return preparar_reporte({'titulo':'Resumen general','generado':ahora,'filtros':{},'columnas':('indicador','valor'),
        'filas':[{'indicador':k,'valor':v} for k,v in indicadores.items()], 'indicadores':indicadores,
        'graficos':movimientos['graficos'],'secciones':secciones,'totales':{'Indicadores':len(indicadores)},'mensaje':'',
        'notas':['Resumen ejecutivo: se muestran hasta cinco registros por sección. Movimientos y productos más movidos: últimos 30 días.',
                 'Los estados reflejan comprobaciones de esta sesión, no monitoreo permanente. Sin comprobaciones se muestra información no disponible.']})

def ruta_disponible(archivo):
    """Sugerir un nombre sin colisiones; la escritura final usa creación exclusiva."""
    archivo=Path(archivo); candidato=archivo; numero=1
    while candidato.exists():
        candidato=archivo.with_name(f'{archivo.stem}_{numero:02d}{archivo.suffix}'); numero+=1
    return candidato
def etiqueta(k): return ETIQUETAS.get(k,k.replace('_',' ').capitalize())
def texto(v):
    if v is None: return 'Sin datos'
    if isinstance(v,datetime): return v.strftime(obtener('inventario','formato_fecha')+' %H:%M')
    if isinstance(v,date): return v.strftime(obtener('inventario','formato_fecha'))
    if isinstance(v,(Decimal,float)): return format_numero(v,agrupar=True)
    return str(v)

def nombre_archivo(r,extension):
    import unicodedata,re
    titulo=unicodedata.normalize('NFKD',r['titulo']).encode('ascii','ignore').decode()
    titulo=re.sub(r'[^A-Za-z0-9]+','_',titulo).strip('_')
    rango='_'.join(str(r['filtros'][k]) for k in ('desde','hasta') if r['filtros'].get(k)) or r['generado'].date().isoformat()
    return f'{titulo}_{rango}.{extension}'

def exportar_excel(r,archivo):
    from integrations.reporting.report_render import exportar_excel as generar
    return generar(r,archivo)


def exportar_pdf(r,archivo):
    from integrations.reporting.report_render import exportar_pdf as generar
    return generar(r,archivo)
