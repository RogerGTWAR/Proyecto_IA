"""Ejecuta la retirada solicitada y comprueba que el inventario no cambie."""
from pathlib import Path
import sys
RAIZ=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(RAIZ))
from core.database import conectar

INVENTARIO=("categorias","ubicaciones","empleados","productos","existencias",
            "tipos_movimiento","movimientos","detalle_movimientos","tipos_alerta",
            "alertas","rostros_empleados")
RETIRADAS=("recursos_interfaz","usuario_rol","rol_permiso","auditoria_aplicacion",
           "usuarios_aplicacion","roles","permisos","seguridad_migraciones")

def ejecutar():
    c=conectar()
    try:
        q=c.cursor()
        antes={t:q.execute("SELECT COUNT_BIG(*) FROM dbo."+t).fetchone()[0]
               for t in INVENTARIO}
        sql=RAIZ.joinpath("migrations").joinpath(
            "003_retirar_acceso_auditoria.sql").read_text(encoding="utf-8")
        q.execute(sql)
        while q.nextset():
            pass
        despues={t:q.execute("SELECT COUNT_BIG(*) FROM dbo."+t).fetchone()[0]
                 for t in INVENTARIO}
        assert antes==despues,"Cambió el recuento del inventario."
        for t in RETIRADAS:
            assert q.execute("SELECT OBJECT_ID(?)","dbo."+t).fetchone()[0] is None,t
        c.commit()
        print("Retiradas las 8 tablas de acceso y auditoría.")
        print("Conservadas las 11 tablas del inventario, con los mismos recuentos:",despues)
    except Exception:
        c.rollback()
        raise
    finally:
        c.close()

if __name__=="__main__":
    ejecutar()
