import json
import re
from pathlib import Path

from database import conectar

RUTA_ETIQUETAS = Path(__file__).resolve().parent / "modelos" / "etiquetas_rostros.json"
RUTA_CONFIGURACION = Path(__file__).resolve().parent / "configurar_reconocimiento_facial.sql"
RUTA_MIGRACION = Path(__file__).resolve().parent / "migrar_auditoria_soft_delete.sql"


def configurar_reconocimiento_facial():
    """Aplica de forma transaccional e idempotente la configuración SQL facial."""
    conexion = conectar(); cursor = conexion.cursor()
    try:
        cursor.execute(RUTA_MIGRACION.read_text(encoding="utf-8"))
        while cursor.nextset():
            pass
        cursor.execute(RUTA_CONFIGURACION.read_text(encoding="utf-8"))
        while cursor.nextset():
            pass
        conexion.commit()
        return True
    except Exception:
        conexion.rollback(); raise
    finally:
        cursor.close(); conexion.close()


def _diccionario(cursor, fila):
    return None if fila is None else dict(zip((c[0] for c in cursor.description), fila))


def listar_relaciones():
    conexion = conectar(); cursor = conexion.cursor()
    try:
        cursor.execute("""
            SELECT re.id_rostro, e.id_empleado, e.codigo_empleado,
                   CONCAT(e.nombres, ' ', e.apellidos) AS nombre, e.cargo,
                   re.etiqueta_modelo, re.estado AS relacion_activa,
                   e.estado AS empleado_activo
            FROM empleados e
            LEFT JOIN rostros_empleados re ON e.id_empleado=re.id_empleado
                                             AND re.fecha_eliminacion IS NULL
            WHERE e.fecha_eliminacion IS NULL AND e.estado=1
            ORDER BY e.codigo_empleado;
        """)
        columnas = [c[0] for c in cursor.description]
        return [dict(zip(columnas, fila)) for fila in cursor.fetchall()]
    finally:
        cursor.close(); conexion.close()


def obtener_empleado_por_etiqueta(etiqueta):
    conexion = conectar(); cursor = conexion.cursor()
    try:
        cursor.execute("""
            SELECT e.id_empleado, e.codigo_empleado,
                   CONCAT(e.nombres, ' ', e.apellidos) AS nombre, e.cargo,
                   e.estado AS empleado_activo, re.etiqueta_modelo
            FROM rostros_empleados re
            JOIN empleados e ON e.id_empleado=re.id_empleado
            WHERE re.etiqueta_modelo=? AND re.estado=1
              AND re.fecha_eliminacion IS NULL AND e.estado=1
              AND e.fecha_eliminacion IS NULL;
        """, etiqueta)
        return _diccionario(cursor, cursor.fetchone())
    finally:
        cursor.close(); conexion.close()


def listar_etiquetas_disponibles(incluir_asignadas=False):
    if not RUTA_ETIQUETAS.is_file():
        return []
    datos = json.loads(RUTA_ETIQUETAS.read_text(encoding="utf-8"))
    etiquetas = sorted(str(valor) for valor in datos.values())
    if incluir_asignadas:
        return etiquetas
    asignadas = {r["etiqueta_modelo"] for r in listar_relaciones() if r["etiqueta_modelo"]}
    return [e for e in etiquetas if e not in asignadas]


