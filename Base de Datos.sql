-- ============================================================
-- SISTEMA INTELIGENTE PARA LA GESTIÓN Y ANÁLISIS DE INVENTARIO
-- SQL SERVER
-- ============================================================


-- ============================================================
-- 1. CREAR BASE DE DATOS
-- ============================================================

IF DB_ID('InventarioIA1') IS NULL
BEGIN
    CREATE DATABASE InventarioIA1;
END;
GO


USE InventarioIA1;
GO


-- ============================================================
-- 2. CATEGORÍAS
-- ============================================================

CREATE TABLE categorias (
    id_categoria INT IDENTITY(1,1) PRIMARY KEY,

    nombre VARCHAR(100) NOT NULL,
    descripcion VARCHAR(255) NULL,

    estado BIT NOT NULL DEFAULT 1,

    fecha_creacion DATETIME2 NOT NULL DEFAULT SYSDATETIME(),
    fecha_actualizacion DATETIME2 NULL,
    fecha_eliminacion DATETIME2 NULL
);
GO


CREATE UNIQUE INDEX UQ_categorias_nombre_activo
ON categorias(nombre)
WHERE fecha_eliminacion IS NULL;
GO


-- ============================================================
-- 3. UBICACIONES
-- ============================================================

CREATE TABLE ubicaciones (
    id_ubicacion INT IDENTITY(1,1) PRIMARY KEY,

    codigo_ubicacion VARCHAR(30) NOT NULL,

    seccion VARCHAR(50) NOT NULL,
    pasillo VARCHAR(50) NULL,
    estante VARCHAR(50) NULL,
    nivel VARCHAR(50) NULL,

    descripcion VARCHAR(255) NULL,

    estado BIT NOT NULL DEFAULT 1,

    fecha_creacion DATETIME2 NOT NULL DEFAULT SYSDATETIME(),
    fecha_actualizacion DATETIME2 NULL,
    fecha_eliminacion DATETIME2 NULL
);
GO


CREATE UNIQUE INDEX UQ_ubicaciones_codigo_activo
ON ubicaciones(codigo_ubicacion)
WHERE fecha_eliminacion IS NULL;
GO


-- ============================================================
-- 4. EMPLEADOS
-- ============================================================

CREATE TABLE empleados (
    id_empleado INT IDENTITY(1,1) PRIMARY KEY,

    codigo_empleado VARCHAR(30) NOT NULL,

    nombres VARCHAR(100) NOT NULL,
    apellidos VARCHAR(100) NOT NULL,

    cargo VARCHAR(100) NULL,

    estado BIT NOT NULL DEFAULT 1,

    fecha_creacion DATETIME2 NOT NULL DEFAULT SYSDATETIME(),
    fecha_actualizacion DATETIME2 NULL,
    fecha_eliminacion DATETIME2 NULL
);
GO


CREATE UNIQUE INDEX UQ_empleados_codigo_activo
ON empleados(codigo_empleado)
WHERE fecha_eliminacion IS NULL;
GO


-- ============================================================
-- 5. PRODUCTOS
-- ============================================================

CREATE TABLE productos (
    id_producto INT IDENTITY(1,1) PRIMARY KEY,

    codigo VARCHAR(30) NOT NULL,

    nombre VARCHAR(150) NOT NULL,

    descripcion VARCHAR(500) NULL,

    id_categoria INT NOT NULL,

    unidad_medida VARCHAR(30) NOT NULL,

    precio DECIMAL(12,2) NOT NULL DEFAULT 0,

    stock_minimo INT NOT NULL DEFAULT 0,

    estado BIT NOT NULL DEFAULT 1,

    fecha_creacion DATETIME2 NOT NULL DEFAULT SYSDATETIME(),
    fecha_actualizacion DATETIME2 NULL,
    fecha_eliminacion DATETIME2 NULL,

    CONSTRAINT FK_productos_categorias
        FOREIGN KEY (id_categoria)
        REFERENCES categorias(id_categoria),

    CONSTRAINT CK_productos_precio
        CHECK (precio >= 0),

    CONSTRAINT CK_productos_stock_minimo
        CHECK (stock_minimo >= 0)
);
GO


