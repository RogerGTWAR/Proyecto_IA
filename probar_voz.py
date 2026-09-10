import time

from agente_inventario import procesar_pregunta
from asistente_voz import (cargar_modelo_voz, escuchar_pregunta, hablar,
                           listar_dispositivos_audio,
                           obtener_ultimas_metricas,
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
    inicio = time.perf_counter()
    respuesta = procesar_pregunta(texto)
    tiempo_jarvis = time.perf_counter() - inicio
    print(f"\n5. Respuesta sin TTS ({tiempo_jarvis:.3f} s):\n{respuesta}")
    print("\n6. Probando edge-tts y parlantes...")
    try:
        motor = hablar(respuesta)
    except RuntimeError as error:
        print(f"ERROR: {error}")
        return
    print(f"Motor utilizado: {motor}")
    print("Métricas:")
    for nombre, valor in obtener_ultimas_metricas().items():
        print(f"- {nombre}: {valor:.3f} s" if isinstance(valor, float) else f"- {nombre}: {valor}")
    print("Prueba de voz completada correctamente.")


if __name__ == "__main__":
    probar_voz()
