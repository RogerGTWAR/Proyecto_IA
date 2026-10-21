"""Preparar registros cronológicos a partir del catálogo y los saldos vigentes."""
from collections import Counter
from datetime import datetime,time,timedelta
from decimal import Decimal
import hashlib
import json
import math
from pathlib import Path
import random
import sys

RAIZ=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(RAIZ))
from core.database import conectar
from inventory.tipos_alerta import obtener_tipo_alerta,normalizar_nombre
from tools.generar_registros_sql import literal
from ai.anomalies.deteccion_anomalias import analizar_datos_movimientos
from core.config_manager import cargar_configuracion


def consultar(q,sql):
    q.execute(sql);columnas=[r[0] for r in q.description]
    return [dict(zip(columnas,r)) for r in q.fetchall()]


def preparar():
    c=conectar()
    try:
        q=c.cursor()
        if q.execute("SELECT 1 FROM inventario_migraciones WHERE version='007_normalizacion_historial'").fetchone():
            raise ValueError('La migración 007 ya está aplicada; no se preparó otra carga.')
        ahora=q.execute('SELECT SYSDATETIME()').fetchone()[0]
        productos=consultar(q,'''SELECT p.id_producto,p.codigo,p.nombre,p.unidad_medida,p.stock_minimo,c.nombre categoria,
            e.id_existencia,e.cantidad,e.id_ubicacion,e.posicion,u.codigo_ubicacion,
            b.id_ubicacion ubicacion_anterior,b.fecha_respaldo fecha_reorganizacion
            FROM productos p JOIN categorias c ON c.id_categoria=p.id_categoria
            JOIN existencias e ON e.id_producto=p.id_producto AND e.fecha_eliminacion IS NULL
            JOIN ubicaciones u ON u.id_ubicacion=e.id_ubicacion AND u.estado=1
            JOIN respaldo_existencias_estantes b ON b.id_existencia=e.id_existencia
            WHERE p.estado=1 AND p.fecha_eliminacion IS NULL ORDER BY p.id_producto''')
        empleados=consultar(q,'SELECT id_empleado,nombres,apellidos,cargo FROM empleados WHERE estado=1 AND fecha_eliminacion IS NULL ORDER BY id_empleado')
        tipos={r['nombre']:r['id_tipo_movimiento'] for r in consultar(q,'SELECT id_tipo_movimiento,nombre FROM tipos_movimiento WHERE estado=1 AND fecha_eliminacion IS NULL')}
        ids_alerta={k:obtener_tipo_alerta(k,cursor=q) for k in ('stock_bajo','producto_agotado')}
        cantidad_anterior=q.execute('SELECT COUNT(*) FROM movimientos').fetchone()[0]
    finally:c.close()
    if len(productos)!=24 or len({p['id_producto'] for p in productos})!=24:
        raise ValueError('Se requieren los 24 productos con una asignación física vigente cada uno.')
    altos=[];medios=[];bajos=[]
    for p in productos:
        codigo=p['codigo'];nombre=normalizar_nombre(p['nombre'])
        if codigo.startswith(('LUB-','TOR-')) or codigo.startswith('REP-') and ('filtro' in nombre or 'bujia' in nombre):altos.append(p)
        elif codigo.startswith('REP-'):medios.append(p)
        else:bajos.append(p)
    frecuencias=(list(zip(altos,[27,29,26,30,28,25,32,31,27,34,29,26,28]))+
                 list(zip(medios,[18,17,19,20]))+list(zip(bajos,[8,9,7,10,8,6,6])))
    if (len(altos),len(medios),len(bajos))!=(13,4,7):
        raise ValueError('El catálogo cambió; deben revisarse los perfiles operativos antes de cargar.')
    pesos=[1 if 'supervisor' in normalizar_nombre(e['cargo']) else 5 if any(x in normalizar_nombre(e['cargo']) for x in ('almacen','inventario','auxiliar')) else 2 for e in empleados]
    eventos=[];iniciales=[]
    fecha_inicio=ahora.date()-timedelta(days=105)
    post_ids={altos[0]['id_producto'],altos[8]['id_producto'],altos[9]['id_producto']}
    for indice,(p,total) in enumerate(frecuencias):
        rng=random.Random(int(hashlib.sha256((p['codigo']+'-007').encode()).hexdigest()[:12],16))
        es_alto=p in altos;es_medio=p in medios
        entradas=max(2,math.ceil(total*.28));ajustes=2 if es_alto else 1 if es_medio else 0
        salidas=total-entradas-ajustes
        post=p['id_producto'] in post_ids and ahora-p['fecha_reorganizacion']>=timedelta(hours=4)
        entradas_hist=entradas-int(post);salidas_hist=salidas-int(post)
        fin=min(ahora.date()-timedelta(days=1) if ahora.hour<18 else ahora.date(),p['fecha_reorganizacion'].date())
        dias=[fecha_inicio+timedelta(days=i) for i in range((fin-fecha_inicio).days+1) if (fecha_inicio+timedelta(days=i)).weekday()!=6]
        recientes=[d for d in dias if d>=ahora.date()-timedelta(days=28)]
        anteriores=[d for d in dias if d not in recientes]
        n_recientes=6 if es_alto or es_medio else min(2,salidas_hist)
        fechas=sorted(rng.sample(recientes,n_recientes)+rng.sample(anteriores,salidas_hist-n_recientes))
        nombre=normalizar_nombre(p['nombre'])
        if p['codigo'].startswith('TOR-'):rango=(5,10,12,15,18,20,25,30);extra=100
        elif 'fusible' in nombre:rango=(2,5,8,10,12);extra=40
        elif p['codigo'].startswith('LUB-'):rango=(1,2,3,4,5) if p['unidad_medida']=='Litro' else (1,2,3);extra=18
        elif p['codigo'].startswith('REP-'):rango=(1,2,3,4) if ('filtro' in nombre or 'bujia' in nombre) else (1,2);extra=18
        else:rango=(1,);extra=3
        consumos=[]
        for j,dia in enumerate(fechas):
            hora=time(rng.randint(8,17),rng.randint(0,59),rng.randint(0,59))
            fecha=datetime.combine(dia,hora)
            cantidad=Decimal(extra if es_alto and j==salidas_hist-2 else rng.choice(rango))
            if es_alto and indice<4 and j==salidas_hist-2:
                fecha=datetime.combine(dia,time(19 if dia==p['fecha_reorganizacion'].date() else 21,rng.randint(5,49),rng.randint(0,59)))
            consumos.append(dict(fecha=fecha,tipo='Salida',cantidad=cantidad,observacion=rng.choice(('Salida para mantenimiento preventivo.','Salida para orden de mantenimiento.','Entrega de materiales para reparación de vehículos.'))))
        for j in range(ajustes):
            base=consumos[max(1,len(consumos)//3+j*len(consumos)//3)]['fecha']
            tipo='Ajuste salida' if j==0 else 'Ajuste entrada'
            consumos.append(dict(fecha=base+timedelta(minutes=25+j),tipo=tipo,cantidad=Decimal(1),observacion='Ajuste por diferencia detectada en conteo físico.' if j==0 else 'Sobrante localizado durante revisión de existencias.'))
        consumos.sort(key=lambda r:r['fecha'])
        grupos=[consumos[i*len(consumos)//entradas_hist:(i+1)*len(consumos)//entradas_hist] for i in range(entradas_hist)]
        operaciones=[]
        for grupo in grupos:
            cantidad=sum((x['cantidad'] if x['tipo']!='Ajuste entrada' else -x['cantidad'] for x in grupo),Decimal(0))
            if cantidad<=0:raise ValueError('Reposición no positiva: '+p['codigo'])
            dia=grupo[0]['fecha'].date()-timedelta(days=1)
            if dia.weekday()==6:dia-=timedelta(days=1)
            fecha=datetime.combine(dia,time(rng.randint(7,10),rng.randint(0,59),rng.randint(0,59)))
            operaciones.append(dict(fecha=fecha,tipo='Entrada',cantidad=cantidad,observacion='Entrada por reposición de inventario.'))
            operaciones.extend(grupo)
        if post:
            fecha=p['fecha_reorganizacion']+timedelta(minutes=25+20*indice)
            if fecha+timedelta(minutes=25)>ahora:
                fecha=p['fecha_reorganizacion']+timedelta(minutes=10)
            cantidad=Decimal(rng.choice(rango))
            operaciones.extend([dict(fecha=fecha,tipo='Entrada',cantidad=cantidad,observacion='Recepción de materiales para mantenimiento correctivo.'),dict(fecha=fecha+timedelta(minutes=25),tipo='Salida',cantidad=cantidad,observacion='Salida para orden de mantenimiento correctivo.')])
        saldo=Decimal(p['cantidad']);iniciales.append(dict(id_producto=p['id_producto'],codigo=p['codigo'],stock_inicial=saldo,stock_final=saldo))
        for op in sorted(operaciones,key=lambda r:r['fecha']):
            anterior=saldo;saldo+=op['cantidad'] if op['tipo'] in ('Entrada','Ajuste entrada') else -op['cantidad']
            if saldo<0:raise ValueError('La planificación produciría stock negativo: '+p['codigo'])
            ubicacion=p['id_ubicacion'] if op['fecha']>=p['fecha_reorganizacion'] else p['ubicacion_anterior']
            empleado=rng.choices(empleados,weights=pesos,k=1)[0]
            eventos.append(dict(**op,id_producto=p['id_producto'],codigo=p['codigo'],producto=p['nombre'],id_empleado=empleado['id_empleado'],id_tipo=tipos[op['tipo']],origen=ubicacion if op['tipo'] in ('Salida','Ajuste salida') else None,destino=ubicacion if op['tipo'] in ('Entrada','Ajuste entrada') else None,anterior=anterior,nuevo=saldo))
        if saldo!=p['cantidad'] or len(operaciones)!=total:raise ValueError('No se conserva el saldo o la frecuencia: '+p['codigo'])
        antes=sum((o['cantidad'] if o['tipo'] in ('Entrada','Ajuste entrada') else -o['cantidad'] for o in operaciones if o['fecha']<p['fecha_reorganizacion']),Decimal(0))
        if antes:raise ValueError('El saldo de la reorganización no coincide: '+p['codigo'])
    eventos.sort(key=lambda r:(r['fecha'],r['id_producto']))
    if len(eventos)!=500 or any(r['fecha']>ahora for r in eventos):raise ValueError('Cantidad o fechas fuera de la planificación.')
    datos=[dict(id_detalle=i+1,id_movimiento=i+1,fecha=e['fecha'],id_producto=e['id_producto'],producto=e['producto'],cantidad=e['cantidad'],tipo_movimiento=e['tipo'],id_empleado=e['id_empleado'],origen=e['origen'],destino=e['destino']) for i,e in enumerate(eventos) if e['tipo'] in ('Entrada','Salida') and e['fecha']>=ahora-timedelta(days=90)]
    analisis=analizar_datos_movimientos(datos)
    resumen=dict(fecha_preparacion=ahora,fecha_inicio=min(e['fecha'] for e in eventos),fecha_final=max(e['fecha'] for e in eventos),total=len(eventos),por_tipo=dict(Counter(e['tipo'] for e in eventos)),fuera_horario=sum(e['fecha'].hour<7 or e['fecha'].hour>=18 for e in eventos),hallazgos_calculados=analisis['anomalias_detectadas'],stock_iniciales=iniciales,frecuencias={p['codigo']:n for p,n in frecuencias})
    guardar_sql(eventos,productos,cantidad_anterior,ids_alerta)
    destino=RAIZ/'outputs/validaciones/plan_historial_operativo.json'
    destino.write_text(json.dumps(resumen,ensure_ascii=False,indent=2,default=str),encoding='utf-8')
    print(json.dumps({k:v for k,v in resumen.items() if k not in ('stock_iniciales','frecuencias')},ensure_ascii=False,indent=2,default=str))


def guardar_sql(eventos,productos,cantidad_anterior,ids_alerta):
    plantilla=(RAIZ/'herramientas/plantilla_normalizacion_historial.sql').read_text(encoding='utf-8')
    filas=[]
    for i,e in enumerate(eventos,1):
        filas.append('('+','.join(literal(x) for x in (i,e['id_producto'],e['id_empleado'],e['id_tipo'],e['fecha'],e['cantidad'],e['origen'],e['destino'],e['anterior'],e['nuevo'],e['observacion']))+')')
    modelo=['('+','.join(literal(x) for x in (p['id_producto'],p['id_existencia'],p['id_ubicacion'],p['posicion'],p['cantidad'],p['ubicacion_anterior'],p['fecha_reorganizacion']))+')' for p in productos]
    contenido=plantilla.replace('@@OPERACIONES@@',',\n'.join(filas)).replace('@@MODELO@@',',\n'.join(modelo)).replace('@@CANTIDAD_ANTERIOR@@',str(cantidad_anterior)).replace('@@TIPO_BAJO@@',str(ids_alerta['stock_bajo'])).replace('@@TIPO_AGOTADO@@',str(ids_alerta['producto_agotado']))
    (RAIZ/'sql/normalizar_historial_inventario.sql').write_text(contenido,encoding='utf-8')


if __name__=='__main__':preparar()
