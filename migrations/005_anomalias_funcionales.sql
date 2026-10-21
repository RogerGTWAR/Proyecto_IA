-- Estado funcional de hallazgos del inventario. No es una bitácora de acceso.
SET XACT_ABORT ON;
BEGIN TRANSACTION;
DECLARE @r INT;
EXEC @r=sp_getapplock @Resource=N'InventarioIA_anomalias_005',@LockMode='Exclusive',@LockOwner='Transaction',@LockTimeout=10000;
IF @r<0 THROW 51000,N'No se pudo bloquear la migración.',1;
IF OBJECT_ID('dbo.anomalias_inventario','U') IS NULL
BEGIN
 CREATE TABLE dbo.anomalias_inventario(
  id_anomalia BIGINT IDENTITY PRIMARY KEY,
  id_detalle INT NOT NULL REFERENCES dbo.detalle_movimientos(id_detalle),
  tipo_anomalia NVARCHAR(80) NOT NULL,
  nivel NVARCHAR(12) NOT NULL CHECK(nivel IN(N'BAJA',N'MEDIA',N'ALTA',N'CRÍTICA')),
  score FLOAT NOT NULL,
  motivo NVARCHAR(2000) NOT NULL,
  referencia_historica NVARCHAR(2000) NOT NULL,
  estado VARCHAR(12) NOT NULL DEFAULT 'PENDIENTE' CHECK(estado IN('PENDIENTE','REVISADA','JUSTIFICADA')),
  observacion NVARCHAR(1000) NOT NULL DEFAULT N'',
  CONSTRAINT UX_anomalia_detalle_tipo UNIQUE(id_detalle,tipo_anomalia));
END;
COMMIT TRANSACTION;
