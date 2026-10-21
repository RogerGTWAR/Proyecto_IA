"""Inspección y actualización controlada desde una exportación de SQL Server."""
import argparse
from collections import defaultdict
import hashlib
import json
from pathlib import Path
import re
import sys
from datetime import datetime

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core.database import conectar

TABLAS_ORIGEN = {'categorias', 'ubicaciones', 'productos', 'empleados',
                 'tipos_movimiento', 'movimientos', 'detalle_movimientos',
                 'existencias', 'tipos_alerta', 'alertas', 'rostros_empleados'}
DEPENDIENTES = {'lotes', 'existencias_lotes', 'detalle_movimiento_lotes',
               'conteos_inventario', 'detalle_conteos', 'anomalias_inventario'}


def identificar_archivo(ruta):
    datos = Path(ruta).read_bytes()
    texto = datos.decode('utf-16' if datos.startswith((b'\xff\xfe', b'\xfe\xff')) else 'utf-8-sig')
    registros = defaultdict(list)
    columnas = {}
    for linea in texto.splitlines():
        if not linea.startswith('INSERT '):
            continue
        m = re.fullmatch(r'INSERT \[dbo\]\.\[(\w+)\] \((.*?)\) VALUES \((.*)\)\s*', linea)
        if not m:
            raise ValueError('Formato INSERT no admitido; revisar antes de ejecutar.')
        tabla, campos, valores = m.groups()
        if tabla not in TABLAS_ORIGEN | {'RespaldoStockAntesReparacion'}:
            raise ValueError('Tabla no autorizada: ' + tabla)
        # Solo aceptar literales y CAST de la exportación, no instrucciones SQL.
        resto = re.sub(r"N?'(?:[^']|'')*'", '', valores)
        resto = re.sub(r'\b(?:NULL|CAST|AS|DateTime2|Decimal)\b', '', resto, flags=re.I)
        if re.search(r'[^\s\d.,()+\-]', resto):
            raise ValueError('Expresión no admitida en ' + tabla)
        claves = tuple(re.findall(r'\[(\w+)\]', campos))
        if not claves or campos != ', '.join('[' + c + ']' for c in claves):
            raise ValueError('Lista de columnas no admitida.')
        if tabla in columnas and columnas[tabla] != claves:
            raise ValueError('Columnas inconsistentes en ' + tabla)
        columnas[tabla] = claves
        registros[tabla].append(valores)
    if set(registros) - {'RespaldoStockAntesReparacion'} != TABLAS_ORIGEN:
        raise ValueError('La exportación no contiene todas las tablas necesarias.')
    return registros, columnas, hashlib.sha256(datos).hexdigest()


def cargar_en_memoria_sql(cursor, registros, columnas):
    for tabla, filas in registros.items():
        if tabla == 'RespaldoStockAntesReparacion':
            continue
        campos = ','.join('[' + c + ']' for c in columnas[tabla])
        seleccion = ','.join(f'[{c}]+0 AS [{c}]' if i == 0 else f'[{c}]'
                             for i, c in enumerate(columnas[tabla]))
        cursor.execute(f'SELECT TOP (0) {seleccion} INTO [#{tabla}] FROM dbo.[{tabla}]')
        for valores in filas:
            cursor.execute(f'INSERT INTO [#{tabla}] ({campos}) VALUES ({valores})')


def inspeccionar(cursor, registros, columnas):
    resultado = {}
    for tabla, filas in registros.items():
        if tabla == 'RespaldoStockAntesReparacion':
            continue
        campos = ','.join('[' + c + ']' for c in columnas[tabla])
        pk = columnas[tabla][0]
        actual = cursor.execute(f'SELECT COUNT(*) FROM dbo.[{tabla}]').fetchone()[0]
        distintos = cursor.execute(f'SELECT COUNT(*) FROM (SELECT {campos} FROM [#{tabla}] EXCEPT SELECT {campos} FROM dbo.[{tabla}]) d').fetchone()[0]
        anteriores = cursor.execute(f'SELECT COUNT(*) FROM dbo.[{tabla}] a WHERE NOT EXISTS (SELECT 1 FROM [#{tabla}] n WHERE n.[{pk}]=a.[{pk}])').fetchone()[0]
        resultado[tabla] = dict(actuales=actual,archivo=len(filas),registros_diferentes=distintos,ids_anteriores_fuera_del_archivo=anteriores)
    return resultado


