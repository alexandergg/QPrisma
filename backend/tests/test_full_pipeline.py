"""
Script de prueba completo para QPrisma
Prueba upload, procesamiento, búsqueda y chat
"""

import os
import time

import pytest
import requests

if os.getenv("RUN_E2E_TESTS", "").lower() not in {"1", "true", "yes"}:
    pytest.skip(
        "Manual full-pipeline checks are disabled. Set RUN_E2E_TESTS=true to enable.",
        allow_module_level=True,
    )

API_URL = "http://localhost:8000"


def print_header(text):
    print("\n" + "=" * 60)
    print(f"  {text}")
    print("=" * 60)


def print_success(text):
    print(f"✅ {text}")


def print_info(text):
    print(f"ℹ️  {text}")


def print_error(text):
    print(f"❌ {text}")


def test_upload_image():
    """Test 1: Subir una imagen de prueba"""
    print_header("Test 1: Upload de Imagen")

    # Crear una imagen de prueba simple (1x1 pixel PNG)
    import io

    from PIL import Image

    img = Image.new("RGB", (100, 100), color="blue")
    img_bytes = io.BytesIO()
    img.save(img_bytes, format="PNG")
    img_bytes.seek(0)

    files = {"file": ("test_image.png", img_bytes, "image/png")}

    try:
        response = requests.post(f"{API_URL}/upload", files=files)
        response.raise_for_status()
        data = response.json()

        print_success("Imagen subida correctamente")
        print_info(f"Media ID: {data['media_id']}")
        print_info(f"Tipo: {data['media_type']}")
        print_info(f"Tamaño: {data['file_size']} bytes")

        return data["media_id"]

    except Exception as e:
        print_error(f"Error en upload: {e}")
        return None


def test_get_metadata(media_id):
    """Test 2: Obtener metadatos"""
    print_header("Test 2: Obtener Metadatos")

    if not media_id:
        print_error("No hay media_id para consultar")
        return False

    try:
        # Esperar un poco para que se procese
        print_info("Esperando procesamiento (10 segundos)...")
        time.sleep(10)

        response = requests.get(f"{API_URL}/media/{media_id}")
        response.raise_for_status()
        data = response.json()

        print_success("Metadatos obtenidos")
        print_info(f"Filename: {data.get('original_filename')}")
        print_info(f"Procesado: {data.get('processed', False)}")

        if data.get("processed"):
            result = data.get("processing_result", {})
            print_info(f"Frames analizados: {result.get('frames_analyzed', 'N/A')}")
            print_info(f"Tokens usados: {result.get('tokens_used', 'N/A')}")

        return True

    except Exception as e:
        print_error(f"Error obteniendo metadatos: {e}")
        return False


def test_search(query="blue image"):
    """Test 3: Búsqueda vectorial"""
    print_header("Test 3: Búsqueda Vectorial")

    try:
        payload = {"query": query, "top": 5}

        response = requests.post(f"{API_URL}/search", json=payload)
        response.raise_for_status()
        data = response.json()

        print_success(f"Búsqueda ejecutada: '{query}'")
        print_info(f"Resultados encontrados: {data['results_count']}")

        for i, result in enumerate(data.get("results", []), 1):
            print(f"\n  Resultado {i}:")
            print(f"    Media ID: {result.get('media_id')}")
            print(f"    Tipo: {result.get('media_type')}")
            print(f"    Score: {result.get('score', 0):.3f}")
            print(f"    Contenido: {result.get('content', '')[:100]}...")

        return True

    except Exception as e:
        print_error(f"Error en búsqueda: {e}")
        return False


def test_chat(media_id=None, message="¿Qué hay en esta imagen?"):
    """Test 4: Chat con contexto"""
    print_header("Test 4: Chat con RAG")

    try:
        payload = {"message": message, "media_id": media_id}

        response = requests.post(f"{API_URL}/chat", json=payload)
        response.raise_for_status()
        data = response.json()

        print_success("Chat ejecutado")
        print_info(f"Modelo: {data.get('model')}")
        print_info(f"Tokens usados: {data.get('tokens_used')}")
        print_info(f"Contexto usado: {data.get('context_used', False)}")
        print("\n  Respuesta:")
        print(f"  {data.get('response')}\n")

        return True

    except Exception as e:
        print_error(f"Error en chat: {e}")
        return False


def test_chat_general():
    """Test 5: Chat sin contexto específico"""
    print_header("Test 5: Chat General")

    try:
        payload = {"message": "¿Qué es QPrisma y qué puede hacer?"}

        response = requests.post(f"{API_URL}/chat", json=payload)
        response.raise_for_status()
        data = response.json()

        print_success("Chat general ejecutado")
        print("\n  Respuesta:")
        print(f"  {data.get('response')}\n")

        return True

    except Exception as e:
        print_error(f"Error en chat general: {e}")
        return False


def main():
    print_header("🚀 QPrisma - Suite de Pruebas Completa")

    # Test 1: Upload
    media_id = test_upload_image()

    # Test 2: Metadata
    if media_id:
        test_get_metadata(media_id)

    # Test 3: Search
    test_search("imagen azul")

    # Test 4: Chat con contexto
    if media_id:
        test_chat(media_id, "Describe esta imagen en detalle")

    # Test 5: Chat general
    test_chat_general()

    print_header("✨ Tests Completados")
