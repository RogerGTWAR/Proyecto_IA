-- Diagnóstico de coherencia, consumo y estructura física. No modifica datos.
USE [InventarioIA2];
SET NOCOUNT ON;
DROP TABLE IF EXISTS #historial,#control,#errores_secuencia,#errores_stock,#errores_ubicacion,#errores_empleado;
SELECT d.*,m.fecha_movimiento,t.nombre tipo,m.id_empleado
INTO #historial FROM dbo.detalle_movimientos d JOIN dbo.movimientos m ON m.id_movimiento=d.id_movimiento
JOIN dbo.tipos_movimiento t ON t.id_tipo_movimiento=m.id_tipo_movimiento
WHERE d.fecha_eliminacion IS NULL AND m.fecha_eliminacion IS NULL;

WITH inicial AS(
 SELECT id_producto,stock_anterior,ROW_NUMBER() OVER(PARTITION BY id_producto ORDER BY fecha_movimiento,id_movimiento,id_detalle) n FROM #historial),
 totales AS(
 SELECT id_producto,SUM(CASE WHEN tipo='Entrada' THEN cantidad ELSE 0 END) entradas,
 SUM(CASE WHEN tipo='Salida' THEN cantidad ELSE 0 END) salidas,
 SUM(CASE WHEN tipo='Ajuste entrada' THEN cantidad ELSE 0 END) ajustes_entrada,
 SUM(CASE WHEN tipo='Ajuste salida' THEN cantidad ELSE 0 END) ajustes_salida FROM #historial GROUP BY id_producto),
 actual AS(SELECT id_producto,SUM(cantidad) stock FROM dbo.existencias WHERE fecha_eliminacion IS NULL GROUP BY id_producto)
SELECT p.id_producto,p.codigo,p.nombre producto,i.stock_anterior stock_inicial,
 t.entradas,t.salidas,t.ajustes_entrada,t.ajustes_salida,
 i.stock_anterior+t.entradas+t.ajustes_entrada-t.salidas-t.ajustes_salida stock_calculado,
 a.stock stock_actual,
 CASE WHEN i.stock_anterior+t.entradas+t.ajustes_entrada-t.salidas-t.ajustes_salida=a.stock THEN N'COINCIDE' ELSE N'REVISAR' END resultado
INTO #control FROM productos p JOIN inicial i ON i.id_producto=p.id_producto AND i.n=1
JOIN totales t ON t.id_producto=p.id_producto JOIN actual a ON a.id_producto=p.id_producto;
SELECT * FROM #control ORDER BY id_producto;

SELECT * INTO #errores_secuencia FROM(
 SELECT id_producto,id_movimiento,stock_anterior,LAG(stock_nuevo) OVER(PARTITION BY id_producto ORDER BY fecha_movimiento,id_movimiento,id_detalle) stock_previo
 FROM #historial)s WHERE stock_previo IS NOT NULL AND stock_previo<>stock_anterior;
SELECT * FROM #errores_secuencia;

SELECT * INTO #errores_stock FROM #historial WHERE
 (tipo IN('Entrada','Ajuste entrada') AND stock_nuevo<>stock_anterior+cantidad) OR
 (tipo IN('Salida','Ajuste salida','Transferencia') AND stock_nuevo<>stock_anterior-cantidad) OR
 cantidad<=0 OR stock_anterior<0 OR stock_nuevo<0;
SELECT * FROM #errores_stock;

SELECT h.* INTO #errores_ubicacion FROM #historial h
LEFT JOIN dbo.respaldo_existencias_estantes b ON b.id_producto=h.id_producto AND b.fecha_eliminacion IS NULL
WHERE (h.tipo IN('Entrada','Ajuste entrada') AND (h.id_ubicacion_origen IS NOT NULL OR h.id_ubicacion_destino IS NULL)) OR
 (h.tipo IN('Salida','Ajuste salida') AND (h.id_ubicacion_origen IS NULL OR h.id_ubicacion_destino IS NOT NULL)) OR
 (h.tipo='Transferencia' AND (h.id_ubicacion_origen IS NULL OR h.id_ubicacion_destino IS NULL OR h.id_ubicacion_origen=h.id_ubicacion_destino)) OR
 (h.fecha_movimiento>=b.fecha_respaldo AND EXISTS(SELECT 1 FROM ubicaciones u WHERE u.estado=0 AND u.id_ubicacion IN(h.id_ubicacion_origen,h.id_ubicacion_destino)));
SELECT * FROM #errores_ubicacion;

SELECT h.* INTO #errores_empleado FROM #historial h LEFT JOIN empleados e ON e.id_empleado=h.id_empleado
WHERE e.id_empleado IS NULL OR e.estado=0 OR e.fecha_eliminacion IS NOT NULL;
SELECT * FROM #errores_empleado;

SELECT
 (SELECT COUNT(*) FROM productos WHERE estado=1 AND fecha_eliminacion IS NULL) productos_activos,
 (SELECT COUNT(*) FROM ubicaciones WHERE estado=1 AND fecha_eliminacion IS NULL) ubicaciones_activas,
 (SELECT COUNT(*) FROM vw_inventario_ubicaciones) posiciones_ocupadas,
 (SELECT COUNT(*) FROM productos p WHERE p.estado=1 AND p.fecha_eliminacion IS NULL AND NOT EXISTS(
   SELECT 1 FROM existencias e JOIN ubicaciones u ON u.id_ubicacion=e.id_ubicacion
   WHERE e.id_producto=p.id_producto AND e.fecha_eliminacion IS NULL AND u.estado=1)) productos_sin_ubicacion,
 (SELECT COUNT(*) FROM #control WHERE resultado<>N'COINCIDE') productos_stock_incoherente,
 (SELECT COUNT(*) FROM #errores_stock)+(SELECT COUNT(*) FROM #errores_secuencia) movimientos_stock_incorrecto,
 (SELECT COUNT(*) FROM #errores_ubicacion) movimientos_ubicacion_incorrecta,
 (SELECT COUNT(*) FROM #errores_empleado) movimientos_empleado_invalido,
 (SELECT COUNT(*) FROM existencias WHERE cantidad<0 AND fecha_eliminacion IS NULL) stock_negativo;

SELECT p.codigo,p.nombre producto,COUNT(*) numero_salidas,
 COUNT(DISTINCT CAST(h.fecha_movimiento AS DATE)) dias_con_consumo,
 COUNT(DISTINCT CASE WHEN h.fecha_movimiento>=DATEADD(day,-30,SYSDATETIME()) THEN CAST(h.fecha_movimiento AS DATE) END) dias_consumo_30,
 MIN(h.fecha_movimiento) primera_salida,MAX(h.fecha_movimiento) ultima_salida,
 AVG(h.cantidad) promedio_salida,STDEVP(h.cantidad) desviacion,MAX(h.cantidad) cantidad_maxima
FROM #historial h JOIN productos p ON p.id_producto=h.id_producto WHERE h.tipo='Salida'
GROUP BY p.codigo,p.nombre ORDER BY p.codigo;

SELECT u.codigo_ubicacion,u.estante,u.nivel,COUNT(DISTINCT p.id_producto) numero_productos
FROM ubicaciones u LEFT JOIN existencias e ON e.id_ubicacion=u.id_ubicacion AND e.fecha_eliminacion IS NULL
LEFT JOIN productos p ON p.id_producto=e.id_producto AND p.estado=1 AND p.fecha_eliminacion IS NULL
WHERE u.estado=1 AND u.fecha_eliminacion IS NULL GROUP BY u.codigo_ubicacion,u.estante,u.nivel ORDER BY u.estante,u.nivel;
SELECT * FROM vw_inventario_ubicaciones ORDER BY estante,nivel,posicion;
