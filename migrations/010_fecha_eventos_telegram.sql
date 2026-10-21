-- Fecha de detección persistida: los hallazgos anteriores conservan NULL.
-- Permite distinguir eventos nuevos sin atribuir fechas a registros históricos.
SET XACT_ABORT ON;
BEGIN TRY
 BEGIN TRANSACTION;
 IF COL_LENGTH('dbo.anomalias_inventario','fecha_creacion') IS NULL
  ALTER TABLE dbo.anomalias_inventario ADD fecha_creacion DATETIME2 NULL
   CONSTRAINT DF_anomalia_fecha_creacion DEFAULT SYSDATETIME();
 COMMIT TRANSACTION;
END TRY
BEGIN CATCH
 IF @@TRANCOUNT>0 ROLLBACK TRANSACTION;
 THROW;
END CATCH;