CREATE UNIQUE INDEX UQ_productos_codigo_activo
ON productos(codigo)
WHERE fecha_eliminacion IS NULL;
GO


-- ============================================================
-- 6. EXISTENCIAS
-- ============================================================

CREATE TABLE existencias (
    id_existencia INT IDENTITY(1,1) PRIMARY KEY,

    id_producto INT NOT NULL,

    id_ubicacion INT NOT NULL,

    cantidad INT NOT NULL DEFAULT 0,

    fecha_creacion DATETIME2 NOT NULL DEFAULT SYSDATETIME(),
    fecha_actualizacion DATETIME2 NULL,
    fecha_eliminacion DATETIME2 NULL,

    CONSTRAINT FK_existencias_productos
        FOREIGN KEY (id_producto)
        REFERENCES productos(id_producto),

    CONSTRAINT FK_existencias_ubicaciones
        FOREIGN KEY (id_ubicacion)
        REFERENCES ubicaciones(id_ubicacion),

    CONSTRAINT CK_existencias_cantidad
        CHECK (cantidad >= 0)
);
GO


CREATE UNIQUE INDEX UQ_existencias_producto_ubicacion_activa
ON existencias(id_producto, id_ubicacion)
WHERE fecha_eliminacion IS NULL;
GO


-- ============================================================
-- 7. TIPOS DE MOVIMIENTO
-- ============================================================

CREATE TABLE tipos_movimiento (
    id_tipo_movimiento INT IDENTITY(1,1) PRIMARY KEY,

    nombre VARCHAR(50) NOT NULL,

    descripcion VARCHAR(255) NULL,

    estado BIT NOT NULL DEFAULT 1,

    fecha_creacion DATETIME2 NOT NULL DEFAULT SYSDATETIME(),
    fecha_actualizacion DATETIME2 NULL,
    fecha_eliminacion DATETIME2 NULL
);
GO


CREATE UNIQUE INDEX UQ_tipos_movimiento_nombre_activo
ON tipos_movimiento(nombre)
WHERE fecha_eliminacion IS NULL;
GO


-- ============================================================
-- 8. MOVIMIENTOS
-- ============================================================

CREATE TABLE movimientos (
    id_movimiento INT IDENTITY(1,1) PRIMARY KEY,

    id_empleado INT NOT NULL,

    id_tipo_movimiento INT NOT NULL,

    fecha_movimiento DATETIME2 NOT NULL
        DEFAULT SYSDATETIME(),

    observacion VARCHAR(500) NULL,

    fecha_creacion DATETIME2 NOT NULL DEFAULT SYSDATETIME(),
    fecha_actualizacion DATETIME2 NULL,
    fecha_eliminacion DATETIME2 NULL,

    CONSTRAINT FK_movimientos_empleados
        FOREIGN KEY (id_empleado)
        REFERENCES empleados(id_empleado),

    CONSTRAINT FK_movimientos_tipos
        FOREIGN KEY (id_tipo_movimiento)
        REFERENCES tipos_movimiento(id_tipo_movimiento)
);
GO


-- ============================================================
-- 9. DETALLE DE MOVIMIENTOS
-- ============================================================

