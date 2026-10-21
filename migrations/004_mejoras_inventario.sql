-- SQL Server / InventarioIA2. No elimina datos ni incorpora autenticación.
-- Ejecutar todos los lotes GO en una misma conexión.
SET XACT_ABORT ON;
BEGIN TRANSACTION;
DECLARE @r INT;
EXEC @r=sp_getapplock @Resource=N'InventarioIA_migracion_004',
 @LockMode='Exclusive',@LockOwner='Transaction',@LockTimeout=10000;
IF @r<0 THROW 51000,N'No se pudo bloquear la migración.',1;
IF OBJECT_ID('dbo.inventario_migraciones') IS NULL
 CREATE TABLE dbo.inventario_migraciones(version VARCHAR(80) PRIMARY KEY,fecha DATETIME2 DEFAULT SYSDATETIME());
IF OBJECT_ID('dbo.unidades_medida') IS NULL
 CREATE TABLE dbo.unidades_medida(id_unidad INT IDENTITY PRIMARY KEY,nombre NVARCHAR(80) UNIQUE NOT NULL,
 abreviatura NVARCHAR(16) NOT NULL,activo BIT NOT NULL DEFAULT 1);
INSERT dbo.unidades_medida(nombre,abreviatura)
SELECT v.nombre,v.abreviatura FROM (VALUES(N'Unidad',N'ud'),(N'Caja',N'caja'),(N'Litro',N'L'),
 (N'Galón',N'gal'),(N'Metro',N'm'),(N'Kilogramo',N'kg'),(N'Paquete',N'paq'))v(nombre,abreviatura)
WHERE NOT EXISTS(SELECT 1 FROM dbo.unidades_medida u WHERE u.nombre=v.nombre);
INSERT dbo.unidades_medida(nombre,abreviatura)
SELECT DISTINCT p.unidad_medida,LEFT(p.unidad_medida,16) FROM dbo.productos p
WHERE NOT EXISTS(SELECT 1 FROM dbo.unidades_medida u WHERE u.nombre=p.unidad_medida);
IF COL_LENGTH('dbo.productos','id_unidad_medida') IS NULL
 ALTER TABLE dbo.productos ADD id_unidad_medida INT NULL;
IF COL_LENGTH('dbo.productos','control_lotes') IS NULL
 ALTER TABLE dbo.productos ADD control_lotes BIT NOT NULL DEFAULT 0;
IF COL_LENGTH('dbo.productos','codigo_barras') IS NULL
 ALTER TABLE dbo.productos ADD codigo_barras NVARCHAR(100) NULL;
IF COL_LENGTH('dbo.productos','codigo_qr') IS NULL
 ALTER TABLE dbo.productos ADD codigo_qr NVARCHAR(250) NULL;
IF COL_LENGTH('dbo.productos','imagen_producto') IS NULL
 ALTER TABLE dbo.productos ADD imagen_producto NVARCHAR(1000) NULL;
IF COL_LENGTH('dbo.ubicaciones','almacen') IS NULL
 ALTER TABLE dbo.ubicaciones ADD almacen NVARCHAR(80) NULL;
IF COL_LENGTH('dbo.ubicaciones','zona') IS NULL
 ALTER TABLE dbo.ubicaciones ADD zona NVARCHAR(80) NULL;
GO
UPDATE p SET id_unidad_medida=u.id_unidad FROM dbo.productos p JOIN dbo.unidades_medida u ON u.nombre=p.unidad_medida
 WHERE p.id_unidad_medida IS NULL;
ALTER TABLE dbo.productos ALTER COLUMN id_unidad_medida INT NOT NULL;
IF NOT EXISTS(SELECT 1 FROM sys.foreign_keys WHERE name='FK_producto_unidad')
 ALTER TABLE dbo.productos ADD CONSTRAINT FK_producto_unidad FOREIGN KEY(id_unidad_medida) REFERENCES dbo.unidades_medida(id_unidad);
