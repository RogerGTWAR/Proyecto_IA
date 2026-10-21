-- Normalización del historial operativo de InventarioIA2.
-- Conserva el catálogo, empleados, existencias y la organización física 006.
-- El archivo final preparado contiene los registros; esta plantilla no se ejecuta sola.
USE [InventarioIA2];
SET NOCOUNT ON;
SET XACT_ABORT ON;
IF EXISTS(SELECT 1 FROM dbo.inventario_migraciones WHERE version='007_normalizacion_historial')
BEGIN SELECT N'La normalización del historial ya está aplicada.' resultado; RETURN; END;
BEGIN TRY
 DECLARE @ruta NVARCHAR(4000)=CAST(SESSION_CONTEXT(N'inventario_respaldo_coherencia') AS NVARCHAR(4000));
 IF @ruta IS NULL
 BEGIN
   IF @@TRANCOUNT>0 THROW 51000,N'El respaldo debe ejecutarse fuera de una transacción previa.',1;
   SET @ruta=CAST(SERVERPROPERTY('InstanceDefaultBackupPath') AS NVARCHAR(4000));
   IF @ruta IS NULL THROW 51000,N'No se encontró la carpeta de respaldo.',1;
   SET @ruta=@ruta+CASE WHEN RIGHT(@ruta,1)='\' THEN '' ELSE '\' END+
   N'InventarioIA2_antes_historial_'+REPLACE(REPLACE(REPLACE(CONVERT(VARCHAR(23),SYSDATETIME(),126),':',''),'-',''),'.','')+N'.bak';
   BACKUP DATABASE [InventarioIA2] TO DISK=@ruta WITH COPY_ONLY,CHECKSUM;
   RESTORE VERIFYONLY FROM DISK=@ruta WITH CHECKSUM;
 END;
 BEGIN TRANSACTION;
 DECLARE @bloqueo INT,@cantidad BIGINT,@fecha DATETIME2=SYSDATETIME();
 EXEC @bloqueo=sys.sp_getapplock @Resource=N'InventarioIA_historial_007',@LockMode='Exclusive',@LockOwner='Transaction',@LockTimeout=15000;
 IF @bloqueo<0 THROW 51000,N'No se pudo bloquear la carga.',1;
 SELECT @cantidad=COUNT_BIG(*) FROM dbo.productos WITH(TABLOCKX,HOLDLOCK);
 SELECT @cantidad=COUNT_BIG(*) FROM dbo.existencias WITH(TABLOCKX,HOLDLOCK);
 SELECT @cantidad=COUNT_BIG(*) FROM dbo.ubicaciones WITH(TABLOCKX,HOLDLOCK);
 SELECT @cantidad=COUNT_BIG(*) FROM dbo.movimientos WITH(TABLOCKX,HOLDLOCK);
 IF @cantidad<>@@CANTIDAD_ANTERIOR@@ THROW 51000,N'El historial cambió desde el diagnóstico; vuelva a prepararlo.',1;
 SELECT @cantidad=COUNT_BIG(*) FROM dbo.detalle_movimientos WITH(TABLOCKX,HOLDLOCK);
 SELECT @cantidad=COUNT_BIG(*) FROM dbo.alertas WITH(TABLOCKX,HOLDLOCK);
 IF NOT EXISTS(SELECT 1 FROM inventario_migraciones WHERE version='006_organizacion_fisica')
 THROW 51000,N'La organización física 006 debe estar aplicada.',1;
 IF EXISTS(SELECT 1 FROM detalle_movimiento_lotes) OR EXISTS(SELECT 1 FROM detalle_conteos WHERE id_movimiento IS NOT NULL)
 THROW 51000,N'Hay lotes o conteos ligados al historial: deben revisarse antes de sustituirlo.',1;
 IF OBJECT_ID('dbo.respaldo_movimientos_coherencia','U') IS NOT NULL
 THROW 51000,N'Ya existe un respaldo de coherencia; no se sobrescribió.',1;
 SELECT *,@fecha fecha_respaldo INTO dbo.respaldo_movimientos_coherencia FROM dbo.movimientos;
 SELECT *,@fecha fecha_respaldo INTO dbo.respaldo_detalle_movimientos_coherencia FROM dbo.detalle_movimientos;
 SELECT *,@fecha fecha_respaldo INTO dbo.respaldo_alertas_coherencia FROM dbo.alertas;
 SELECT *,@fecha fecha_respaldo INTO dbo.respaldo_existencias_coherencia FROM dbo.existencias;
 SELECT *,@fecha fecha_respaldo INTO dbo.respaldo_anomalias_coherencia FROM dbo.anomalias_inventario;

 CREATE TABLE #modelo(id_producto INT PRIMARY KEY,id_existencia INT,id_ubicacion INT,posicion TINYINT,
   cantidad DECIMAL(18,3),ubicacion_anterior INT,fecha_reorganizacion DATETIME2);
 INSERT #modelo VALUES
 @@MODELO@@;
 IF EXISTS(SELECT id_producto,id_existencia,id_ubicacion,posicion,cantidad FROM #modelo EXCEPT
   SELECT id_producto,id_existencia,id_ubicacion,posicion,cantidad FROM dbo.existencias WHERE fecha_eliminacion IS NULL)
 OR EXISTS(SELECT id_producto,id_existencia,id_ubicacion,posicion,cantidad FROM dbo.existencias WHERE fecha_eliminacion IS NULL
   EXCEPT SELECT id_producto,id_existencia,id_ubicacion,posicion,cantidad FROM #modelo)
 THROW 51000,N'El stock o las posiciones cambiaron desde la preparación.',1;
 CREATE TABLE #operaciones(orden INT PRIMARY KEY,id_producto INT,id_empleado INT,id_tipo INT,fecha DATETIME2,
   cantidad DECIMAL(18,3),origen INT NULL,destino INT NULL,anterior DECIMAL(18,3),nuevo DECIMAL(18,3),observacion NVARCHAR(500));
 INSERT #operaciones VALUES
 @@OPERACIONES@@;
 IF EXISTS(SELECT 1 FROM #operaciones WHERE fecha>SYSDATETIME() OR cantidad<=0 OR anterior<0 OR nuevo<0)
 THROW 51000,N'Fechas futuras o cantidades inválidas.',1;
 IF EXISTS(SELECT 1 FROM #operaciones o LEFT JOIN empleados e ON e.id_empleado=o.id_empleado
   WHERE e.id_empleado IS NULL OR e.estado=0 OR e.fecha_eliminacion IS NOT NULL)
 THROW 51000,N'Empleado inexistente o inactivo.',1;
 IF EXISTS(SELECT 1 FROM #operaciones o JOIN #modelo m ON m.id_producto=o.id_producto
 WHERE COALESCE(o.origen,o.destino)<>CASE WHEN o.fecha<m.fecha_reorganizacion THEN m.ubicacion_anterior ELSE m.id_ubicacion END)
 THROW 51000,N'Ubicación incompatible con la fecha de reorganización.',1;
 IF EXISTS(SELECT 1 FROM #operaciones o JOIN tipos_movimiento t ON t.id_tipo_movimiento=o.id_tipo
 WHERE t.estado=0 OR t.fecha_eliminacion IS NOT NULL OR
 (t.nombre IN('Entrada','Ajuste entrada') AND (o.origen IS NOT NULL OR o.destino IS NULL OR o.nuevo<>o.anterior+o.cantidad)) OR
 (t.nombre IN('Salida','Ajuste salida') AND (o.origen IS NULL OR o.destino IS NOT NULL OR o.nuevo<>o.anterior-o.cantidad)) OR
 t.nombre NOT IN('Entrada','Salida','Ajuste entrada','Ajuste salida'))
 THROW 51000,N'Semántica de movimiento incorrecta.',1;
 IF EXISTS(SELECT 1 FROM (SELECT anterior,LAG(nuevo) OVER(PARTITION BY id_producto ORDER BY fecha,orden) previo FROM #operaciones) s
 WHERE previo IS NOT NULL AND previo<>anterior)
 THROW 51000,N'La secuencia completa de stock no coincide.',1;
 IF EXISTS(SELECT 1 FROM (SELECT id_producto,nuevo,ROW_NUMBER() OVER(PARTITION BY id_producto ORDER BY fecha DESC,orden DESC) rn FROM #operaciones) u
 JOIN #modelo m ON m.id_producto=u.id_producto WHERE u.rn=1 AND u.nuevo<>m.cantidad)
 THROW 51000,N'El stock final planificado no coincide con existencias.',1;
 IF EXISTS(SELECT 1 FROM (SELECT o.id_producto,o.nuevo,ROW_NUMBER() OVER(PARTITION BY o.id_producto ORDER BY o.fecha DESC,o.orden DESC) rn
 FROM #operaciones o JOIN #modelo m ON m.id_producto=o.id_producto WHERE o.fecha<m.fecha_reorganizacion) u
 JOIN #modelo m ON m.id_producto=u.id_producto WHERE u.rn=1 AND u.nuevo<>m.cantidad)
 THROW 51000,N'El saldo antes de reorganizar no coincide con su respaldo.',1;

 DELETE FROM dbo.alertas;
 DELETE FROM dbo.anomalias_inventario;
 DELETE FROM dbo.detalle_movimientos;
 DELETE FROM dbo.movimientos;
 INSERT dbo.movimientos(id_empleado,id_tipo_movimiento,fecha_movimiento,observacion,fecha_creacion,referencia)
 SELECT o.id_empleado,o.id_tipo,o.fecha,o.observacion,o.fecha,N'INV-007-'+RIGHT('0000'+CONVERT(VARCHAR(4),o.orden),4)
 FROM #operaciones o ORDER BY o.fecha,o.orden;
 INSERT dbo.detalle_movimientos(id_movimiento,id_producto,cantidad,id_ubicacion_origen,id_ubicacion_destino,stock_anterior,stock_nuevo,fecha_creacion)
 SELECT m.id_movimiento,o.id_producto,o.cantidad,o.origen,o.destino,o.anterior,o.nuevo,o.fecha
 FROM #operaciones o JOIN dbo.movimientos m ON m.referencia=N'INV-007-'+RIGHT('0000'+CONVERT(VARCHAR(4),o.orden),4)
 ORDER BY o.fecha,o.orden;
 -- Alertas derivadas del stock, sin modificar el catálogo de tipos.
 INSERT dbo.alertas(id_tipo_alerta,id_producto,mensaje,nivel,atendida,fecha_creacion)
 SELECT CASE WHEN i.stock_actual=0 THEN @@TIPO_AGOTADO@@ ELSE @@TIPO_BAJO@@ END,i.id_producto,
 CASE WHEN i.stock_actual=0 THEN N'El producto '+i.nombre+N' se encuentra agotado.'
 ELSE N'El producto '+i.nombre+N' tiene '+CONVERT(NVARCHAR(40),i.stock_actual)+N' unidades disponibles.' END,
 CASE WHEN i.stock_actual<=i.stock_minimo/2 THEN 'Critica' ELSE 'Alta' END,0,SYSDATETIME()
 FROM dbo.vw_inventario i WHERE i.estado=1 AND i.fecha_eliminacion IS NULL AND i.stock_actual<=i.stock_minimo;
 IF EXISTS(SELECT id_producto,id_existencia,id_ubicacion,posicion,cantidad FROM #modelo EXCEPT
   SELECT id_producto,id_existencia,id_ubicacion,posicion,cantidad FROM dbo.existencias WHERE fecha_eliminacion IS NULL)
 THROW 51000,N'La carga alteró existencias o posiciones.',1;
 DBCC CHECKCONSTRAINTS WITH ALL_CONSTRAINTS;
 INSERT dbo.inventario_migraciones(version) VALUES('007_normalizacion_historial');
 COMMIT TRANSACTION;
 SELECT @ruta respaldo_sql;
 SELECT t.nombre tipo,COUNT(*) movimientos,MIN(m.fecha_movimiento) primera_fecha,MAX(m.fecha_movimiento) ultima_fecha
 FROM movimientos m JOIN tipos_movimiento t ON t.id_tipo_movimiento=m.id_tipo_movimiento GROUP BY t.nombre;
 SELECT p.codigo,p.nombre,COUNT(DISTINCT CASE WHEN t.nombre='Salida' THEN m.id_movimiento END) numero_salidas,
 COUNT(DISTINCT CASE WHEN t.nombre='Salida' AND m.fecha_movimiento>=DATEADD(day,-30,SYSDATETIME()) THEN CAST(m.fecha_movimiento AS DATE) END) dias_consumo_reciente,
 MIN(CASE WHEN t.nombre='Salida' THEN m.fecha_movimiento END) primera_salida,MAX(CASE WHEN t.nombre='Salida' THEN m.fecha_movimiento END) ultima_salida,
 AVG(CASE WHEN t.nombre='Salida' THEN d.cantidad END) promedio_salida,STDEVP(CASE WHEN t.nombre='Salida' THEN d.cantidad END) desviacion,
 MAX(CASE WHEN t.nombre='Salida' THEN d.cantidad END) cantidad_maxima
 FROM productos p JOIN detalle_movimientos d ON d.id_producto=p.id_producto JOIN movimientos m ON m.id_movimiento=d.id_movimiento
 JOIN tipos_movimiento t ON t.id_tipo_movimiento=m.id_tipo_movimiento GROUP BY p.codigo,p.nombre ORDER BY p.codigo;
END TRY
BEGIN CATCH
 IF XACT_STATE()<>0 ROLLBACK TRANSACTION;
 THROW;
END CATCH;
-- El ejecutor Python completa predicción y anomalías con los motores reales antes de confirmar su transacción externa.
