-- Ampliación del catálogo existente; no crea eventos ni modifica inventario.
SET XACT_ABORT ON;
BEGIN TRY
    BEGIN TRANSACTION;
    DECLARE @bloqueo INT;
    EXEC @bloqueo=sp_getapplock @Resource=N'InventarioIA_tipo_intrusion_006',
        @LockMode='Exclusive',@LockOwner='Transaction',@LockTimeout=10000;
    IF @bloqueo<0 THROW 51000,N'No se pudo bloquear el catálogo de alertas.',1;
    IF (SELECT COUNT(*) FROM dbo.tipos_alerta WHERE nombre=N'Intrusión detectada')>1
        THROW 51001,N'Existen tipos de intrusión duplicados; revisar el catálogo.',1;
    IF EXISTS(SELECT 1 FROM dbo.tipos_alerta WHERE nombre=N'Intrusión detectada'
              AND (estado=0 OR fecha_eliminacion IS NOT NULL))
        THROW 51002,N'El tipo de intrusión está inactivo; revisar antes de habilitarlo.',1;
    IF NOT EXISTS(SELECT 1 FROM dbo.tipos_alerta WHERE nombre=N'Intrusión detectada')
        INSERT dbo.tipos_alerta(nombre,descripcion,estado,fecha_creacion)
        VALUES(N'Intrusión detectada',N'Entrada confirmada de una persona en una zona restringida por cámara.',1,SYSDATETIME());
    COMMIT TRANSACTION;
END TRY
BEGIN CATCH
    IF @@TRANCOUNT>0 ROLLBACK TRANSACTION;
    THROW;
END CATCH;
