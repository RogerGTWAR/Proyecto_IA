"""Exportar registros del inventario como INSERT de SQL Server."""

import sys
from pathlib import Path as _RutaProyecto
_RAIZ_PROYECTO = _RutaProyecto(__file__).resolve().parents[1]
if str(_RAIZ_PROYECTO) not in sys.path:
    sys.path.insert(0, str(_RAIZ_PROYECTO))

from datetime import date, datetime, time
from decimal import Decimal
from pathlib import Path
import json
from core.database import conectar


TABLAS = ['categorias', 'unidades_medida', 'ubicaciones', 'empleados',
          'tipos_movimiento', 'motivos_movimiento', 'productos', 'lotes',
          'movimientos', 'detalle_movimientos', 'detalle_movimiento_lotes',
          'existencias', 'existencias_lotes', 'tipos_alerta', 'alertas', 'rostros_empleados']


def identificador(valor):
    return '[' + valor.replace(']', ']]') + ']'


def literal(valor):
    if valor is None:
        return 'NULL'
    if isinstance(valor, bool):
        return '1' if valor else '0'
    if isinstance(valor, (int, Decimal)):
        return str(valor)
    if isinstance(valor, float):
        raise ValueError('Se requiere revisar la representación de columnas flotantes.')
    if isinstance(valor, (datetime, date, time)):
        valor = valor.isoformat()
    if isinstance(valor, bytes):
        return '0x' + valor.hex()
    return "N'" + str(valor).replace("'", "''") + "'"