CREATE TABLE detalle_movimientos (
    id_detalle INT IDENTITY(1,1) PRIMARY KEY,

    id_movimiento INT NOT NULL,

    id_producto INT NOT NULL,

    cantidad INT NOT NULL,

    id_ubicacion_origen INT NULL,

    id_ubicacion_destino INT NULL,

    stock_anterior INT NULL,

    stock_nuevo INT NULL,

    fecha_creacion DATETIME2 NOT NULL DEFAULT SYSDATETIME(),
    fecha_actualizacion DATETIME2 NULL,
    fecha_eliminacion DATETIME2 NULL,

    CONSTRAINT FK_detalle_movimientos
        FOREIGN KEY (id_movimiento)
        REFERENCES movimientos(id_movimiento),

    CONSTRAINT FK_detalle_productos
        FOREIGN KEY (id_producto)
        REFERENCES productos(id_producto),

    CONSTRAINT FK_detalle_ubicacion_origen
        FOREIGN KEY (id_ubicacion_origen)
        REFERENCES ubicaciones(id_ubicacion),

    CONSTRAINT FK_detalle_ubicacion_destino
        FOREIGN KEY (id_ubicacion_destino)
        REFERENCES ubicaciones(id_ubicacion),

    CONSTRAINT CK_detalle_cantidad
        CHECK (cantidad > 0),

    CONSTRAINT CK_detalle_stock_anterior
        CHECK (
            stock_anterior IS NULL
            OR stock_anterior >= 0
        ),

    CONSTRAINT CK_detalle_stock_nuevo
        CHECK (
            stock_nuevo IS NULL
            OR stock_nuevo >= 0
        )
);
GO


-- ============================================================
-- 10. TIPOS DE ALERTA
-- ============================================================

CREATE TABLE tipos_alerta (
    id_tipo_alerta INT IDENTITY(1,1) PRIMARY KEY,

    nombre VARCHAR(100) NOT NULL,

    descripcion VARCHAR(500) NULL,

    estado BIT NOT NULL DEFAULT 1,

    fecha_creacion DATETIME2 NOT NULL DEFAULT SYSDATETIME(),
    fecha_actualizacion DATETIME2 NULL,
    fecha_eliminacion DATETIME2 NULL
);
GO


CREATE UNIQUE INDEX UQ_tipos_alerta_nombre_activo
ON tipos_alerta(nombre)
WHERE fecha_eliminacion IS NULL;
GO


-- ============================================================
-- 11. ALERTAS
-- ============================================================

CREATE TABLE alertas (
    id_alerta INT IDENTITY(1,1) PRIMARY KEY,

    id_tipo_alerta INT NOT NULL,

    id_producto INT NULL,

    id_movimiento INT NULL,

    id_empleado INT NULL,

    id_ubicacion INT NULL,

    mensaje VARCHAR(500) NOT NULL,

    nivel VARCHAR(20) NOT NULL DEFAULT 'Media',

    atendida BIT NOT NULL DEFAULT 0,

    fecha_atencion DATETIME2 NULL,

    fecha_creacion DATETIME2 NOT NULL DEFAULT SYSDATETIME(),
    fecha_actualizacion DATETIME2 NULL,
    fecha_eliminacion DATETIME2 NULL,

    CONSTRAINT FK_alertas_tipos
        FOREIGN KEY (id_tipo_alerta)
        REFERENCES tipos_alerta(id_tipo_alerta),

    CONSTRAINT FK_alertas_productos
        FOREIGN KEY (id_producto)
        REFERENCES productos(id_producto),

    CONSTRAINT FK_alertas_movimientos
        FOREIGN KEY (id_movimiento)
        REFERENCES movimientos(id_movimiento),

    CONSTRAINT FK_alertas_empleados
        FOREIGN KEY (id_empleado)
        REFERENCES empleados(id_empleado),

    CONSTRAINT FK_alertas_ubicaciones
        FOREIGN KEY (id_ubicacion)
        REFERENCES ubicaciones(id_ubicacion),

    CONSTRAINT CK_alertas_nivel
        CHECK (
            nivel IN (
                'Baja',
                'Media',
                'Alta',
                'Critica'
            )
        )
);
GO


-- ============================================================
-- 12. ROSTROS DE EMPLEADOS
-- ============================================================

CREATE TABLE rostros_empleados (
    id_rostro INT IDENTITY(1,1) PRIMARY KEY,

    id_empleado INT NOT NULL,

    etiqueta_modelo VARCHAR(30) NOT NULL,

    estado BIT NOT NULL DEFAULT 1,

    fecha_creacion DATETIME2 NOT NULL DEFAULT SYSDATETIME(),
    fecha_actualizacion DATETIME2 NULL,
    fecha_eliminacion DATETIME2 NULL,

    CONSTRAINT FK_rostros_empleados
        FOREIGN KEY (id_empleado)
        REFERENCES empleados(id_empleado)
);
GO


