import json
import random
import shutil
from pathlib import Path

from dataset_rostros import cargar_dataset, resumir_dataset
from modelo_cnn import crear_modelo_cnn


BASE_DIR = Path(__file__).resolve().parent
CARPETA_MODELOS = BASE_DIR / "modelos"
RUTA_MODELO = CARPETA_MODELOS / "modelo_rostros.keras"
RUTA_ETIQUETAS = CARPETA_MODELOS / "etiquetas_rostros.json"
RUTA_METRICAS = CARPETA_MODELOS / "metricas_modelo_rostros.json"
RUTA_BACKUP = CARPETA_MODELOS / "modelo_rostros_anterior.keras"
SEMILLA = 42
EPOCAS = 50
ACCURACY_MINIMA_ENTRENAMIENTO = 0.60
ACCURACY_MINIMA_PRUEBA = 0.60


def entrenar_modelo_cnn(callback_estado=None):
    import numpy as np
    from matplotlib.figure import Figure
    from sklearn.metrics import (ConfusionMatrixDisplay, classification_report,
                                 confusion_matrix)
    from sklearn.model_selection import train_test_split
    try:
        import tensorflow as tf
    except ImportError as error:
        raise RuntimeError(
            "TensorFlow no está instalado en .venv. Ejecute: "
            ".venv\\Scripts\\python.exe -m pip install 'tensorflow>=2.16,<2.21'"
        ) from error

    random.seed(SEMILLA); np.random.seed(SEMILLA); tf.random.set_seed(SEMILLA)

    def estado(mensaje):
        if callback_estado:
            callback_estado(mensaje)

    # 1. Cargar dataset
    estado("Preparando dataset...")
    datos = cargar_dataset(); resumen = resumir_dataset(datos)
    x, y = datos["X"], datos["y"]
    print(f"Imágenes: {resumen['imagenes']} | Subjects: {resumen['subjects']}")
    print(f"Subjects activos SQL: {len(resumen['subjects_activos_sql'])} {resumen['subjects_activos_sql']}")
    print(f"Subjects encontrados dataset: {len(resumen['subjects_encontrados_dataset'])}")
    print(f"Archivos dataset encontrados: {resumen['archivos_dataset_encontrados']}")
    print(f"Subjects utilizados: {resumen['subjects']} | Archivos utilizados: {resumen['imagenes']}")
    for subject in resumen['subjects_sin_imagenes']:
        print(f"ADVERTENCIA: {subject} no tiene imágenes disponibles.")
    print(f"Shape X: {x.shape} | Shape y: {y.shape}")

    # 2. Separar 80% para desarrollo y 20% para prueba
    x_train, x_temp, y_train, y_temp = train_test_split(
        x, y, test_size=0.20, random_state=SEMILLA, stratify=y)
    x_train, x_val, y_train, y_val = train_test_split(
        x_train, y_train, test_size=0.20, random_state=SEMILLA, stratify=y_train)

    # 3. Crear y entrenar CNN
    estado("Entrenando modelo...")
    modelo = crear_modelo_cnn(resumen["subjects"])
    callbacks = [
        tf.keras.callbacks.EarlyStopping(monitor="val_loss", patience=8, restore_best_weights=True),
        tf.keras.callbacks.ReduceLROnPlateau(monitor="val_loss", factor=0.5, patience=4, min_lr=1e-6),
    ]
    historia = modelo.fit(x_train, y_train, validation_data=(x_val, y_val),
                          epochs=EPOCAS, batch_size=16, callbacks=callbacks, verbose=2)

    # 4. Evaluar
    estado("Evaluando...")
    _, accuracy_train = modelo.evaluate(x_train, y_train, verbose=0)
    _, accuracy_val = modelo.evaluate(x_val, y_val, verbose=0)
    _, accuracy_test = modelo.evaluate(x_temp, y_temp, verbose=0)
    predicciones = np.argmax(modelo.predict(x_temp, verbose=0), axis=1)
    nombres = [datos["indice_a_subject"][i] for i in range(resumen["subjects"])]
    print(f"Accuracy entrenamiento: {accuracy_train:.4f}")
    print(f"Accuracy validación: {accuracy_val:.4f}")
    print(f"Accuracy prueba: {accuracy_test:.4f}")
    print("\nReporte de clasificación:")
    print(classification_report(y_temp, predicciones, labels=range(len(nombres)),
                                target_names=nombres, zero_division=0))

    # 5. Guardar modelo, etiquetas y gráficas
    CARPETA_MODELOS.mkdir(exist_ok=True)
    modelo_valido = (accuracy_train >= ACCURACY_MINIMA_ENTRENAMIENTO and
                     accuracy_test >= ACCURACY_MINIMA_PRUEBA)
    if modelo_valido:
        ruta_temporal = CARPETA_MODELOS / "modelo_rostros_nuevo.keras"
        modelo.save(ruta_temporal)
        if RUTA_MODELO.is_file():
            shutil.copy2(RUTA_MODELO, RUTA_BACKUP)
        ruta_temporal.replace(RUTA_MODELO)
        RUTA_ETIQUETAS.write_text(json.dumps(datos["indice_a_subject"], indent=2), encoding="utf-8")
    matriz = confusion_matrix(y_temp, predicciones, labels=range(len(nombres)))
    figura = Figure(figsize=(10, 9))
    eje = figura.subplots()
    ConfusionMatrixDisplay(matriz, display_labels=nombres).plot(ax=eje, xticks_rotation=45, colorbar=False)
    figura.tight_layout(); figura.savefig(CARPETA_MODELOS / "matriz_confusion_rostros.png", dpi=150)

    figura = Figure(figsize=(11, 4))
    ejes = figura.subplots(1, 2)
    ejes[0].plot(historia.history["accuracy"], label="Entrenamiento")
    ejes[0].plot(historia.history["val_accuracy"], label="Validación")
    ejes[0].set_title("Accuracy"); ejes[0].set_xlabel("Época"); ejes[0].legend()
    ejes[1].plot(historia.history["loss"], label="Entrenamiento")
    ejes[1].plot(historia.history["val_loss"], label="Validación")
    ejes[1].set_title("Loss"); ejes[1].set_xlabel("Época"); ejes[1].legend()
    figura.tight_layout(); figura.savefig(CARPETA_MODELOS / "entrenamiento_rostros.png", dpi=150)
    resultado = {"modelo_valido": modelo_valido, "accuracy_entrenamiento": float(accuracy_train),
                 "accuracy_validacion": float(accuracy_val), "accuracy_prueba": float(accuracy_test),
                 "imagenes": resumen["imagenes"], "subjects": resumen["subjects"],
                 "modelo": str(RUTA_MODELO.relative_to(BASE_DIR)) if modelo_valido else None}
    if modelo_valido:
        RUTA_METRICAS.write_text(json.dumps(resultado, indent=2), encoding="utf-8")
        estado("Modelo entrenado correctamente.")
        print(f"Modelo guardado en: {RUTA_MODELO}")
    else:
        estado("El modelo no aprendió correctamente.")
        print("El modelo no aprendió correctamente y no se reemplazó el modelo anterior.")
    return resultado


