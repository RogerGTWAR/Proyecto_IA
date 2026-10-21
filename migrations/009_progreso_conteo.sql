-- Progreso explícito del conteo; no modifica cantidades ni movimientos.
SET XACT_ABORT ON;
BEGIN TRY
 BEGIN TRANSACTION;
 DECLARE @r INT;
 EXEC @r=sp_getapplock @Resource=N'InventarioIA_conteo_009',@LockMode='Exclusive',
     @LockOwner='Transaction',@LockTimeout=10000;
 IF @r<0 THROW 51000,N'No se pudo bloquear la ampliación del conteo.',1;
 IF COL_LENGTH('dbo.detalle_conteos','contado') IS NULL
  ALTER TABLE dbo.detalle_conteos ADD contado BIT NULL;
 -- Los valores NULL anteriores no prueban una confirmación física por fila.
 COMMIT TRANSACTION;
END TRY
BEGIN CATCH
 IF @@TRANCOUNT>0 ROLLBACK TRANSACTION;
 THROW;
END CATCH;
