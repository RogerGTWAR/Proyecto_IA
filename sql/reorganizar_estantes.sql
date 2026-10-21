-- Organización física del almacén. Conserva productos, cantidades, alertas e historial.
-- Ejecutar completo sobre InventarioIA2. Requiere SQL Server y privilegios de respaldo.
USE [InventarioIA2];
SET NOCOUNT ON;
SET XACT_ABORT ON;
IF EXISTS(SELECT 1 FROM dbo.inventario_migraciones WHERE version='006_organizacion_fisica')
BEGIN SELECT N'La organización física ya está aplicada.' resultado; RETURN; END;
BEGIN TRY
 DECLARE @ruta NVARCHAR(4000)=CAST(SERVERPROPERTY('InstanceDefaultBackupPath') AS NVARCHAR(4000));
 IF @ruta IS NULL THROW 51000,N'No se encontró la carpeta de respaldo de SQL Server.',1;
 SET @ruta=@ruta+CASE WHEN RIGHT(@ruta,1)='\' THEN '' ELSE '\' END+
 N'InventarioIA2_antes_estantes_'+REPLACE(REPLACE(REPLACE(CONVERT(VARCHAR(23),SYSDATETIME(),126),':',''),'-',''),'.','')+N'.bak';
 BACKUP DATABASE [InventarioIA2] TO DISK=@ruta WITH COPY_ONLY,CHECKSUM;
 RESTORE VERIFYONLY FROM DISK=@ruta WITH CHECKSUM;
 BEGIN TRANSACTION;
 DECLARE @r INT;
 EXEC @r=sys.sp_getapplock @Resource=N'InventarioIA_organizacion_fisica',@LockMode='Exclusive',
 @LockOwner='Transaction',@LockTimeout=15000;
 IF @r<0 THROW 51000,N'No se pudo bloquear la reorganización.',1;
 DECLARE @filas BIGINT;
 SELECT @filas=COUNT_BIG(*) FROM dbo.ubicaciones WITH(TABLOCKX,HOLDLOCK);
 SELECT @filas=COUNT_BIG(*) FROM dbo.existencias WITH(TABLOCKX,HOLDLOCK);
 SELECT @filas=COUNT_BIG(*) FROM dbo.productos WITH(TABLOCKX,HOLDLOCK);
 SELECT @filas=COUNT_BIG(*) FROM dbo.movimientos WITH(TABLOCKX,HOLDLOCK);
 SELECT @filas=COUNT_BIG(*) FROM dbo.detalle_movimientos WITH(TABLOCKX,HOLDLOCK);
 SELECT @filas=COUNT_BIG(*) FROM dbo.alertas WITH(TABLOCKX,HOLDLOCK);
 IF COL_LENGTH('dbo.existencias','posicion') IS NULL
 EXEC(N'ALTER TABLE dbo.existencias ADD posicion TINYINT NULL;');
 IF COL_LENGTH('dbo.ubicaciones','capacidad_productos') IS NULL
 EXEC(N'ALTER TABLE dbo.ubicaciones ADD capacidad_productos TINYINT NOT NULL CONSTRAINT DF_ubicacion_capacidad DEFAULT 2;');
 EXEC(N'
DECLARE @fecha DATETIME2=SYSDATETIME();
SELECT * INTO #historico_movimientos FROM dbo.movimientos;
SELECT * INTO #historico_detalles FROM dbo.detalle_movimientos;
SELECT * INTO #alertas_antes FROM dbo.alertas;
SELECT id_producto,SUM(cantidad) stock INTO #stock_antes FROM dbo.existencias
 WHERE fecha_eliminacion IS NULL GROUP BY id_producto;
IF (SELECT COUNT(*) FROM dbo.productos WHERE estado=1 AND fecha_eliminacion IS NULL)<>24
 THROW 51000,N''Se requieren los 24 productos activos de la base vigente.'',1;
IF (SELECT COUNT(*) FROM dbo.existencias WHERE fecha_eliminacion IS NULL)<>24 OR
 EXISTS(SELECT id_producto FROM dbo.existencias WHERE fecha_eliminacion IS NULL GROUP BY id_producto HAVING COUNT(*)<>1)
 THROW 51000,N''Revise las asignaciones: se requiere una existencia vigente por producto.'',1;
IF EXISTS(SELECT 1 FROM dbo.existencias_lotes) OR EXISTS(SELECT 1 FROM dbo.detalle_conteos)
 THROW 51000,N''Existen lotes o conteos: deben revisarse antes de reorganizar.'',1;
IF OBJECT_ID(''dbo.respaldo_ubicaciones_estantes'',''U'') IS NOT NULL OR
 OBJECT_ID(''dbo.respaldo_existencias_estantes'',''U'') IS NOT NULL
 THROW 51000,N''Ya existe un respaldo físico previo; no se sobrescribió.'',1;
SELECT *,@fecha fecha_respaldo INTO dbo.respaldo_ubicaciones_estantes FROM dbo.ubicaciones;
SELECT *,@fecha fecha_respaldo,CAST(NULL AS INT) id_ubicacion_nueva,
 CAST(NULL AS TINYINT) posicion_nueva INTO dbo.respaldo_existencias_estantes FROM dbo.existencias;

DECLARE @estantes INT=6,@niveles INT=2,@posiciones INT=2;
SELECT p.id_producto,ROW_NUMBER() OVER(ORDER BY p.id_producto) orden
 INTO #productos FROM dbo.productos p WHERE p.estado=1 AND p.fecha_eliminacion IS NULL;
SELECT id_producto,RIGHT(''00''+CAST((orden-1)/(@niveles*@posiciones)+1 AS VARCHAR(2)),2) estante,
 RIGHT(''00''+CAST(((orden-1)/@posiciones)%@niveles+1 AS VARCHAR(2)),2) nivel,
 CAST((orden-1)%@posiciones+1 AS TINYINT) posicion INTO #asignacion FROM #productos;
UPDATE dbo.ubicaciones SET estado=0,fecha_actualizacion=@fecha WHERE estado=1 AND fecha_eliminacion IS NULL;
INSERT dbo.ubicaciones(codigo_ubicacion,seccion,pasillo,estante,nivel,descripcion,estado,
 fecha_creacion,almacen,zona,capacidad_productos)
 SELECT DISTINCT ''E''+estante+''-N''+nivel,''A'',''01'',estante,nivel,
 ''Estante ''+CAST(CONVERT(INT,estante) AS VARCHAR(2))+'' - Nivel ''+CAST(CONVERT(INT,nivel) AS VARCHAR(2)),
 1,@fecha,NULL,''A'',@posiciones FROM #asignacion;
UPDATE b SET id_ubicacion_nueva=u.id_ubicacion,posicion_nueva=a.posicion
 FROM dbo.respaldo_existencias_estantes b JOIN #asignacion a ON a.id_producto=b.id_producto
 JOIN dbo.ubicaciones u ON u.codigo_ubicacion=''E''+a.estante+''-N''+a.nivel AND u.estado=1
 WHERE b.fecha_eliminacion IS NULL;
UPDATE e SET id_ubicacion=b.id_ubicacion_nueva,posicion=b.posicion_nueva,fecha_actualizacion=@fecha
 FROM dbo.existencias e JOIN dbo.respaldo_existencias_estantes b ON b.id_existencia=e.id_existencia
 WHERE e.fecha_eliminacion IS NULL;
IF EXISTS(SELECT id_producto,stock FROM #stock_antes EXCEPT
 SELECT id_producto,SUM(cantidad) FROM dbo.existencias WHERE fecha_eliminacion IS NULL GROUP BY id_producto)
 OR EXISTS(SELECT id_producto,SUM(cantidad) FROM dbo.existencias WHERE fecha_eliminacion IS NULL GROUP BY id_producto
 EXCEPT SELECT id_producto,stock FROM #stock_antes)
 THROW 51000,N''El stock cambió durante la reorganización.'',1;
IF (SELECT COUNT(*) FROM dbo.ubicaciones WHERE estado=1 AND fecha_eliminacion IS NULL)<>@estantes*@niveles
 OR EXISTS(SELECT u.id_ubicacion FROM dbo.ubicaciones u LEFT JOIN dbo.existencias e
 ON e.id_ubicacion=u.id_ubicacion AND e.fecha_eliminacion IS NULL WHERE u.estado=1
 GROUP BY u.id_ubicacion HAVING COUNT(DISTINCT e.id_producto)<>@posiciones)
 THROW 51000,N''La distribución no cumple seis estantes y dos productos por nivel.'',1;
IF EXISTS(SELECT * FROM #historico_movimientos EXCEPT SELECT * FROM dbo.movimientos)
 OR EXISTS(SELECT * FROM dbo.movimientos EXCEPT SELECT * FROM #historico_movimientos)
 OR EXISTS(SELECT * FROM #historico_detalles EXCEPT SELECT * FROM dbo.detalle_movimientos)
 OR EXISTS(SELECT * FROM dbo.detalle_movimientos EXCEPT SELECT * FROM #historico_detalles)
 OR EXISTS(SELECT * FROM #alertas_antes EXCEPT SELECT * FROM dbo.alertas)
 OR EXISTS(SELECT * FROM dbo.alertas EXCEPT SELECT * FROM #alertas_antes)
 THROW 51000,N''Se detectó un cambio en movimientos o alertas.'',1;
');
 EXEC(N'ALTER TABLE dbo.existencias WITH CHECK ADD CONSTRAINT CK_existencias_posicion CHECK(posicion IS NULL OR posicion IN(1,2));');
 EXEC(N'CREATE UNIQUE INDEX UX_existencias_posicion ON dbo.existencias(id_ubicacion,posicion) WHERE fecha_eliminacion IS NULL AND posicion IS NOT NULL;');
 EXEC(N'ALTER TABLE dbo.ubicaciones WITH CHECK ADD CONSTRAINT CK_ubicacion_estructura CHECK(
 estado=0 OR (estante IS NOT NULL AND nivel IS NOT NULL AND estante IN(''01'',''02'',''03'',''04'',''05'',''06'') AND nivel IN(''01'',''02'') AND codigo_ubicacion=''E''+estante+''-N''+nivel AND capacidad_productos=2));');
 EXEC(N'CREATE UNIQUE INDEX UX_ubicacion_estante_nivel ON dbo.ubicaciones(estante,nivel) WHERE estado=1 AND fecha_eliminacion IS NULL;');
 EXEC(N'
CREATE OR ALTER TRIGGER dbo.TR_existencias_capacidad_fisica ON dbo.existencias
AFTER INSERT,UPDATE AS
BEGIN
 SET NOCOUNT ON;
 DECLARE @ubicacion INT,@estante VARCHAR(10),@nivel VARCHAR(10),@mensaje NVARCHAR(2048);
 -- Serializar la ocupación por ubicación también para inserciones SQL directas.
 DECLARE @bloqueadas BIGINT;
 SELECT @bloqueadas=COUNT_BIG(*) FROM dbo.ubicaciones u WITH(UPDLOCK,HOLDLOCK)
 WHERE u.id_ubicacion IN(SELECT id_ubicacion FROM inserted UNION SELECT id_ubicacion FROM deleted);
 SELECT TOP(1) @ubicacion=u.id_ubicacion,@estante=u.estante,@nivel=u.nivel
 FROM dbo.ubicaciones u JOIN dbo.existencias e WITH(UPDLOCK,HOLDLOCK) ON e.id_ubicacion=u.id_ubicacion
 WHERE u.estado=1 AND u.fecha_eliminacion IS NULL AND e.fecha_eliminacion IS NULL
 AND u.id_ubicacion IN(SELECT id_ubicacion FROM inserted UNION SELECT id_ubicacion FROM deleted)
 GROUP BY u.id_ubicacion,u.estante,u.nivel,u.capacidad_productos
 HAVING COUNT(DISTINCT e.id_producto)>u.capacidad_productos;
 IF @ubicacion IS NOT NULL BEGIN
   SET @mensaje=N''El Estante ''+CAST(CONVERT(INT,@estante) AS NVARCHAR(2))+N'' - Nivel ''+
    CAST(CONVERT(INT,@nivel) AS NVARCHAR(2))+N'' ya tiene los dos espacios de producto ocupados.'';
   THROW 51001,@mensaje,1;
 END;
 IF EXISTS(SELECT 1 FROM inserted e JOIN dbo.ubicaciones u ON u.id_ubicacion=e.id_ubicacion
 WHERE e.fecha_eliminacion IS NULL AND (u.estado=0 OR u.fecha_eliminacion IS NOT NULL OR e.posicion IS NULL))
 THROW 51002,N''Asigne una posición 1 o 2 en una ubicación activa.'',1;
END;
');
 EXEC(N'
CREATE OR ALTER VIEW dbo.vw_inventario_ubicaciones AS
SELECT p.id_producto,p.codigo,p.nombre producto,c.nombre categoria,p.unidad_medida,p.precio,
 u.id_ubicacion,u.codigo_ubicacion,u.seccion,u.pasillo,u.estante,u.nivel,e.cantidad,p.stock_minimo,
 e.posicion,(TRY_CONVERT(INT,u.estante)-1)*4+(TRY_CONVERT(INT,u.nivel)-1)*2+e.posicion led
 FROM dbo.existencias e JOIN dbo.productos p ON p.id_producto=e.id_producto
 JOIN dbo.categorias c ON c.id_categoria=p.id_categoria JOIN dbo.ubicaciones u ON u.id_ubicacion=e.id_ubicacion
 WHERE e.fecha_eliminacion IS NULL AND p.estado=1 AND p.fecha_eliminacion IS NULL
 AND c.estado=1 AND c.fecha_eliminacion IS NULL AND u.estado=1 AND u.fecha_eliminacion IS NULL;
');
 INSERT dbo.inventario_migraciones(version) VALUES('006_organizacion_fisica');
 COMMIT TRANSACTION;
 SELECT @ruta respaldo_sql;
 EXEC(N'SELECT * FROM dbo.vw_inventario_ubicaciones ORDER BY estante,nivel,posicion;');
 SELECT u.estante,u.nivel,COUNT(DISTINCT e.id_producto) numero_productos
 FROM dbo.ubicaciones u LEFT JOIN dbo.existencias e ON e.id_ubicacion=u.id_ubicacion AND e.fecha_eliminacion IS NULL
 WHERE u.estado=1 AND u.fecha_eliminacion IS NULL GROUP BY u.estante,u.nivel ORDER BY u.estante,u.nivel;
END TRY
BEGIN CATCH
 IF XACT_STATE()<>0 ROLLBACK TRANSACTION;
 THROW;
END CATCH;