CREATE UNIQUE INDEX UQ_rostros_etiqueta_activa
ON rostros_empleados(etiqueta_modelo)
WHERE fecha_eliminacion IS NULL;
GO


CREATE UNIQUE INDEX UQ_rostros_empleado_activo
ON rostros_empleados(id_empleado)
WHERE fecha_eliminacion IS NULL;
GO


-- ============================================================
-- 13. TIPOS DE MOVIMIENTO
-- ============================================================

INSERT INTO tipos_movimiento (
    nombre,
    descripcion
)
VALUES
(
    'Entrada',
    'Ingreso de productos al almacén.'
),
(
    'Salida',
    'Retiro de productos del almacén.'
),
(
    'Transferencia',
    'Movimiento de productos entre ubicaciones del almacén.'
),
(
    'Ajuste entrada',
    'Incremento manual del inventario por corrección.'
),
(
    'Ajuste salida',
    'Disminución manual del inventario por corrección.'
);
GO


-- ============================================================
-- 14. TIPOS DE ALERTA
-- ============================================================

INSERT INTO tipos_alerta (
    nombre,
    descripcion
)
VALUES
(
    'Stock bajo',
    'El stock disponible alcanzó o disminuyó por debajo del stock mínimo establecido.'
),
(
    'Producto agotado',
    'El producto llegó a cero unidades disponibles.'
),
(
    'Próximo a agotarse',
    'El análisis predictivo estima que el producto podría agotarse próximamente.'
),
(
    'Movimiento anormal',
    'Se detectó un movimiento diferente al comportamiento habitual del inventario.'
),
(
    'Cantidad inusual',
    'La cantidad registrada se encuentra fuera del comportamiento habitual.'
),
(
    'Horario inusual',
    'Se registró un movimiento en un horario considerado fuera de lo habitual.'
),
(
    'Empleado no reconocido',
    'La cámara detectó una persona que no pudo ser identificada como empleado autorizado.'
);
GO


-- ============================================================
-- 15. CATEGORÍAS
-- ============================================================

INSERT INTO categorias (
    nombre,
    descripcion
)
VALUES
(
    'Herramientas',
    'Herramientas manuales y eléctricas.'
),
(
    'Equipos',
    'Equipos utilizados dentro de las operaciones.'
),
(
    'Materiales eléctricos',
    'Materiales utilizados en instalaciones eléctricas.'
),
(
    'Repuestos',
    'Repuestos para equipos y maquinaria.'
),
(
    'Tornillería',
    'Tornillos, tuercas, pernos y accesorios.'
);
GO


-- ============================================================
-- 16. UBICACIONES
-- ============================================================

INSERT INTO ubicaciones (
    codigo_ubicacion,
    seccion,
    pasillo,
    estante,
    nivel,
    descripcion
)
VALUES
(
    'A-01-01-01',
    'A',
    '01',
    '01',
    '01',
    'Zona de herramientas manuales.'
),
(
    'A-02-02-01',
    'A',
    '02',
    '02',
    '01',
    'Zona de herramientas eléctricas.'
),
(
    'B-02-03-02',
    'B',
    '02',
    '03',
    '02',
    'Zona de motores y equipos.'
),
(
    'C-01-01-02',
    'C',
    '01',
    '01',
    '02',
    'Zona de repuestos.'
),
(
    'D-01-02-01',
    'D',
    '01',
    '02',
    '01',
    'Zona de tornillería.'
),
(
    'D-02-01-01',
    'D',
    '02',
    '01',
    '01',
    'Zona secundaria de tornillería.'
);
GO


-- ============================================================
-- 17. EMPLEADOS
-- ============================================================

