from core.paths import PROJECT_ROOT
from core.formato_numerico import format_numero
pass
import json
import random
import shutil
import time
from pathlib import Path

from ai.facial.dataset_rostros import cargar_dataset, resumir_dataset
from ai.facial.modelo_cnn import crear_modelo_cnn


BASE_DIR = PROJECT_ROOT
CARPETA_MODELOS = BASE_DIR / "modelos"
RUTA_MODELO = CARPETA_MODELOS / "modelo_rostros.keras"
RUTA_ETIQUETAS = CARPETA_MODELOS / "etiquetas_rostros.json"
RUTA_METRICAS = CARPETA_MODELOS / "metricas_modelo_rostros.json"
RUTA_BACKUP = CARPETA_MODELOS / "modelo_rostros_anterior.keras"
SEMILLA = 42
EPOCAS = 50
ACCURACY_MINIMA_ENTRENAMIENTO = 0.60
ACCURACY_MINIMA_PRUEBA = 0.60


def aumentar_rostro_distante(imagen):
    """Augmentation solo de entrenamiento, moderada y sin modificar datos guardados."""
    import cv2
    import numpy as np
    gris=np.asarray(imagen,np.float32)[...,0]
    if np.random.random()<.5:
        gris=cv2.flip(gris,1)
    matriz=cv2.getRotationMatrix2D((49.5,49.5),np.random.uniform(-7,7),np.random.uniform(.95,1.05))
    gris=cv2.warpAffine(gris,matriz,(100,100),borderMode=cv2.BORDER_REFLECT_101)
    if np.random.random()<.5:
        lado=int(np.random.randint(40,90))
        gris=cv2.resize(cv2.resize(gris,(lado,lado),interpolation=cv2.INTER_AREA),(100,100),interpolation=cv2.INTER_LINEAR)
    if np.random.random()<.25:
        gris=cv2.GaussianBlur(gris,(3,3),.5)
    gris=(gris-.5)*np.random.uniform(.9,1.1)+.5+np.random.uniform(-.06,.06)
    gris+=np.random.normal(0,.008,gris.shape).astype(np.float32)
    return np.clip(gris,0,1).astype(np.float32)[...,None]