-- estado y precio siguen siendo los campos almacenados: no duplicar activo/precio_unitario.
ALTER TABLE dbo.productos ALTER COLUMN unidad_medida NVARCHAR(80) NOT NULL;
-- Conservar y restaurar las restricciones originales al ampliar cantidades.
DECLARE @cambio TABLE(tabla SYSNAME,columna SYSNAME);
INSERT @cambio VALUES('productos','stock_minimo'),('existencias','cantidad'),
 ('detalle_movimientos','cantidad'),('detalle_movimientos','stock_anterior'),('detalle_movimientos','stock_nuevo');
DECLARE @restricciones TABLE(tabla SYSNAME,nombre SYSNAME,definicion NVARCHAR(MAX),columna NVARCHAR(128) NULL,tipo CHAR(1));
INSERT @restricciones
SELECT DISTINCT t.name,c.name,c.definition,NULL,'C' FROM sys.check_constraints c
JOIN sys.tables t ON t.object_id=c.parent_object_id
JOIN @cambio x ON x.tabla=t.name
WHERE CHARINDEX(QUOTENAME(x.columna),c.definition)>0;
INSERT @restricciones
SELECT t.name,d.name,d.definition,x.columna,'D' FROM sys.default_constraints d
JOIN sys.tables t ON t.object_id=d.parent_object_id
JOIN @cambio x ON x.tabla=t.name AND x.columna=COL_NAME(d.parent_object_id,d.parent_column_id);
DECLARE @sql NVARCHAR(MAX)=N'';
SELECT @sql=@sql+N'ALTER TABLE dbo.'+QUOTENAME(tabla)+N' DROP CONSTRAINT '+QUOTENAME(nombre)+N';' FROM @restricciones;
IF LEN(@sql)>0 EXEC sp_executesql @sql;
ALTER TABLE dbo.productos ALTER COLUMN stock_minimo DECIMAL(18,3) NOT NULL;
ALTER TABLE dbo.existencias ALTER COLUMN cantidad DECIMAL(18,3) NOT NULL;
ALTER TABLE dbo.detalle_movimientos ALTER COLUMN cantidad DECIMAL(18,3) NOT NULL;
ALTER TABLE dbo.detalle_movimientos ALTER COLUMN stock_anterior DECIMAL(18,3) NULL;
ALTER TABLE dbo.detalle_movimientos ALTER COLUMN stock_nuevo DECIMAL(18,3) NULL;
SET @sql=N'';
SELECT @sql=@sql+N'ALTER TABLE dbo.'+QUOTENAME(tabla)+N' ADD CONSTRAINT '+QUOTENAME(nombre)+
 CASE WHEN tipo='C' THEN N' CHECK '+definicion ELSE N' DEFAULT '+definicion+N' FOR '+QUOTENAME(columna) END+N';' FROM @restricciones;
IF LEN(@sql)>0 EXEC sp_executesql @sql;
IF OBJECT_ID('dbo.motivos_movimiento') IS NULL
 CREATE TABLE dbo.motivos_movimiento(id_motivo INT IDENTITY PRIMARY KEY,nombre NVARCHAR(100) NOT NULL,
 tipo VARCHAR(30) NOT NULL,activo BIT NOT NULL DEFAULT 1,CONSTRAINT UQ_motivo_tipo UNIQUE(nombre,tipo));
INSERT dbo.motivos_movimiento(nombre,tipo)
SELECT v.nombre,v.tipo FROM (VALUES(N'Entrada por compra','Entrada'),(N'Devolución','Entrada'),
 (N'Salida por consumo','Salida'),(N'Salida por mantenimiento','Salida'),(N'Producto dañado','Salida'),
 (N'Transferencia interna','Transferencia'),(N'Corrección de inventario','Ajuste entrada'),
 (N'Corrección de inventario','Ajuste salida'))v(nombre,tipo)
