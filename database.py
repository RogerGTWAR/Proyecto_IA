import traceback

import pyodbc


SERVER = r"MSI\SQLSERVER"
DATABASE = "InventarioIA2"
DRIVER = "{ODBC Driver 17 for SQL Server}"


def conectar():
    """Abre una conexión local a SQL Server con autenticación de Windows."""
    cadena_conexion = (
        f"DRIVER={DRIVER};"
        f"SERVER={SERVER};"
        f"DATABASE={DATABASE};"
        "Trusted_Connection=yes;"
        "Encrypt=no;"
        "TrustServerCertificate=yes;"
    )
    try:
        return pyodbc.connect(cadena_conexion, timeout=5)
    except pyodbc.Error as error:
        raise ConnectionError(
            f"No fue posible conectar con SQL Server local {SERVER}, base {DATABASE}.\n"
            f"Error original: {error}"
        ) from error


def probar_conexion():
    """Prueba la conexión y muestra el servidor y la base local en uso."""
    conexion = None
    cursor = None
    try:
        conexion = conectar()
        cursor = conexion.cursor()
        cursor.execute("SELECT @@SERVERNAME, DB_NAME();")
        servidor, base = cursor.fetchone()
        print("\n==============================")
        print("CONEXIÓN CORRECTA")
        print("==============================")
        print("Servidor:", servidor)
        print("Base:", base)
        print("==============================\n")
        return True
    except Exception as error:
        print("\n==============================")
        print("ERROR DE CONEXIÓN")
        print("==============================")
        print("Tipo:", type(error).__name__)
        print("Detalle:", error)
        print("==============================\n")
        traceback.print_exc()
        return False
    finally:
        if cursor is not None:
            cursor.close()
        if conexion is not None:
            conexion.close()


if __name__ == "__main__":
    probar_conexion()