def validar_origen(q, columnas):
    for tabla in TABLAS_ORIGEN:
        pk = columnas[tabla][0]
        if q.execute(f'SELECT COUNT(*) FROM (SELECT [{pk}] FROM [#{tabla}] GROUP BY [{pk}] HAVING COUNT(*)>1) d').fetchone()[0]:
            raise ValueError('Identificador duplicado en ' + tabla)
    for origen, destino, campo, referencia in q.execute('''SELECT OBJECT_NAME(f.parent_object_id),
        OBJECT_NAME(f.referenced_object_id),COL_NAME(f.parent_object_id,c.parent_column_id),
        COL_NAME(f.referenced_object_id,c.referenced_column_id)
        FROM sys.foreign_keys f JOIN sys.foreign_key_columns c ON c.constraint_object_id=f.object_id''').fetchall():
        if origen in TABLAS_ORIGEN and destino in TABLAS_ORIGEN and campo in columnas[origen]:
            if q.execute(f'SELECT COUNT(*) FROM [#{origen}] o WHERE o.[{campo}] IS NOT NULL AND NOT EXISTS '
                         f'(SELECT 1 FROM [#{destino}] d WHERE d.[{referencia}]=o.[{campo}])').fetchone()[0]:
                raise ValueError('Referencia inexistente: ' + origen + '.' + campo)
    if q.execute('SELECT COUNT(*) FROM #existencias WHERE cantidad<0').fetchone()[0]:
        raise ValueError('Existencias negativas en el archivo.')
    if q.execute('SELECT COUNT(*) FROM #movimientos WHERE fecha_movimiento>SYSDATETIME()').fetchone()[0]:
        raise ValueError('Movimientos futuros en el archivo.')
    saldos = {}
    aperturas = {}
    for r in q.execute('''SELECT d.id_detalle,d.id_producto,d.cantidad,d.id_ubicacion_origen,
        d.id_ubicacion_destino,d.stock_anterior,d.stock_nuevo,t.nombre
        FROM #detalle_movimientos d JOIN #movimientos m ON m.id_movimiento=d.id_movimiento
        JOIN #tipos_movimiento t ON t.id_tipo_movimiento=m.id_tipo_movimiento
        ORDER BY m.fecha_movimiento,m.id_movimiento,d.id_detalle''').fetchall():
        ident, producto, cantidad, origen, destino, anterior, nuevo, tipo = r
        clave = (producto, origen or destino)
        if cantidad <= 0 or clave[1] is None or anterior is None or nuevo is None:
            raise ValueError('Movimiento incompleto: ' + str(ident))
        if clave not in saldos:
            saldos[clave] = anterior
            aperturas[clave] = anterior
        if saldos[clave] != anterior:
            raise ValueError('Cadena de stock inconsistente: ' + str(ident))
        if tipo in ('Salida', 'Ajuste salida', 'Transferencia'):
            if origen is None:
                raise ValueError('Falta origen: ' + str(ident))
            saldos[producto, origen] -= cantidad
        if tipo in ('Entrada', 'Ajuste entrada', 'Transferencia'):
            if destino is None:
                raise ValueError('Falta destino: ' + str(ident))
            if (producto, destino) not in saldos:
                raise ValueError('Transferencia sin saldo inicial verificable: ' + str(ident))
            saldos[producto, destino] += cantidad
        if tipo not in ('Entrada', 'Salida', 'Transferencia', 'Ajuste entrada', 'Ajuste salida'):
            raise ValueError('Tipo no admitido: ' + tipo)
        if any(v < 0 for v in saldos.values()) or saldos[clave] != nuevo:
            raise ValueError('Saldo posterior inconsistente: ' + str(ident))
    finales = {(r[0], r[1]):r[2] for r in q.execute('SELECT id_producto,id_ubicacion,cantidad FROM #existencias')}
    for clave, saldo in saldos.items():
        if finales.get(clave) != saldo:
            raise ValueError('Existencias distintas del historial: ' + str(clave))
    return {'saldos_iniciales_del_historial': [dict(producto=p,ubicacion=u,cantidad=v)
                                             for (p,u),v in aperturas.items() if v != 0]}


def respaldar(c):
    c.rollback()
    c.autocommit = True
    q = c.cursor()
    directorio = q.execute("SELECT CAST(SERVERPROPERTY('InstanceDefaultBackupPath') AS nvarchar(4000))").fetchone()[0]
    if not directorio:
        raise ValueError('No se pudo identificar la carpeta de respaldo del servidor.')
    destino = directorio.rstrip('\\/') + '\\InventarioIA2_antes_actualizacion_' + datetime.now().strftime('%Y%m%d_%H%M%S') + '.bak'
    q.execute('BACKUP DATABASE [InventarioIA2] TO DISK = ? WITH COPY_ONLY,CHECKSUM', destino)
    while q.nextset():
        pass
    q.execute('RESTORE VERIFYONLY FROM DISK = ? WITH CHECKSUM', destino)
    while q.nextset():
        pass
    c.autocommit = False
    return destino