INSERT INTO empleados (
    codigo_empleado,
    nombres,
    apellidos,
    cargo
)
VALUES
('EMP-001', 'Carlos', 'Lopez', 'Encargado de almacén'),
('EMP-002', 'Ana', 'Martinez', 'Auxiliar de almacén'),
('EMP-003', 'Luis', 'Ramirez', 'Supervisor'),
('EMP-004', 'Maria', 'Hernandez', 'Auxiliar de almacén'),
('EMP-005', 'Jose', 'Gonzalez', 'Operador de almacén'),
('EMP-006', 'Daniela', 'Perez', 'Auxiliar de inventario'),
('EMP-007', 'Miguel', 'Torres', 'Operador de almacén'),
('EMP-008', 'Andrea', 'Castillo', 'Encargada de inventario'),
('EMP-009', 'Kevin', 'Morales', 'Auxiliar de almacén'),
('EMP-010', 'Sofia', 'Mendoza', 'Supervisora de inventario'),
('EMP-011', 'Fernando', 'Ruiz', 'Operador de almacén'),
('EMP-012', 'Gabriela', 'Sanchez', 'Auxiliar de inventario'),
('EMP-013', 'Alejandro', 'Vargas', 'Operador de almacén'),
('EMP-014', 'Valeria', 'Rojas', 'Auxiliar de almacén'),
('EMP-015', 'Ricardo', 'Navarro', 'Supervisor de almacén');
GO


-- ============================================================
-- 18. RELACIÓN EMPLEADOS - SUBJECTS
-- ============================================================

INSERT INTO rostros_empleados (
    id_empleado,
    etiqueta_modelo
)
SELECT id_empleado, 'subject01'
FROM empleados
WHERE codigo_empleado = 'EMP-001'
AND fecha_eliminacion IS NULL;


INSERT INTO rostros_empleados (
    id_empleado,
    etiqueta_modelo
)
SELECT id_empleado, 'subject02'
FROM empleados
WHERE codigo_empleado = 'EMP-002'
AND fecha_eliminacion IS NULL;


INSERT INTO rostros_empleados (
    id_empleado,
    etiqueta_modelo
)
SELECT id_empleado, 'subject03'
FROM empleados
WHERE codigo_empleado = 'EMP-003'
AND fecha_eliminacion IS NULL;


INSERT INTO rostros_empleados (
    id_empleado,
    etiqueta_modelo
)
SELECT id_empleado, 'subject04'
FROM empleados
WHERE codigo_empleado = 'EMP-004'
AND fecha_eliminacion IS NULL;


INSERT INTO rostros_empleados (
    id_empleado,
    etiqueta_modelo
)
SELECT id_empleado, 'subject05'
FROM empleados
WHERE codigo_empleado = 'EMP-005'
AND fecha_eliminacion IS NULL;


INSERT INTO rostros_empleados (
    id_empleado,
    etiqueta_modelo
)
SELECT id_empleado, 'subject06'
FROM empleados
WHERE codigo_empleado = 'EMP-006'
AND fecha_eliminacion IS NULL;


INSERT INTO rostros_empleados (
    id_empleado,
    etiqueta_modelo
)
SELECT id_empleado, 'subject07'
FROM empleados
WHERE codigo_empleado = 'EMP-007'
AND fecha_eliminacion IS NULL;


INSERT INTO rostros_empleados (
    id_empleado,
    etiqueta_modelo
)
SELECT id_empleado, 'subject08'
FROM empleados
WHERE codigo_empleado = 'EMP-008'
AND fecha_eliminacion IS NULL;


INSERT INTO rostros_empleados (
    id_empleado,
    etiqueta_modelo
)
SELECT id_empleado, 'subject09'
FROM empleados
WHERE codigo_empleado = 'EMP-009'
AND fecha_eliminacion IS NULL;


INSERT INTO rostros_empleados (
    id_empleado,
    etiqueta_modelo
)
SELECT id_empleado, 'subject10'
FROM empleados
WHERE codigo_empleado = 'EMP-010'
AND fecha_eliminacion IS NULL;