def asignar_etiqueta_empleado(id_empleado, etiqueta):
    etiqueta = str(etiqueta).strip().lower()
    if not re.fullmatch(r"subject\d+", etiqueta):
        raise ValueError("La etiqueta debe usar el formato subjectXX.")
    conexion = conectar(); cursor = conexion.cursor()
    try:
        cursor.execute("SELECT id_empleado FROM empleados WHERE id_empleado=? AND estado=1 AND fecha_eliminacion IS NULL;", id_empleado)
        if cursor.fetchone() is None:
            raise ValueError("El empleado no existe.")
        cursor.execute("SELECT id_empleado FROM rostros_empleados WHERE etiqueta_modelo=? AND fecha_eliminacion IS NULL;", etiqueta)
        por_etiqueta = cursor.fetchone()
        if por_etiqueta is not None and por_etiqueta.id_empleado != int(id_empleado):
            raise ValueError("La etiqueta ya está relacionada con otro empleado.")
        cursor.execute("SELECT etiqueta_modelo FROM rostros_empleados WHERE id_empleado=? AND fecha_eliminacion IS NULL;", id_empleado)
        por_empleado = cursor.fetchone()
        if por_empleado is not None and por_empleado.etiqueta_modelo != etiqueta:
            raise ValueError("El empleado ya tiene otra etiqueta facial.")
        if por_etiqueta is None:
            cursor.execute("""SELECT id_rostro,id_empleado,etiqueta_modelo FROM rostros_empleados
                              WHERE etiqueta_modelo=? OR id_empleado=?;""", etiqueta, id_empleado)
            anteriores=cursor.fetchall()
            if anteriores:
                if len(anteriores)!=1 or anteriores[0].id_empleado!=int(id_empleado) or anteriores[0].etiqueta_modelo!=etiqueta:
                    raise ValueError("Existe una relación histórica incompatible con esa etiqueta o empleado.")
                cursor.execute("""UPDATE rostros_empleados SET estado=1,fecha_eliminacion=NULL,
                                  fecha_actualizacion=SYSDATETIME() WHERE id_rostro=?;""", anteriores[0].id_rostro)
            else:
                cursor.execute("INSERT INTO rostros_empleados(id_empleado,etiqueta_modelo,estado,fecha_creacion) VALUES(?,?,1,SYSDATETIME());", id_empleado, etiqueta)
        else:
            cursor.execute("""UPDATE rostros_empleados SET estado=1,fecha_actualizacion=SYSDATETIME()
                              WHERE etiqueta_modelo=? AND fecha_eliminacion IS NULL;""", etiqueta)
        conexion.commit()
    except Exception:
        conexion.rollback(); raise
    finally:
        cursor.close(); conexion.close()
    return obtener_empleado_por_etiqueta(etiqueta)


def eliminar_relacion(id_rostro):
    conexion = conectar(); cursor = conexion.cursor()
    try:
        cursor.execute("""UPDATE rostros_empleados SET estado=0,fecha_actualizacion=SYSDATETIME(),
                          fecha_eliminacion=SYSDATETIME()
                          WHERE id_rostro=? AND fecha_eliminacion IS NULL;""", id_rostro)
        if cursor.rowcount == 0:
            raise ValueError("La relación facial no existe.")
        conexion.commit(); return True
    except Exception:
        conexion.rollback(); raise
    finally:
        cursor.close(); conexion.close()


def obtener_subjects_activos():
    conexion=conectar(); cursor=conexion.cursor()
    try:
        cursor.execute("""SELECT re.etiqueta_modelo FROM rostros_empleados re
                          JOIN empleados e ON e.id_empleado=re.id_empleado
                          WHERE re.fecha_eliminacion IS NULL AND re.estado=1
                            AND e.fecha_eliminacion IS NULL AND e.estado=1
                          ORDER BY re.etiqueta_modelo;""")
        return [fila.etiqueta_modelo for fila in cursor.fetchall()]
    finally: cursor.close(); conexion.close()


def actualizar_relacion(id_rostro, id_empleado, etiqueta):
    etiqueta=str(etiqueta).strip().lower()
    conexion=conectar(); cursor=conexion.cursor()
    try:
        cursor.execute("""UPDATE rostros_empleados SET id_empleado=?,etiqueta_modelo=?,
                          fecha_actualizacion=SYSDATETIME()
                          WHERE id_rostro=? AND fecha_eliminacion IS NULL;""", id_empleado, etiqueta, id_rostro)
        if cursor.rowcount==0: raise ValueError("La relación no existe o fue eliminada.")
        conexion.commit(); return True
    except Exception: conexion.rollback(); raise
    finally: cursor.close(); conexion.close()
