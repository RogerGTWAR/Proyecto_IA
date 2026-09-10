from asistente_voz import (cargar_modelo_voz, escuchar_pregunta, hablar,
                           listar_dispositivos_audio,
                           obtener_microfono_predeterminado,
                           obtener_ruta_modelo)


def probar_voz():
    print("1. Verificando Vosk...")
    try:
        import vosk  # noqa: F401
    except ImportError:
        print("ERROR: Vosk no está instalado.")
        print("Ejecute: python -m pip install -r requirements.txt")
        return
    print("Vosk está instalado.")
    print("\n2. Verificando modelo...")
    try:
        ruta = obtener_ruta_modelo()
        print(f"Ruta: {ruta}\nModelo Vosk encontrado.")
        cargar_modelo_voz()
    except RuntimeError as error:
        print(f"ERROR: {error}")
        return
    print("Modelo cargado correctamente.")
    print("\n3. Dispositivos de audio:")
    try:
        for indice, dispositivo in enumerate(listar_dispositivos_audio()):
            print(f"[{indice}] {dispositivo['name']} | entradas: {dispositivo['max_input_channels']} | salidas: {dispositivo['max_output_channels']}")
        microfono = obtener_microfono_predeterminado()
    except RuntimeError as error:
        print(f"ERROR: {error}")
        return
    print(f"\nMicrófono: [{microfono['indice']}] {microfono['nombre']}")
    print("\n4. Di una frase corta (máximo 10 segundos)...")
    try:
        texto = escuchar_pregunta()
    except RuntimeError as error:
        print(f"ERROR: {error}")
        return
    print(f"\nTexto reconocido:\n{texto}")
    print("\n5. Probando parlantes...")
    try:
        hablar(f"Texto reconocido: {texto}")
    except RuntimeError as error:
        print(f"ERROR: {error}")
        return
    print("Prueba de voz completada correctamente.")


if __name__ == "__main__":
    probar_voz()