WHERE NOT EXISTS(SELECT 1 FROM dbo.motivos_movimiento m WHERE m.nombre=v.nombre AND m.tipo=v.tipo);
INSERT dbo.tipos_movimiento(nombre,descripcion,estado,fecha_creacion)
SELECT v.nombre,v.nombre,1,SYSDATETIME() FROM (VALUES('Ajuste entrada'),('Ajuste salida'))v(nombre)
WHERE NOT EXISTS(SELECT 1 FROM dbo.tipos_movimiento t WHERE t.nombre=v.nombre AND t.fecha_eliminacion IS NULL);
IF COL_LENGTH('dbo.movimientos','id_motivo') IS NULL
 ALTER TABLE dbo.movimientos ADD id_motivo INT NULL REFERENCES dbo.motivos_movimiento(id_motivo);
IF COL_LENGTH('dbo.movimientos','referencia') IS NULL
 ALTER TABLE dbo.movimientos ADD referencia NVARCHAR(100) NULL;
IF COL_LENGTH('dbo.detalle_movimientos','costo_unitario') IS NULL
 ALTER TABLE dbo.detalle_movimientos ADD costo_unitario DECIMAL(18,2) NULL CHECK(costo_unitario>=0);
IF OBJECT_ID('dbo.lotes') IS NULL
 CREATE TABLE dbo.lotes(id_lote INT IDENTITY PRIMARY KEY,id_producto INT NOT NULL REFERENCES dbo.productos(id_producto),
 codigo_lote NVARCHAR(80) NOT NULL,fecha_ingreso DATETIME2 NOT NULL DEFAULT SYSDATETIME(),fecha_vencimiento DATE NULL,
 activo BIT NOT NULL DEFAULT 1,CONSTRAINT UQ_lote_producto UNIQUE(id_producto,codigo_lote));
IF OBJECT_ID('dbo.existencias_lotes') IS NULL
 CREATE TABLE dbo.existencias_lotes(id_lote INT NOT NULL REFERENCES dbo.lotes(id_lote),
 id_ubicacion INT NOT NULL REFERENCES dbo.ubicaciones(id_ubicacion),cantidad DECIMAL(18,3) NOT NULL CHECK(cantidad>=0),
 CONSTRAINT PK_existencias_lotes PRIMARY KEY(id_lote,id_ubicacion));
IF OBJECT_ID('dbo.detalle_movimiento_lotes') IS NULL
 CREATE TABLE dbo.detalle_movimiento_lotes(id_detalle INT NOT NULL REFERENCES dbo.detalle_movimientos(id_detalle),
 id_lote INT NOT NULL REFERENCES dbo.lotes(id_lote),cantidad DECIMAL(18,3) NOT NULL CHECK(cantidad>0),
 CONSTRAINT PK_detalle_lote PRIMARY KEY(id_detalle,id_lote));
IF OBJECT_ID('dbo.conteos_inventario') IS NULL
 CREATE TABLE dbo.conteos_inventario(id_conteo INT IDENTITY PRIMARY KEY,id_ubicacion INT NOT NULL REFERENCES dbo.ubicaciones(id_ubicacion),
 id_empleado INT NOT NULL REFERENCES dbo.empleados(id_empleado),fecha DATETIME2 NOT NULL DEFAULT SYSDATETIME(),
 estado VARCHAR(20) NOT NULL DEFAULT 'BORRADOR' CHECK(estado IN('BORRADOR','APLICADO')));
IF OBJECT_ID('dbo.detalle_conteos') IS NULL
 CREATE TABLE dbo.detalle_conteos(id_conteo INT NOT NULL REFERENCES dbo.conteos_inventario(id_conteo),
 id_producto INT NOT NULL REFERENCES dbo.productos(id_producto),id_lote INT NULL REFERENCES dbo.lotes(id_lote),
 cantidad_sistema DECIMAL(18,3) NOT NULL,cantidad_fisica DECIMAL(18,3) NOT NULL CHECK(cantidad_fisica>=0),
 id_detalle_conteo INT IDENTITY PRIMARY KEY,id_movimiento INT NULL REFERENCES dbo.movimientos(id_movimiento));
