-- Detalle opcional del evento; conserva alertas y referencias existentes.
SET XACT_ABORT ON;
BEGIN TRY
    BEGIN TRANSACTION;
    DECLARE @bloqueo INT;
    EXEC @bloqueo=sp_getapplock @Resource=N'InventarioIA_identidad_intrusion_007',
        @LockMode='Exclusive',@LockOwner='Transaction',@LockTimeout=10000;
    IF @bloqueo<0 THROW 51000,N'No se pudo bloquear la ampliación de alertas.',1;
    IF OBJECT_ID('dbo.alertas','U') IS NULL
        THROW 51001,N'No se encontró la tabla de alertas existente.',1;
    IF COL_LENGTH('dbo.alertas','detalle_vigilancia') IS NULL
        ALTER TABLE dbo.alertas ADD detalle_vigilancia NVARCHAR(MAX) NULL;
    COMMIT TRANSACTION;
END TRY
BEGIN CATCH
    IF @@TRANCOUNT>0 ROLLBACK TRANSACTION;
    THROW;
END CATCH;
