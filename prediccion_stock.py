import math

from database import conectar


MINIMO_DIAS_PREDICCION = 5
DIAS_ALERTA_AGOTAMIENTO = 7


def obtener_consumo_diario(id_producto):
    conexion = None
    cursor = None

    try:
        conexion = conectar()
        cursor = conexion.cursor()

        cursor.execute("""
            SELECT
                CAST(m.fecha_movimiento AS date) AS fecha,
                SUM(d.cantidad) AS cantidad

            FROM movimientos AS m

            INNER JOIN tipos_movimiento AS tm
                ON tm.id_tipo_movimiento = m.id_tipo_movimiento

            INNER JOIN detalle_movimientos AS d
                ON d.id_movimiento = m.id_movimiento

            WHERE
                tm.nombre = 'Salida'
                AND d.id_producto = ?
                AND m.fecha_eliminacion IS NULL
                AND d.fecha_eliminacion IS NULL
                AND tm.fecha_eliminacion IS NULL

            GROUP BY
                CAST(m.fecha_movimiento AS date)

            ORDER BY
                fecha;
        """, id_producto)

        return [
            {
                "fecha": fila.fecha,
                "cantidad": fila.cantidad
            }
            for fila in cursor.fetchall()
        ]

    finally:
        if cursor is not None:
            cursor.close()

        if conexion is not None:
            conexion.close()


def analizar_consumo_producto(id_producto):
    import numpy as np

    conexion = None
    cursor = None

    try:
        conexion = conectar()
        cursor = conexion.cursor()

        cursor.execute("""
            SELECT
                p.nombre,

                COALESCE(
                    SUM(e.cantidad),
                    0
                ) AS stock_actual

            FROM productos AS p

            LEFT JOIN existencias AS e
                ON e.id_producto = p.id_producto
                AND e.fecha_eliminacion IS NULL

            WHERE
                p.id_producto = ?
                AND p.fecha_eliminacion IS NULL
                AND p.estado = 1

            GROUP BY
                p.nombre;
        """, id_producto)

        producto = cursor.fetchone()

        if producto is None:
            raise ValueError(
                "El producto no existe o está inactivo."
            )

        nombre_producto = producto.nombre
        stock_actual = producto.stock_actual

    finally:
        if cursor is not None:
            cursor.close()

        if conexion is not None:
            conexion.close()

    consumo = obtener_consumo_diario(
        id_producto
    )

    cantidades = [
        registro["cantidad"]
        for registro in consumo
    ]

    return {
        "producto": nombre_producto,
        "stock_actual": stock_actual,
        "dias_analizados": len(cantidades),

        "consumo_promedio_diario": (
            float(np.mean(cantidades))
            if cantidades
            else 0.0
        ),

        "consumo_maximo": (
            max(cantidades)
            if cantidades
            else 0
        ),

        "consumo_minimo": (
            min(cantidades)
            if cantidades
            else 0
        ),

        "consumo_diario": consumo
    }


def _actualizar_alerta(
        id_producto,
        producto,
        dias):

    conexion = None
    cursor = None

    try:
        conexion = conectar()
        cursor = conexion.cursor()

        cursor.execute("""
            SELECT
                id_tipo_alerta

            FROM tipos_alerta

            WHERE
                nombre = 'Próximo a agotarse'
                AND estado = 1
                AND fecha_eliminacion IS NULL;
        """)

        tipo = cursor.fetchone()

        if tipo is None:
            raise ValueError(
                "El tipo de alerta "
                "'Próximo a agotarse' "
                "no existe o está inactivo."
            )

        id_tipo_alerta = tipo.id_tipo_alerta

        if (
            dias is not None
            and dias <= DIAS_ALERTA_AGOTAMIENTO
        ):

            cursor.execute("""
                SELECT 1

                FROM alertas

                WHERE
                    id_producto = ?
                    AND id_tipo_alerta = ?
                    AND atendida = 0
                    AND fecha_eliminacion IS NULL;
            """, id_producto, id_tipo_alerta)

            if cursor.fetchone() is None:

                mensaje = (
                    f"El producto {producto} podría "
                    f"agotarse en aproximadamente "
                    f"{math.ceil(dias)} días."
                )

                cursor.execute("""
                    INSERT INTO alertas (
                        id_tipo_alerta,
                        id_producto,
                        mensaje,
                        nivel,
                        atendida,
                        fecha_creacion
                    )

                    VALUES (
                        ?,
                        ?,
                        ?,
                        'Alta',
                        0,
                        SYSDATETIME()
                    );
                """, id_tipo_alerta, id_producto, mensaje)

        else:

            cursor.execute("""
                UPDATE alertas

                SET
                    atendida = 1,
                    fecha_atencion = SYSDATETIME(),
                    fecha_actualizacion = SYSDATETIME()

                WHERE
                    id_producto = ?
                    AND id_tipo_alerta = ?
                    AND atendida = 0
                    AND fecha_eliminacion IS NULL;
            """, id_producto, id_tipo_alerta)

        conexion.commit()

    except Exception:
        if conexion is not None:
            conexion.rollback()

        raise

    finally:
        if cursor is not None:
            cursor.close()

        if conexion is not None:
            conexion.close()


def predecir_agotamiento(id_producto):
    import numpy as np
    import pandas as pd

    from sklearn.linear_model import LinearRegression

    analisis = analizar_consumo_producto(
        id_producto
    )

    if (
        analisis["dias_analizados"]
        < MINIMO_DIAS_PREDICCION
    ):
        analisis.update({
            "datos_suficientes": False,

            "mensaje": (
                "Datos insuficientes para realizar "
                "una predicción confiable."
            ),

            "dias_restantes_promedio": None,
            "dias_restantes_regresion": None,
            "consumo_tendencia": None,
            "pendiente_regresion": None,
            "estado": "Datos insuficientes"
        })

        return analisis

    df = pd.DataFrame(
        analisis["consumo_diario"]
    )

    promedio = analisis[
        "consumo_promedio_diario"
    ]

    dias_promedio = (
        analisis["stock_actual"] / promedio
        if promedio > 0
        else None
    )

    x = np.arange(
        len(df)
    ).reshape(-1, 1)

    y = df[
        "cantidad"
    ].to_numpy()

    modelo = LinearRegression()

    modelo.fit(
        x,
        y
    )

    consumo_tendencia = max(
        float(
            modelo.predict(
                [[len(df)]]
            )[0]
        ),
        0.0
    )

    dias_regresion = (
        analisis["stock_actual"]
        / consumo_tendencia

        if consumo_tendencia > 0
        else None
    )

    estado = (
        "Próximo a agotarse"

        if (
            dias_promedio is not None
            and dias_promedio
            <= DIAS_ALERTA_AGOTAMIENTO
        )

        else "Sin riesgo próximo"
    )

    analisis.update({
        "datos_suficientes": True,

        "dias_restantes_promedio":
            dias_promedio,

        "dias_restantes_regresion":
            dias_regresion,

        "consumo_tendencia":
            consumo_tendencia,

        "pendiente_regresion":
            float(modelo.coef_[0]),

        "estado":
            estado
    })

    _actualizar_alerta(
        id_producto,
        analisis["producto"],
        dias_promedio
    )

    return analisis