def entrenar_modelo_cnn(callback_estado=None):
    import numpy as np
    from matplotlib.figure import Figure
    from sklearn.metrics import (ConfusionMatrixDisplay, classification_report,
                                 confusion_matrix)
    from sklearn.model_selection import train_test_split
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

    if resumen['subjects_sin_imagenes'] or any(n<8 for n in resumen['conteos'].values()):
        raise ValueError('Cada identidad activa necesita al menos ocho imágenes válidas antes de entrenar.')
    estado(f"Dataset: {resumen['subjects']} clases / {resumen['imagenes']} imágenes válidas")
    from ai.facial.cnn_dataset import particionar
    try:indices=particionar(datos)
    except ValueError as error:
        estado(str(error));raise
    it,iv,ie=(indices[k] for k in ('entrenamiento','validacion','evaluacion'))
    x_train,y_train=x[it],y[it];x_val,y_val=x[iv],y[iv];x_temp,y_temp=x[ie],y[ie]

    try:
        import tensorflow as tf
    except ImportError as error:
        raise RuntimeError(
            "TensorFlow no está instalado en .venv. Ejecute: "
            ".venv\\Scripts\\python.exe -m pip install 'tensorflow>=2.16,<2.21'"
        ) from error

    random.seed(SEMILLA); np.random.seed(SEMILLA); tf.random.set_seed(SEMILLA)

    # 3. Crear y entrenar CNN
    estado("Entrenando modelo...")
    modelo = crear_modelo_cnn(resumen["subjects"])
    import tempfile
    checkpoint_directorio=tempfile.TemporaryDirectory(prefix='cnn_mejor_')
    checkpoint=Path(checkpoint_directorio.name)/'mejor.keras'
    callbacks = [
        tf.keras.callbacks.EarlyStopping(monitor="val_loss", patience=8, restore_best_weights=True),
        tf.keras.callbacks.ModelCheckpoint(str(checkpoint),monitor='val_loss',save_best_only=True,mode='min'),
        tf.keras.callbacks.ReduceLROnPlateau(monitor="val_loss", factor=0.5, patience=4, min_lr=1e-6),
    ]
    def augmentation(imagen, etiqueta):
        aumentada=tf.numpy_function(aumentar_rostro_distante,[imagen],tf.float32)
        aumentada.set_shape((100,100,1))
        return aumentada,etiqueta
    entrenamiento=(tf.data.Dataset.from_tensor_slices((x_train,y_train))
                   .shuffle(len(x_train),seed=SEMILLA).map(augmentation,num_parallel_calls=1).batch(16).prefetch(1))
    clases,frecuencias=np.unique(y_train,return_counts=True)
    pesos={int(c):len(y_train)/(len(clases)*int(n)) for c,n in zip(clases,frecuencias)}
    try:
        historia = modelo.fit(entrenamiento, validation_data=(x_val, y_val),class_weight=pesos,
                              epochs=EPOCAS, callbacks=callbacks, verbose=2)
        modelo=tf.keras.models.load_model(checkpoint)
    finally:checkpoint_directorio.cleanup()

    # 4. Evaluar
    estado("Evaluando...")
    loss_train, accuracy_train = modelo.evaluate(x_train, y_train, verbose=0)
    loss_val, accuracy_val = modelo.evaluate(x_val, y_val, verbose=0)
    loss_test, accuracy_test = modelo.evaluate(x_temp, y_temp, verbose=0)
    inicio_inferencia=time.perf_counter()
    predicciones = np.argmax(modelo.predict(x_temp, verbose=0), axis=1)
    inferencia_ms=(time.perf_counter()-inicio_inferencia)*1000/max(len(x_temp),1)
    nombres = [datos["indice_a_subject"][i] for i in range(resumen["subjects"])]
    print(f"Accuracy entrenamiento: {format_numero(accuracy_train)}")
    print(f"Accuracy validación: {format_numero(accuracy_val)}")
    print(f"Accuracy prueba: {format_numero(accuracy_test)}")
    print("\nReporte de clasificación:")
    print(classification_report(y_temp, predicciones, labels=range(len(nombres)),
                                target_names=nombres, zero_division=0))

    # 5. Guardar modelo, etiquetas y gráficas
    CARPETA_MODELOS.mkdir(exist_ok=True)
    modelo_valido = (accuracy_train >= ACCURACY_MINIMA_ENTRENAMIENTO and
                     accuracy_val >= ACCURACY_MINIMA_PRUEBA)
    if modelo_valido:
        from datetime import datetime
        respaldo=CARPETA_MODELOS/'respaldos_cnn'/datetime.now().strftime('%Y%m%d_%H%M%S_%f')
        respaldo.mkdir(parents=True,exist_ok=True)
        for archivo in (RUTA_MODELO,RUTA_ETIQUETAS,RUTA_METRICAS,CARPETA_MODELOS/'particiones_cnn.json',CARPETA_MODELOS/'ai.facial.calibracion_cnn.json'):
            if archivo.is_file():shutil.copy2(archivo,respaldo/archivo.name)
        ruta_temporal = CARPETA_MODELOS / "modelo_rostros_nuevo.keras"
        modelo.save(ruta_temporal)
        if RUTA_MODELO.is_file():
            shutil.copy2(RUTA_MODELO, RUTA_BACKUP)
        ruta_temporal.replace(RUTA_MODELO)
        RUTA_ETIQUETAS.write_text(json.dumps(datos["indice_a_subject"], indent=2), encoding="utf-8")
        from ai.facial.pipeline_facial import sha256,escribir_json_atomico
        from ai.facial.base_facial import PREPROCESAMIENTO_CNN
        from ai.facial.seguridad_cnn import VERSION_PROTOCOLO
        particiones={k:[{campo:datos['metadatos'][i][campo] for campo in ('archivo','sha256','pixeles_sha256','subject','grupo','sesion','session_id','fecha')} for i in ids] for k,ids in indices.items()}
        escribir_json_atomico(CARPETA_MODELOS/'particiones_cnn.json',{'modelo_sha256':sha256(RUTA_MODELO),
            'preprocesamiento':PREPROCESAMIENTO_CNN,'protocolo':VERSION_PROTOCOLO,'particiones':particiones})
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
                 "modelo": str(RUTA_MODELO.relative_to(BASE_DIR)) if modelo_valido else None,
                 "reporte_clasificacion": classification_report(y_temp,predicciones,labels=list(range(len(nombres))),target_names=nombres,zero_division=0,output_dict=True),
                 "matriz_confusion": matriz.tolist(), "inferencia_batch_ms_por_imagen": inferencia_ms,
                 "nota": "Clasificación cerrada por imagen; no mide FAR de desconocidos ni valida vigilancia a distancia."}
    from ai.facial.base_facial import PREPROCESAMIENTO_CNN
    resultado['preprocesamiento']=PREPROCESAMIENTO_CNN
    resultado.update(loss_entrenamiento=float(loss_train),loss_validacion=float(loss_val),loss_evaluacion=float(loss_test),
        grupos_independientes=True,particiones={k:len(ids) for k,ids in indices.items()},pesos_clases=pesos,
        historial={k:list(map(float,v)) for k,v in historia.history.items()})
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
    pass
    try:
        pass
        entrenar_modelo_cnn()
    except (PermissionError, RuntimeError, FileNotFoundError, ValueError) as error:
        print(f"ERROR: {error}")