def generar():
    conexion = conectar()
    try:
        q = conexion.cursor()
        q.execute('SET TRANSACTION ISOLATION LEVEL SERIALIZABLE')
        metadatos = {}
        registros = {}
        for tabla in TABLAS:
            columnas = q.execute('''SELECT c.name, c.is_identity, c.is_computed, ty.name
                FROM sys.columns c JOIN sys.types ty ON ty.user_type_id=c.user_type_id
                WHERE c.object_id=OBJECT_ID(?) ORDER BY c.column_id''', 'dbo.' + tabla).fetchall()
            if not columnas:
                raise ValueError('No existe la tabla: ' + tabla)
            columnas = [r for r in columnas if not r.is_computed and r[3] not in ('timestamp', 'rowversion')]
            pk = [r[0] for r in q.execute('''SELECT c.name FROM sys.indexes i
                JOIN sys.index_columns ic ON ic.object_id=i.object_id AND ic.index_id=i.index_id
                JOIN sys.columns c ON c.object_id=ic.object_id AND c.column_id=ic.column_id
                WHERE i.object_id=OBJECT_ID(?) AND i.is_primary_key=1 ORDER BY ic.key_ordinal''', 'dbo.' + tabla).fetchall()]
            if not pk:
                raise ValueError('Falta clave primaria: ' + tabla)
            nombres = [r[0] for r in columnas]
            metadatos[tabla] = (nombres, pk, any(r[1] for r in columnas))
            seleccion = [
                'CONVERT(nvarchar(40),'+identificador(r[0])+',126)'
                if r[3] in ('datetime2', 'datetime', 'smalldatetime', 'date', 'time', 'datetimeoffset')
                else identificador(r[0]) for r in columnas]
            registros[tabla] = [tuple(r) for r in q.execute(
                'SELECT ' + ','.join(seleccion) + ' FROM dbo.' + identificador(tabla) +
                ' ORDER BY ' + ','.join(map(identificador, pk))).fetchall()]
        conexion.rollback()
    finally:
        conexion.close()

    sql = [
        '-- Registros del almacén obtenidos de InventarioIA2.',
        '-- Ejecutar el archivo completo en SQL Server Management Studio.',
        '-- Requiere las tablas y columnas actuales del proyecto.',
        '-- Conserva los identificadores para mantener las relaciones del historial.',
        '-- Los registros existentes idénticos se omiten; cualquier diferencia cancela la carga.',
        '-- Los saldos son los finales del historial: no se suman otra vez.',
        '-- Incluye las relaciones faciales registradas, sin imágenes ni embeddings.',
        '-- No inserta resultados calculados de predicción o anomalías.',
        'USE [InventarioIA2];',
        'SET NOCOUNT ON;', 'SET XACT_ABORT ON;',
        'SET TRANSACTION ISOLATION LEVEL SERIALIZABLE;',
        'DECLARE @insertados int=0, @bloqueo int;',
        'BEGIN TRY', '    BEGIN TRANSACTION;',
        "    EXEC @bloqueo=sys.sp_getapplock @Resource=N'InventarioIA_carga_catalogo_202610', @LockMode='Exclusive', @LockOwner='Transaction', @LockTimeout=10000;",
        "    IF @bloqueo<0 THROW 51000,N'No se pudo bloquear la carga.',1;",
    ]
    tablas_sql = ','.join(literal(t) for t in TABLAS)
    sql += [
        '    IF EXISTS (SELECT 1 FROM sys.triggers tr JOIN sys.tables t ON t.object_id=tr.parent_id',
        '        WHERE tr.is_disabled=0 AND tr.name<>N\'TR_existencias_capacidad_fisica\' AND t.schema_id=SCHEMA_ID(N\'dbo\') AND t.name IN ('+tablas_sql+'))',
        "        THROW 51000,N'Existen desencadenadores activos: revise su efecto sobre stock antes de cargar.',1;",
    ]
    for tabla in TABLAS:
        nombres, pk, identidad = metadatos[tabla]
        nombre = 'dbo.' + identificador(tabla)
        columnas_sql = ', '.join(map(identificador, nombres))
        sql += ['', '-- ' + tabla + ': ' + str(len(registros[tabla])) + ' registros.',
                "    IF OBJECT_ID(N'dbo."+tabla+"',N'U') IS NULL THROW 51000,N'Falta la tabla "+tabla+".',1;"]
        if identidad:
            sql.append('    SET IDENTITY_INSERT ' + nombre + ' ON;')
        for fila in registros[tabla]:
            valores = ', '.join(map(literal, fila))
            condicion = ' AND '.join(identificador(c)+'='+literal(fila[nombres.index(c)]) for c in pk)
            sql += [
                '    IF NOT EXISTS (SELECT 1 FROM '+nombre+' WITH (UPDLOCK,HOLDLOCK) WHERE '+condicion+')',
                '    BEGIN',
                '        INSERT INTO '+nombre+' ('+columnas_sql+')',
                '        VALUES ('+valores+');',
                '        SET @insertados+=1;', '    END',
                '    ELSE IF EXISTS (SELECT '+columnas_sql+' FROM '+nombre+' WHERE '+condicion,
                '        EXCEPT SELECT '+valores+')',
                "        THROW 51000,N'El registro existente difiere en "+tabla+": "+','.join(str(fila[nombres.index(c)]) for c in pk).replace("'","''")+". No se sobrescribió.',1;",
            ]
        if identidad:
            sql.append('    SET IDENTITY_INSERT ' + nombre + ' OFF;')
    sql += [
        '', '    COMMIT TRANSACTION;',
        "    SELECT @insertados AS registros_agregados, N'Carga completada' AS resultado;",
        'END TRY', 'BEGIN CATCH',
        '    IF XACT_STATE()<>0 ROLLBACK TRANSACTION;',
    ]
    for tabla in TABLAS:
        if metadatos[tabla][2]:
            sql.append('    SET IDENTITY_INSERT dbo.'+identificador(tabla)+' OFF;')
    sql += ['    THROW;', 'END CATCH;', '']
    destino = Path(__file__).resolve().parents[1] / 'sql' / 'registros_inventario.sql'
    destino.write_text('\n'.join(sql), encoding='utf-8-sig')
    print(json.dumps({'archivo': str(destino), 'registros': {t:len(r) for t,r in registros.items()},
                      'total':sum(map(len, registros.values()))}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    generar()
