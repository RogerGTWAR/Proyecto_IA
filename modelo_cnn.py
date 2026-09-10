from dataset_rostros import TAMANO_IMAGEN


def crear_modelo_cnn(cantidad_clases):
    import tensorflow as tf

    modelo = tf.keras.Sequential([
        tf.keras.layers.Input(shape=(*TAMANO_IMAGEN, 1)),
        tf.keras.layers.Conv2D(16, 3, activation="relu", padding="same"),
        tf.keras.layers.MaxPooling2D(),
        tf.keras.layers.Conv2D(32, 3, activation="relu", padding="same"),
        tf.keras.layers.MaxPooling2D(),
        tf.keras.layers.Conv2D(64, 3, activation="relu", padding="same"),
        tf.keras.layers.MaxPooling2D(),
        tf.keras.layers.Flatten(),
        tf.keras.layers.Dense(64, activation="relu"),
        tf.keras.layers.Dropout(0.3),
        tf.keras.layers.Dense(cantidad_clases, activation="softmax"),
    ], name="cnn_reconocimiento_rostros")
    modelo.compile(optimizer=tf.keras.optimizers.Adam(learning_rate=0.001),
                   loss="sparse_categorical_crossentropy", metrics=["accuracy"])
    return modelo
