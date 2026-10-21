-- Retira exclusivamente la capa de usuarios, roles, permisos y auditoría.
-- Borra sus cuentas e historial. No modifica inventario, empleados ni rostros.
USE [InventarioIA2];
SET XACT_ABORT ON;
BEGIN TRY
    BEGIN TRANSACTION;
    DECLARE @tablas TABLE(nombre SYSNAME PRIMARY KEY);
    INSERT @tablas(nombre) VALUES
        ('recursos_interfaz'),('usuario_rol'),('rol_permiso'),
        ('auditoria_aplicacion'),('usuarios_aplicacion'),
        ('roles'),('permisos'),('seguridad_migraciones');
    IF EXISTS (
        SELECT 1 FROM sys.foreign_keys fk
        JOIN sys.tables destino ON destino.object_id=fk.referenced_object_id
        JOIN @tablas t ON t.nombre=destino.name
        WHERE destino.schema_id=SCHEMA_ID('dbo')
          AND NOT EXISTS(SELECT 1 FROM @tablas origen
              WHERE OBJECT_ID('dbo.'+QUOTENAME(origen.nombre))=fk.parent_object_id)
    ) THROW 51000,N'Hay dependencias externas: no se eliminó ninguna tabla.',1;
    DROP TABLE IF EXISTS dbo.recursos_interfaz;
    DROP TABLE IF EXISTS dbo.usuario_rol;
    DROP TABLE IF EXISTS dbo.rol_permiso;
    DROP TABLE IF EXISTS dbo.auditoria_aplicacion;
    DROP TABLE IF EXISTS dbo.usuarios_aplicacion;
    DROP TABLE IF EXISTS dbo.roles;
    DROP TABLE IF EXISTS dbo.permisos;
    DROP TABLE IF EXISTS dbo.seguridad_migraciones;
    COMMIT TRANSACTION;
END TRY
BEGIN CATCH
    IF @@TRANCOUNT>0 ROLLBACK TRANSACTION;
    THROW;
END CATCH;