INSERT INTO rostros_empleados (
    id_empleado,
    etiqueta_modelo
)
SELECT id_empleado, 'subject11'
FROM empleados
WHERE codigo_empleado = 'EMP-011'
AND fecha_eliminacion IS NULL;


INSERT INTO rostros_empleados (
    id_empleado,
    etiqueta_modelo
)
SELECT id_empleado, 'subject12'
FROM empleados
WHERE codigo_empleado = 'EMP-012'
AND fecha_eliminacion IS NULL;


INSERT INTO rostros_empleados (
    id_empleado,
    etiqueta_modelo
)
SELECT id_empleado, 'subject13'
FROM empleados
WHERE codigo_empleado = 'EMP-013'
AND fecha_eliminacion IS NULL;


INSERT INTO rostros_empleados (
    id_empleado,
    etiqueta_modelo
)
SELECT id_empleado, 'subject14'
FROM empleados
WHERE codigo_empleado = 'EMP-014'
AND fecha_eliminacion IS NULL;


INSERT INTO rostros_empleados (
    id_empleado,
    etiqueta_modelo
)
SELECT id_empleado, 'subject15'
FROM empleados
WHERE codigo_empleado = 'EMP-015'
AND fecha_eliminacion IS NULL;
GO


-- ============================================================
-- 19. PRODUCTOS
-- ============================================================
-- Los precios quedan inicialmente en 0.00.
-- Después puedes cambiarlos por los precios reales.
-- ============================================================

INSERT INTO productos (
    codigo,
    nombre,
    descripcion,
    id_categoria,
    unidad_medida,
    precio,
    stock_minimo
)
SELECT
    'MOT-001',
    'Motor eléctrico',
    'Motor eléctrico para uso industrial.',
    id_categoria,
    'Unidad',
    0.00,
    5
FROM categorias
WHERE nombre = 'Equipos'
AND fecha_eliminacion IS NULL;


INSERT INTO productos (
    codigo,
    nombre,
    descripcion,
    id_categoria,
    unidad_medida,
    precio,
    stock_minimo
)
SELECT
    'TAL-001',
    'Taladro',
    'Taladro eléctrico.',
    id_categoria,
    'Unidad',
    0.00,
    3
FROM categorias
WHERE nombre = 'Herramientas'
AND fecha_eliminacion IS NULL;


INSERT INTO productos (
    codigo,
    nombre,
    descripcion,
    id_categoria,
    unidad_medida,
    precio,
    stock_minimo
)
SELECT
    'ROD-001',
    'Rodamiento',
    'Rodamiento industrial.',
    id_categoria,
    'Unidad',
    0.00,
    10
FROM categorias
WHERE nombre = 'Repuestos'
AND fecha_eliminacion IS NULL;


INSERT INTO productos (
    codigo,
    nombre,
    descripcion,
    id_categoria,
    unidad_medida,
    precio,
    stock_minimo
)
SELECT
    'TOR-001',
    'Tornillo 1/2',
    'Tornillo de media pulgada.',
    id_categoria,
    'Unidad',
    0.00,
    20
FROM categorias
WHERE nombre = 'Tornillería'
AND fecha_eliminacion IS NULL;
GO


-- ============================================================
-- 20. EXISTENCIAS INICIALES
-- ============================================================

INSERT INTO existencias (
    id_producto,
    id_ubicacion,
    cantidad
)
SELECT
    p.id_producto,
    u.id_ubicacion,
    15
FROM productos AS p
CROSS JOIN ubicaciones AS u
WHERE p.codigo = 'MOT-001'
AND u.codigo_ubicacion = 'B-02-03-02'
AND p.fecha_eliminacion IS NULL
AND u.fecha_eliminacion IS NULL;


INSERT INTO existencias (
    id_producto,
    id_ubicacion,
    cantidad
)
SELECT
    p.id_producto,
    u.id_ubicacion,
    8
