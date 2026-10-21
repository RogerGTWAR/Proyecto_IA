from core.database import conectar
c=conectar()
try:
    q=c.cursor()
    print('productos_stock=',q.execute('SELECT COUNT(*),SUM(stock_actual) FROM vw_inventario').fetchone())
    print('movimientos=',q.execute('SELECT COUNT(*) FROM movimientos WHERE fecha_eliminacion IS NULL').fetchone()[0])
    print('anomalias=',q.execute('SELECT COUNT(*) FROM anomalias_inventario').fetchone()[0])
    print('niveles_alerta=',[r[0] for r in q.execute('SELECT DISTINCT nivel FROM alertas WHERE fecha_eliminacion IS NULL')])
    print('tablas_acceso=',q.execute("SELECT COUNT(*) FROM sys.tables WHERE name IN ('usuarios_aplicacion','roles','permisos','usuario_rol','rol_permiso','auditoria_aplicacion','recursos_interfaz','seguridad_migraciones')").fetchone()[0])
finally:
    c.close()