IF COL_LENGTH('dbo.alertas','id_lote') IS NULL
 ALTER TABLE dbo.alertas ADD id_lote INT NULL REFERENCES dbo.lotes(id_lote);
INSERT dbo.tipos_alerta(nombre,descripcion,estado,fecha_creacion)
SELECT v.nombre,v.nombre,1,SYSDATETIME() FROM (VALUES('Lote próximo a vencer'),('Lote vencido'))v(nombre)
WHERE NOT EXISTS(SELECT 1 FROM dbo.tipos_alerta t WHERE t.nombre=v.nombre AND t.fecha_eliminacion IS NULL);
IF NOT EXISTS(SELECT 1 FROM sys.indexes WHERE name='IX_productos_busqueda' AND object_id=OBJECT_ID('dbo.productos'))
 CREATE INDEX IX_productos_busqueda ON dbo.productos(nombre,id_categoria) INCLUDE(codigo,estado,id_unidad_medida);
IF NOT EXISTS(SELECT 1 FROM sys.indexes WHERE name='UX_productos_codigo_global' AND object_id=OBJECT_ID('dbo.productos'))
 CREATE UNIQUE INDEX UX_productos_codigo_global ON dbo.productos(codigo);
IF NOT EXISTS(SELECT 1 FROM sys.indexes WHERE name='IX_movimientos_fecha_tipo' AND object_id=OBJECT_ID('dbo.movimientos'))
 CREATE INDEX IX_movimientos_fecha_tipo ON dbo.movimientos(fecha_movimiento,id_tipo_movimiento);
IF NOT EXISTS(SELECT 1 FROM sys.indexes WHERE name='IX_detalle_producto' AND object_id=OBJECT_ID('dbo.detalle_movimientos'))
 CREATE INDEX IX_detalle_producto ON dbo.detalle_movimientos(id_producto,id_movimiento);
GO
CREATE OR ALTER VIEW dbo.vw_stock_producto AS
 SELECT p.id_producto,COALESCE(SUM(e.cantidad),0) stock_actual
 FROM dbo.productos p LEFT JOIN dbo.existencias e ON e.id_producto=p.id_producto AND e.fecha_eliminacion IS NULL
 AND EXISTS(SELECT 1 FROM dbo.ubicaciones u WHERE u.id_ubicacion=e.id_ubicacion AND u.estado=1 AND u.fecha_eliminacion IS NULL)
 GROUP BY p.id_producto;
GO
CREATE OR ALTER VIEW dbo.vw_inventario AS
 SELECT p.*,c.nombre categoria,u.nombre unidad,u.abreviatura,s.stock_actual,
 p.precio precio_unitario,p.estado activo,s.stock_actual*p.precio valor_stock,
 CASE WHEN p.estado=0 THEN 'INACTIVO' WHEN s.stock_actual=0 THEN 'AGOTADO'
 WHEN s.stock_actual<=p.stock_minimo/2.0 THEN 'CRÍTICO'
 WHEN s.stock_actual<=p.stock_minimo THEN 'BAJO' ELSE 'NORMAL' END estado_inventario
 FROM dbo.productos p JOIN dbo.categorias c ON c.id_categoria=p.id_categoria
 JOIN dbo.unidades_medida u ON u.id_unidad=p.id_unidad_medida
 JOIN dbo.vw_stock_producto s ON s.id_producto=p.id_producto;
GO
IF NOT EXISTS(SELECT 1 FROM dbo.inventario_migraciones WHERE version='004_mejoras_inventario')
 INSERT dbo.inventario_migraciones(version) VALUES('004_mejoras_inventario');
COMMIT TRANSACTION;