FROM productos AS p
CROSS JOIN ubicaciones AS u
WHERE p.codigo = 'TAL-001'
AND u.codigo_ubicacion = 'A-02-02-01'
AND p.fecha_eliminacion IS NULL
AND u.fecha_eliminacion IS NULL;


INSERT INTO existencias (
    id_producto,
    id_ubicacion,
    cantidad
)
SELECT
    p.id_producto,
    u.id_ubicacion,
    30
FROM productos AS p
CROSS JOIN ubicaciones AS u
WHERE p.codigo = 'ROD-001'
AND u.codigo_ubicacion = 'C-01-01-02'
AND p.fecha_eliminacion IS NULL
AND u.fecha_eliminacion IS NULL;


INSERT INTO existencias (
    id_producto,
    id_ubicacion,
    cantidad
)
SELECT
    p.id_producto,
    u.id_ubicacion,
    60
FROM productos AS p
CROSS JOIN ubicaciones AS u
WHERE p.codigo = 'TOR-001'
AND u.codigo_ubicacion = 'D-01-02-01'
AND p.fecha_eliminacion IS NULL
AND u.fecha_eliminacion IS NULL;


INSERT INTO existencias (
    id_producto,
    id_ubicacion,
    cantidad
)
SELECT
    p.id_producto,
    u.id_ubicacion,
    40
FROM productos AS p
CROSS JOIN ubicaciones AS u
WHERE p.codigo = 'TOR-001'
AND u.codigo_ubicacion = 'D-02-01-01'
AND p.fecha_eliminacion IS NULL
AND u.fecha_eliminacion IS NULL;
GO


-- ============================================================
-- 21. VISTA INVENTARIO POR UBICACIÓN
-- ============================================================

CREATE OR ALTER VIEW vw_inventario_ubicaciones
AS

SELECT
    p.id_producto,

    p.codigo,

    p.nombre AS producto,

    c.nombre AS categoria,

    p.unidad_medida,

    p.precio,

    u.id_ubicacion,

    u.codigo_ubicacion,

    u.seccion,

    u.pasillo,

    u.estante,

    u.nivel,

    e.cantidad,

    p.stock_minimo

FROM existencias AS e

INNER JOIN productos AS p
    ON e.id_producto = p.id_producto

INNER JOIN categorias AS c
    ON p.id_categoria = c.id_categoria

INNER JOIN ubicaciones AS u
    ON e.id_ubicacion = u.id_ubicacion

WHERE
    e.fecha_eliminacion IS NULL
    AND p.fecha_eliminacion IS NULL
    AND p.estado = 1
    AND c.fecha_eliminacion IS NULL
    AND c.estado = 1
    AND u.fecha_eliminacion IS NULL
    AND u.estado = 1;
GO


-- ============================================================
-- 22. VISTA STOCK TOTAL
-- ============================================================

CREATE OR ALTER VIEW vw_stock_productos
AS

SELECT
    p.id_producto,

    p.codigo,

    p.nombre AS producto,

    c.nombre AS categoria,

    p.unidad_medida,

    p.precio,

    COALESCE(
        SUM(
            CASE
                WHEN e.fecha_eliminacion IS NULL
                    THEN e.cantidad
                ELSE 0
            END
        ),
        0
    ) AS stock_actual,

    p.stock_minimo,

    CASE
        WHEN COALESCE(
            SUM(
                CASE
                    WHEN e.fecha_eliminacion IS NULL
                        THEN e.cantidad
                    ELSE 0
                END
            ),
            0
        ) = 0
            THEN 'Agotado'

        WHEN COALESCE(
            SUM(
                CASE
                    WHEN e.fecha_eliminacion IS NULL
                        THEN e.cantidad
                    ELSE 0
                END
            ),
            0
        ) <= p.stock_minimo
            THEN 'Stock bajo'

        ELSE 'Normal'

    END AS estado_stock

FROM productos AS p

INNER JOIN categorias AS c
    ON p.id_categoria = c.id_categoria

LEFT JOIN existencias AS e
    ON p.id_producto = e.id_producto
    AND e.fecha_eliminacion IS NULL