def probar_modelo_con_dataset():
    """Devuelve una predicción diagnóstica por cada subject."""
    import tensorflow as tf
    import numpy as np
    datos = cargar_dataset()
    modelo = tf.keras.models.load_model(RUTA_MODELO)
    resultados, vistos = [], set()
    for indice, archivo in enumerate(datos["archivos"]):
        real = datos["indice_a_subject"][int(datos["y"][indice])]
        if real in vistos:
            continue
        vistos.add(real)
        probabilidades = modelo.predict(datos["X"][indice:indice+1], verbose=0)[0]
        predicha = datos["indice_a_subject"][int(np.argmax(probabilidades))]
        resultados.append({"archivo": Path(archivo).name, "clase_real": real,
                           "clase_predicha": predicha,
                           "confianza": float(np.max(probabilidades))})
    return resultados


def evaluar_modelo_por_subject():
    """Evalúa todas las imágenes y resume aciertos por persona."""
    import tensorflow as tf
    import numpy as np
    datos = cargar_dataset()
    modelo = tf.keras.models.load_model(RUTA_MODELO)
    predicciones = np.argmax(modelo.predict(datos["X"], verbose=0), axis=1)
    resumen = {}
    for subject, indice in datos["subject_a_indice"].items():
        mascara = datos["y"] == indice
        resumen[subject] = {"correctas": int(np.sum(predicciones[mascara] == indice)),
                            "total": int(np.sum(mascara))}
    return resumen


if __name__ == "__main__":
    try:
        entrenar_modelo_cnn()
    except (RuntimeError, FileNotFoundError, ValueError) as error:
        print(f"ERROR: {error}")
