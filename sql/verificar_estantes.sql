-- Control de distribución y conservación de cantidades; no modifica registros.
USE [InventarioIA2];
SELECT u.codigo_ubicacion,u.estante,u.nivel,COUNT(DISTINCT e.id_producto) numero_productos
FROM dbo.ubicaciones u LEFT JOIN dbo.existencias e ON e.id_ubicacion=u.id_ubicacion AND e.fecha_eliminacion IS NULL
LEFT JOIN dbo.productos p ON p.id_producto=e.id_producto AND p.estado=1 AND p.fecha_eliminacion IS NULL
WHERE u.estado=1 AND u.fecha_eliminacion IS NULL
GROUP BY u.codigo_ubicacion,u.estante,u.nivel ORDER BY u.estante,u.nivel;

SELECT p.id_producto,p.codigo,p.nombre,b.stock_antes,e.stock_despues,
CASE WHEN b.stock_antes=e.stock_despues THEN N'COINCIDE' ELSE N'REVISAR' END resultado
FROM dbo.productos p
JOIN (SELECT id_producto,SUM(cantidad) stock_antes FROM dbo.respaldo_existencias_estantes
      WHERE fecha_eliminacion IS NULL GROUP BY id_producto) b ON b.id_producto=p.id_producto
JOIN (SELECT id_producto,SUM(cantidad) stock_despues FROM dbo.existencias
      WHERE fecha_eliminacion IS NULL GROUP BY id_producto) e ON e.id_producto=p.id_producto
ORDER BY p.id_producto;

SELECT * FROM dbo.vw_inventario_ubicaciones ORDER BY estante,nivel,posicion;
