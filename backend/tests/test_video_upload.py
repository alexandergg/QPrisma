"""
Test completo del flujo de procesamiento de video:
1. Upload video
2. Process con FFmpeg
3. Verificar resultados
"""

import time
from pathlib import Path

import requests

API_URL = "http://localhost:8000"


def test_video_upload_and_processing():
    """Test completo del flujo de upload y procesamiento"""

    print("=" * 70)
    print("🎬 TEST COMPLETO: Upload y Procesamiento de Video con FFmpeg")
    print("=" * 70)

    # 1. Verificar que el API esté corriendo
    print("\n1️⃣ Verificando API...")
    try:
        response = requests.get(f"{API_URL}/health", timeout=5)
        health = response.json()
        print(f"   ✓ API Status: {health['services']['api']}")
        print(f"   ✓ OpenAI: {health['services']['openai']}")
        print(f"   ✓ Blob Storage: {health['services']['blob_storage']}")
        print(f"   ✓ Cosmos DB: {health['services']['cosmos_db']}")
    except Exception as e:
        print(f"   ✗ Error: API no disponible - {e}")
        print(
            "   💡 Asegúrate de que el backend esté corriendo: cd backend && uv run python api/main.py"
        )
        return

    # 2. Verificar que existe el video de prueba
    print("\n2️⃣ Verificando video de prueba...")
    test_video = Path("test_data/test_video.mp4")

    if not test_video.exists():
        print(f"   ⚠ Video de prueba no encontrado: {test_video}")
        print("   💡 Generando video de prueba...")
        import subprocess

        result = subprocess.run(
            ["uv", "run", "python", "create_test_video.py"], capture_output=True, text=True
        )
        if result.returncode == 0:
            print("   ✓ Video de prueba generado")
        else:
            print(f"   ✗ Error generando video: {result.stderr}")
            return

    file_size = test_video.stat().st_size / (1024 * 1024)
    print(f"   ✓ Video encontrado: {test_video}")
    print(f"   ✓ Tamaño: {file_size:.2f} MB")

    # 3. Upload del video
    print("\n3️⃣ Subiendo video al servidor...")
    try:
        with open(test_video, "rb") as f:
            files = {"file": (test_video.name, f, "video/mp4")}
            response = requests.post(f"{API_URL}/upload", files=files, timeout=120)

        if response.status_code == 200:
            upload_result = response.json()
            media_id = upload_result["media_id"]
            blob_name = upload_result["blob_name"]
            print("   ✓ Video subido exitosamente!")
            print(f"   ✓ Media ID: {media_id}")
            print(f"   ✓ Blob Name: {blob_name}")
        else:
            print(f"   ✗ Error en upload: {response.status_code}")
            print(f"   {response.text}")
            return
    except Exception as e:
        print(f"   ✗ Error: {e}")
        return

    # 4. Esperar un poco para que el background task procese
    print("\n4️⃣ Esperando procesamiento inicial (background task)...")
    time.sleep(3)

    # 5. Listar presets disponibles
    print("\n5️⃣ Verificando presets disponibles...")
    try:
        response = requests.get(f"{API_URL}/presets")
        presets = response.json()["presets"]
        print(f"   ✓ {len(presets)} presets disponibles:")
        for preset in presets[:3]:  # Mostrar solo los primeros 3
            print(f"      • {preset['name']}: {preset['description']}")
    except Exception as e:
        print(f"   ✗ Error: {e}")

    # 6. Procesar video con FFmpeg usando preset "balanced"
    print("\n6️⃣ Procesando video con FFmpeg (preset: balanced)...")
    try:
        response = requests.post(
            f"{API_URL}/process/video/ffmpeg",
            params={"media_id": media_id, "preset": "balanced"},
            timeout=60,
        )

        if response.status_code == 200:
            result = response.json()
            print("   ✓ Procesamiento iniciado!")
            print(f"   ✓ Status: {result['status']}")
            print(f"   ✓ Message: {result['message']}")
        else:
            print(f"   ✗ Error: {response.status_code}")
            print(f"   {response.text}")
            return
    except Exception as e:
        print(f"   ✗ Error: {e}")
        return

    # 7. Verificar pipeline preview
    print("\n7️⃣ Obteniendo preview del pipeline...")
    try:
        response = requests.get(f"{API_URL}/pipeline/preview", params={"preset": "balanced"})

        if response.status_code == 200:
            pipeline = response.json()
            nodes = pipeline["pipeline"]["nodes"]
            connections = pipeline["pipeline"]["connections"]
            print("   ✓ Pipeline generado:")
            print(f"      • Nodos: {len(nodes)}")
            print(f"      • Conexiones: {len(connections)}")
            print(
                f"      • Config: {pipeline['config']['extraction']['method']} @ {pipeline['config']['extraction']['max_frames']} frames"
            )
        else:
            print("   ⚠ No se pudo obtener pipeline preview")
    except Exception as e:
        print(f"   ⚠ Error: {e}")

    # 8. Resumen final
    print("\n" + "=" * 70)
    print("✅ TEST COMPLETADO")
    print("=" * 70)
    print("\n📊 Resumen:")
    print(f"   • Video ID: {media_id}")
    print(f"   • Archivo: {blob_name}")
    print(f"   • Tamaño: {file_size:.2f} MB")
    print("   • Preset usado: balanced")
    print("\n💡 Próximos pasos:")
    print("   1. Abre el frontend: http://localhost:3000")
    print("   2. Ve a la pestaña 'Procesar Video'")
    print(f"   3. Sube el video: {test_video.absolute()}")
    print("   4. Observa el procesamiento en tiempo real")
    print("\n🔍 Para ver los resultados en Azure:")
    print(f"   • Cosmos DB: Busca el documento con id='{media_id}'")
    print(f"   • Knowledge Graph (Neo4j): Busca frames con media_id='{media_id}'")
    print(f"   • Blob Storage: Busca el blob '{blob_name}'")

    return media_id


def test_search_processed_video(media_id: str):
    """Test de búsqueda de video procesado"""
    print(f"\n🔍 Buscando frames del video {media_id}...")

    try:
        # Buscar en el índice
        response = requests.post(f"{API_URL}/search", json={"query": "video frame", "top_k": 5})

        if response.status_code == 200:
            results = response.json()
            print(f"   ✓ {len(results.get('results', []))} resultados encontrados")

            # Filtrar por media_id
            video_frames = [r for r in results.get("results", []) if r.get("media_id") == media_id]
            print(f"   ✓ {len(video_frames)} frames de este video")

            if video_frames:
                print("\n   Primeros frames encontrados:")
                for i, frame in enumerate(video_frames[:3], 1):
                    print(
                        f"      {i}. Frame {frame.get('frame_index', 'N/A')} - Score: {frame.get('score', 0):.3f}"
                    )
        else:
            print(f"   ⚠ Error en búsqueda: {response.status_code}")
    except Exception as e:
        print(f"   ⚠ Error: {e}")


if __name__ == "__main__":
    media_id = test_video_upload_and_processing()

    if media_id:
        print("\n" + "=" * 70)
        input("Presiona Enter para probar la búsqueda de los frames procesados...")
        test_search_processed_video(media_id)