WHERE
    p.fecha_eliminacion IS NULL
    AND p.estado = 1
    AND c.fecha_eliminacion IS NULL
    AND c.estado = 1

GROUP BY
    p.id_producto,
    p.codigo,
    p.nombre,
    c.nombre,
    p.unidad_medida,
    p.precio,
    p.stock_minimo;
GO


-- ============================================================
-- 23. VISTA HISTORIAL DE MOVIMIENTOS
-- ============================================================

CREATE OR ALTER VIEW vw_historial_movimientos
AS

SELECT
    m.id_movimiento,

    m.fecha_movimiento,

    tm.nombre AS tipo_movimiento,

    CONCAT(
        emp.nombres,
        ' ',
        emp.apellidos
    ) AS empleado,

    emp.codigo_empleado,

    p.codigo AS codigo_producto,

    p.nombre AS producto,

    dm.cantidad,

    uo.codigo_ubicacion AS ubicacion_origen,

    ud.codigo_ubicacion AS ubicacion_destino,

    dm.stock_anterior,

    dm.stock_nuevo,

    m.observacion

FROM detalle_movimientos AS dm

INNER JOIN movimientos AS m
    ON dm.id_movimiento = m.id_movimiento

INNER JOIN tipos_movimiento AS tm
    ON m.id_tipo_movimiento = tm.id_tipo_movimiento

INNER JOIN empleados AS emp
    ON m.id_empleado = emp.id_empleado

INNER JOIN productos AS p
    ON dm.id_producto = p.id_producto

LEFT JOIN ubicaciones AS uo
    ON dm.id_ubicacion_origen = uo.id_ubicacion

LEFT JOIN ubicaciones AS ud
    ON dm.id_ubicacion_destino = ud.id_ubicacion

WHERE
    dm.fecha_eliminacion IS NULL
    AND m.fecha_eliminacion IS NULL
    AND tm.fecha_eliminacion IS NULL;
GO


-- ============================================================
-- 24. VISTA ALERTAS
-- ============================================================

CREATE OR ALTER VIEW vw_alertas
AS

SELECT
    a.id_alerta,

    ta.nombre AS tipo_alerta,

    a.nivel,

    p.codigo AS codigo_producto,

    p.nombre AS producto,

    a.id_movimiento,

    CONCAT(
        emp.nombres,
        ' ',
        emp.apellidos
    ) AS empleado,

    u.codigo_ubicacion,

    a.mensaje,

    a.fecha_creacion AS fecha_generacion,

    a.atendida,

    a.fecha_atencion,

    a.fecha_actualizacion

FROM alertas AS a

INNER JOIN tipos_alerta AS ta
    ON a.id_tipo_alerta = ta.id_tipo_alerta

LEFT JOIN productos AS p
    ON a.id_producto = p.id_producto

LEFT JOIN empleados AS emp
    ON a.id_empleado = emp.id_empleado

LEFT JOIN ubicaciones AS u
    ON a.id_ubicacion = u.id_ubicacion

WHERE
    a.fecha_eliminacion IS NULL
    AND ta.fecha_eliminacion IS NULL;
GO


-- ============================================================
-- 25. VISTA ROSTROS - EMPLEADOS
-- ============================================================

CREATE OR ALTER VIEW vw_rostros_empleados
AS

SELECT
    re.id_rostro,

    re.id_empleado,

    re.etiqueta_modelo,

    e.codigo_empleado,

    e.nombres,

    e.apellidos,

    CONCAT(
        e.nombres,
        ' ',
        e.apellidos
    ) AS empleado,

    e.cargo,

    e.estado AS estado_empleado,

    re.estado AS estado_rostro,

    re.fecha_creacion,

    re.fecha_actualizacion

FROM rostros_empleados AS re

INNER JOIN empleados AS e
    ON re.id_empleado = e.id_empleado

WHERE
    re.fecha_eliminacion IS NULL
    AND e.fecha_eliminacion IS NULL;
GO