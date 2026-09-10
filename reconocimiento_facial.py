from pathlib import Path

import cv2
import numpy as np

from database import conectar


UMBRAL_RECONOCIMIENTO = 70
CANTIDAD_IMAGENES = 30
TAMANO_ROSTRO = (200, 200)
CARPETA_ROSTROS = Path(__file__).parent / "rostros"
CARPETA_MODELOS = Path(__file__).parent / "modelos"
ARCHIVO_MODELO = CARPETA_MODELOS / "modelo_lbph.yml"


def listar_empleados():
    conexion = conectar(); cursor = conexion.cursor()
    try:
        cursor.execute("""SELECT id_empleado, codigo_empleado, nombres, apellidos, cargo,
                           CASE WHEN estado=1 THEN 'Activo' ELSE 'Inactivo' END AS estado
                           FROM empleados WHERE fecha_eliminacion IS NULL AND estado=1
                           ORDER BY nombres, apellidos;""")
        columnas = [c[0] for c in cursor.description]
        return [dict(zip(columnas, fila)) for fila in cursor.fetchall()]
    finally:
        cursor.close(); conexion.close()


def _obtener_empleado(id_empleado, solo_activo=True):
    conexion = conectar(); cursor = conexion.cursor()
    try:
        cursor.execute("""SELECT id_empleado, codigo_empleado, nombres, apellidos, cargo, estado
                           FROM empleados WHERE id_empleado = ? AND fecha_eliminacion IS NULL;""", id_empleado)
        fila = cursor.fetchone()
        if fila is None: raise ValueError("El empleado no existe.")
        if solo_activo and not fila.estado: raise ValueError("El empleado está inactivo.")
        return {"id_empleado": fila.id_empleado, "codigo_empleado": fila.codigo_empleado,
                "nombres": fila.nombres, "apellidos": fila.apellidos,
                "cargo": fila.cargo, "estado": bool(fila.estado)}
    finally:
        cursor.close(); conexion.close()


def _detector():
    ruta = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
    detector = cv2.CascadeClassifier(ruta)
    if detector.empty(): raise RuntimeError("No se pudo cargar el detector Haar Cascade.")
    return detector


def capturar_rostro_empleado(id_empleado):
    empleado = _obtener_empleado(id_empleado)
    carpeta = CARPETA_ROSTROS / f"empleado_{id_empleado}"
    carpeta.mkdir(parents=True, exist_ok=True)
    camara = cv2.VideoCapture(0)
    if not camara.isOpened(): raise RuntimeError("No se pudo abrir la cámara.")
    detector = _detector(); capturadas = 0; ciclos = 0
    try:
        while capturadas < CANTIDAD_IMAGENES:
            correcto, cuadro = camara.read()
            if not correcto: raise RuntimeError("No se pudo leer una imagen de la cámara.")
            gris = cv2.cvtColor(cuadro, cv2.COLOR_BGR2GRAY)
            rostros = detector.detectMultiScale(gris, scaleFactor=1.2, minNeighbors=5, minSize=(80, 80))
            for x, y, ancho, alto in rostros[:1]:
                ciclos += 1
                cv2.rectangle(cuadro, (x, y), (x + ancho, y + alto), (0, 180, 0), 2)
                if ciclos % 3 == 0:
                    rostro = cv2.resize(gris[y:y + alto, x:x + ancho], TAMANO_ROSTRO)
                    capturadas += 1
                    cv2.imwrite(str(carpeta / f"rostro_{capturadas}.jpg"), rostro)
            cv2.putText(cuadro, f"Imagenes: {capturadas}/{CANTIDAD_IMAGENES} - ESC cancela",
                        (15, 30), cv2.FONT_HERSHEY_SIMPLEX, .7, (0, 255, 0), 2)
            cv2.imshow(f"Registro facial - {empleado['nombres']} {empleado['apellidos']}", cuadro)
            if cv2.waitKey(1) & 0xFF == 27: break
        return capturadas
    finally:
        camara.release(); cv2.destroyAllWindows()


def entrenar_modelo_facial():
    if not hasattr(cv2, "face"):
        raise RuntimeError("LBPH requiere opencv-contrib-python.")
    imagenes, etiquetas = [], []
    if CARPETA_ROSTROS.exists():
        for carpeta in CARPETA_ROSTROS.glob("empleado_*"):
            try: id_empleado = int(carpeta.name.split("_")[1])
            except (IndexError, ValueError): continue
            for archivo in carpeta.glob("*.jpg"):
                imagen = cv2.imread(str(archivo), cv2.IMREAD_GRAYSCALE)
                if imagen is not None:
                    imagenes.append(cv2.resize(imagen, TAMANO_ROSTRO)); etiquetas.append(id_empleado)
    if not imagenes: raise ValueError("No existen imágenes faciales para entrenar.")
    modelo = cv2.face.LBPHFaceRecognizer_create()
    modelo.train(imagenes, np.array(etiquetas, dtype=np.int32))
    CARPETA_MODELOS.mkdir(parents=True, exist_ok=True); modelo.write(str(ARCHIVO_MODELO))
    return {"imagenes": len(imagenes), "empleados": len(set(etiquetas)), "archivo": str(ARCHIVO_MODELO)}


def reconocer_empleado():
    if not ARCHIVO_MODELO.exists(): raise ValueError("Primero debe entrenar el modelo facial.")
    if not hasattr(cv2, "face"): raise RuntimeError("LBPH requiere opencv-contrib-python.")
    modelo = cv2.face.LBPHFaceRecognizer_create(); modelo.read(str(ARCHIVO_MODELO))
    detector = _detector(); camara = cv2.VideoCapture(0)
    if not camara.isOpened(): raise RuntimeError("No se pudo abrir la cámara.")
    reconocido = None; confirmaciones = 0
    try:
        while True:
            correcto, cuadro = camara.read()
            if not correcto: break
            gris = cv2.cvtColor(cuadro, cv2.COLOR_BGR2GRAY)
            rostros = detector.detectMultiScale(gris, 1.2, 5, minSize=(80, 80))
            for x, y, ancho, alto in rostros[:1]:
                rostro = cv2.resize(gris[y:y + alto, x:x + ancho], TAMANO_ROSTRO)
                etiqueta, distancia = modelo.predict(rostro)
                texto = "Empleado desconocido"; color = (0, 0, 255)
                if distancia <= UMBRAL_RECONOCIMIENTO:
                    try: empleado = _obtener_empleado(etiqueta)
                    except ValueError: empleado = None
                    if empleado:
                        texto = f"{empleado['nombres']} {empleado['apellidos']}"; color = (0, 200, 0)
                        reconocido = empleado; reconocido["confianza"] = float(distancia); confirmaciones += 1
                else: reconocido = None; confirmaciones = 0
                cv2.rectangle(cuadro, (x, y), (x + ancho, y + alto), color, 2)
                cv2.putText(cuadro, texto, (x, max(25, y - 10)), cv2.FONT_HERSHEY_SIMPLEX, .7, color, 2)
            cv2.imshow("Reconocimiento - ESC cancela", cuadro)
            if confirmaciones >= 5: return reconocido
            if cv2.waitKey(1) & 0xFF == 27: return None
        return None
    finally:
        camara.release(); cv2.destroyAllWindows()