def reemplazar(c, registros, columnas):
    q = c.cursor()
    q.execute('SET XACT_ABORT ON; SET LOCK_TIMEOUT 15000')
    cargar_en_memoria_sql(q, registros, columnas)
    validacion = validar_origen(q, columnas)
    tablas = TABLAS_ORIGEN | DEPENDIENTES
    existentes = {r[0] for r in q.execute("SELECT name FROM sys.tables WHERE schema_id=SCHEMA_ID('dbo')")}
    tablas &= existentes
    dependencias = {t:set() for t in tablas}
    for hijo, padre in q.execute('SELECT OBJECT_NAME(parent_object_id),OBJECT_NAME(referenced_object_id) FROM sys.foreign_keys').fetchall():
        if padre in tablas and hijo not in tablas:
            raise ValueError('Dependencia externa no incluida: ' + hijo)
        if hijo in tablas and padre in tablas:
            dependencias[hijo].add(padre)
    orden = []
    pendientes = set(tablas)
    while pendientes:
        disponibles = sorted(t for t in pendientes if not (dependencias[t] & pendientes))
        if not disponibles:
            raise ValueError('Relaciones circulares; no se modificó la base.')
        orden.extend(disponibles)
        pendientes.difference_update(disponibles)
    for tabla in sorted(tablas):
        q.execute(f'SELECT COUNT(*) FROM dbo.[{tabla}] WITH(TABLOCKX,HOLDLOCK)').fetchone()
    unidades = [r[0] for r in q.execute('SELECT DISTINCT unidad_medida FROM #productos').fetchall()]
    for nombre in unidades:
        if not q.execute('SELECT 1 FROM unidades_medida WHERE nombre=? AND activo=1', nombre).fetchone():
            if q.execute('SELECT 1 FROM unidades_medida WHERE nombre=?', nombre).fetchone():
                raise ValueError('La unidad existe pero está inactiva: ' + nombre)
            q.execute('INSERT dbo.unidades_medida(nombre,abreviatura) VALUES(?,?)', nombre, nombre)
    for tabla in reversed(orden):
        q.execute(f'DELETE FROM dbo.[{tabla}]')
    for tabla in orden:
        if tabla not in TABLAS_ORIGEN:
            continue
        campos = ','.join('['+k+']' for k in columnas[tabla])
        seleccion = ','.join('s.['+k+']' for k in columnas[tabla])
        complemento = ''
        if tabla == 'productos':
            campos += ',[id_unidad_medida]'
            seleccion += ',u.id_unidad'
            complemento = ' JOIN dbo.unidades_medida u ON u.nombre=s.unidad_medida AND u.activo=1'
        elif tabla == 'ubicaciones':
            campos += ',[zona]'
            seleccion += ',s.seccion'
        identidad = q.execute('SELECT COUNT(*) FROM sys.identity_columns WHERE object_id=OBJECT_ID(?)', 'dbo.'+tabla).fetchone()[0]
        if identidad:
            q.execute(f'SET IDENTITY_INSERT dbo.[{tabla}] ON')
        try:
            q.execute(f'INSERT dbo.[{tabla}] ({campos}) SELECT {seleccion} FROM [#{tabla}] s'+complemento)
        finally:
            if identidad:
                q.execute(f'SET IDENTITY_INSERT dbo.[{tabla}] OFF')
    comparacion = inspeccionar(q, registros, columnas)
    if any(r['actuales']!=r['archivo'] or r['registros_diferentes'] or r['ids_anteriores_fuera_del_archivo'] for r in comparacion.values()):
        raise ValueError('La verificación de los registros importados no coincide.')
    q.execute('DBCC CHECKCONSTRAINTS WITH ALL_CONSTRAINTS')
    if q.description and q.fetchall():
        raise ValueError('Se detectaron restricciones incumplidas.')
    return comparacion, validacion


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('archivo')
    parser.add_argument('--aplicar', action='store_true', help='Respaldar y reemplazar los registros por los del archivo.')
    args = parser.parse_args()
    registros, columnas, firma = identificar_archivo(args.archivo)
    c = conectar()
    try:
        q = c.cursor()
        cargar_en_memoria_sql(q, registros, columnas)
        validacion = validar_origen(q, columnas)
        resultado = inspeccionar(q, registros, columnas)
        print(json.dumps({'sha256':firma,'comparacion':resultado},ensure_ascii=False,indent=2))
        print('Saldos iniciales registrados:', len(validacion['saldos_iniciales_del_historial']))
        if args.aplicar:
            if q.execute("SELECT 1 FROM dbo.inventario_migraciones WHERE version='006_organizacion_fisica'").fetchone():
                raise ValueError('La organización física ya está aplicada. Esta exportación anterior no incluye posiciones; utilice los registros vigentes del proyecto para conservarla.')
            respaldo = respaldar(c)
            resultado, validacion = reemplazar(c, registros, columnas)
            informe = dict(archivo=str(Path(args.archivo).resolve()),sha256=firma,respaldo_sql=respaldo,
                           fecha=datetime.now().isoformat(),comparacion=resultado,**validacion)
            destino = Path('outputs/validaciones/actualizacion_desde_sql.json')
            destino.parent.mkdir(parents=True,exist_ok=True)
            informe['resultado'] = 'VALIDADO_ANTES_DE_COMMIT'
            destino.write_text(json.dumps(informe,ensure_ascii=False,indent=2,default=str),encoding='utf-8')
            c.commit()
            informe['resultado'] = 'APLICADO'
            destino.write_text(json.dumps(informe,ensure_ascii=False,indent=2,default=str),encoding='utf-8')
            print('Actualización aplicada. Respaldo:', respaldo)
            print(json.dumps(resultado,ensure_ascii=False,indent=2))
            return
        print('DEPENDENCIAS:')
        for fila in q.execute('''SELECT OBJECT_NAME(parent_object_id),OBJECT_NAME(referenced_object_id),name
                                 FROM sys.foreign_keys ORDER BY 1,2'''):
            print(tuple(fila))
        print('COLUMNAS ADICIONALES:')
        for tabla in resultado:
            adicionales = [tuple(f) for f in q.execute('''SELECT name,TYPE_NAME(user_type_id),is_nullable,
                              OBJECT_DEFINITION(default_object_id) FROM sys.columns WHERE object_id=OBJECT_ID(?)''', 'dbo.'+tabla)
                           if f[0] not in columnas[tabla]]
            if adicionales:
                print(tabla, adicionales)
        print('EXTENSIONES:')
        for tabla in ['lotes','existencias_lotes','detalle_movimiento_lotes','conteos_inventario','detalle_conteos','anomalias_inventario']:
            if q.execute("SELECT OBJECT_ID(?, 'U')", 'dbo.'+tabla).fetchone()[0]:
                print(tabla, q.execute(f'SELECT COUNT(*) FROM dbo.[{tabla}]').fetchone()[0])
        print('TIPOS DEL ARCHIVO:', [tuple(f) for f in q.execute('SELECT id_tipo_movimiento,nombre FROM #tipos_movimiento')])
        print('SALDOS DEL ARCHIVO:', tuple(q.execute('SELECT SUM(cantidad),MIN(cantidad) FROM #existencias').fetchone()))
        print('FECHAS DEL ARCHIVO:', tuple(q.execute('SELECT MIN(fecha_movimiento),MAX(fecha_movimiento) FROM #movimientos').fetchone()))
        print('NOMBRES FACIALES QUE CAMBIAN:', [tuple(f) for f in q.execute('''SELECT n.etiqueta_modelo,
            CONCAT(e.nombres,' ',e.apellidos),CONCAT(ne.nombres,' ',ne.apellidos)
            FROM #rostros_empleados n JOIN #empleados ne ON ne.id_empleado=n.id_empleado
            JOIN dbo.rostros_empleados r ON r.etiqueta_modelo=n.etiqueta_modelo
            JOIN dbo.empleados e ON e.id_empleado=r.id_empleado
            WHERE e.nombres<>ne.nombres OR e.apellidos<>ne.apellidos''')])
        print('ESTANTES:', [tuple(f) for f in q.execute('SELECT * FROM #ubicaciones')])
        print('UNIDADES:', [tuple(f) for f in q.execute('SELECT * FROM dbo.unidades_medida')])
        print('STOCK FINAL DISTINTO DEL ULTIMO MOVIMIENTO:', [tuple(f) for f in q.execute('''WITH ultimos AS (
            SELECT d.id_producto,d.stock_nuevo,ROW_NUMBER() OVER(PARTITION BY d.id_producto
            ORDER BY m.fecha_movimiento DESC,m.id_movimiento DESC,d.id_detalle DESC) n
            FROM #detalle_movimientos d JOIN #movimientos m ON m.id_movimiento=d.id_movimiento)
            SELECT p.codigo,SUM(e.cantidad),u.stock_nuevo FROM #productos p
            JOIN #existencias e ON e.id_producto=p.id_producto JOIN ultimos u ON u.id_producto=p.id_producto AND u.n=1
            GROUP BY p.codigo,u.stock_nuevo HAVING SUM(e.cantidad)<>u.stock_nuevo''')])
    finally:
        c.rollback()
        c.close()


if __name__ == '__main__':
    main()
