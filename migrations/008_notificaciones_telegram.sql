-- Estado de entrega central. No copia ni envía alertas históricas.
SET XACT_ABORT ON;
BEGIN TRY
 BEGIN TRANSACTION;
 DECLARE @r INT;
 EXEC @r=sp_getapplock @Resource=N'InventarioIA_telegram_008',@LockMode='Exclusive',
     @LockOwner='Transaction',@LockTimeout=10000;
 IF @r<0 THROW 51000,N'No se pudo bloquear la migración de notificaciones.',1;
 IF OBJECT_ID('dbo.notificaciones_telegram','U') IS NULL
 BEGIN
  CREATE TABLE dbo.notificaciones_telegram(
   id_notificacion BIGINT IDENTITY PRIMARY KEY,
   referencia NVARCHAR(180) NOT NULL UNIQUE,
   sesion VARCHAR(32) NOT NULL,
   tipo NVARCHAR(40) NOT NULL,
   nivel NVARCHAR(16) NOT NULL,
   contenido NVARCHAR(MAX) NOT NULL,
   estado VARCHAR(16) NOT NULL DEFAULT 'PENDIENTE',
   intentos INT NOT NULL DEFAULT 0,
   detalle NVARCHAR(500) NOT NULL DEFAULT N'',
   fecha_creacion DATETIME2 NOT NULL DEFAULT SYSDATETIME(),
   fecha_envio DATETIME2 NULL);
  CREATE INDEX IX_telegram_pendientes ON dbo.notificaciones_telegram(sesion,estado,id_notificacion);
 END;
 IF OBJECT_ID('dbo.telegram_estado_riesgo','U') IS NULL
  CREATE TABLE dbo.telegram_estado_riesgo(
   id_producto INT PRIMARY KEY REFERENCES dbo.productos(id_producto),
   riesgo NVARCHAR(20) NOT NULL,
   id_alerta INT NULL,
   ultimo_movimiento INT NOT NULL,
   fecha_actualizacion DATETIME2 NOT NULL DEFAULT SYSDATETIME());
 COMMIT TRANSACTION;
END TRY
BEGIN CATCH
 IF @@TRANCOUNT>0 ROLLBACK TRANSACTION;
 THROW;
END CATCH;
