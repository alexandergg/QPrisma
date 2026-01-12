"""
Test rápido de endpoints FFmpeg
"""

import requests

API_URL = "http://localhost:8000"


def test_presets():
    """Test endpoint de presets"""
    print("=" * 50)
    print("TEST: GET /presets")
    print("=" * 50)

    response = requests.get(f"{API_URL}/presets")
    print(f"Status: {response.status_code}")

    if response.status_code == 200:
        data = response.json()
        print(f"\n✅ {len(data['presets'])} presets disponibles:\n")
        for preset in data["presets"]:
            print(f"📌 {preset['name'].upper()}")
            print(f"   {preset['description']}")
            print(f"   Config: {preset['config']}")
            print()
    else:
        print(f"❌ Error: {response.text}")


def test_pipeline_preview(preset="balanced"):
    """Test endpoint de pipeline preview"""
    print("=" * 50)
    print(f"TEST: GET /pipeline/preview?preset={preset}")
    print("=" * 50)

    response = requests.get(f"{API_URL}/pipeline/preview", params={"preset": preset})
    print(f"Status: {response.status_code}")

    if response.status_code == 200:
        data = response.json()
        print("\n✅ Pipeline preview obtenido:")
        print(f"   Nodos: {len(data['nodes'])}")
        print(f"   Conexiones: {len(data['edges'])}")
        print("\n   Nodos del pipeline:")
        for node in data["nodes"]:
            print(
                f"   - {node['data']['icon']} {node['data']['label']}: {node['data']['description']}"
            )
        print()
    else:
        print(f"❌ Error: {response.text}")


def test_health():
    """Test health check"""
    print("=" * 50)
    print("TEST: GET /health")
    print("=" * 50)

    response = requests.get(f"{API_URL}/health")
    print(f"Status: {response.status_code}")

    if response.status_code == 200:
        data = response.json()
        print("\n✅ Services:")
        for service, status in data["services"].items():
            icon = "✓" if status == "configured" or status == "healthy" else "✗"
            print(f"   {icon} {service}: {status}")
        print()
    else:
        print(f"❌ Error: {response.text}")


if __name__ == "__main__":
    try:
        test_health()
        test_presets()
        test_pipeline_preview("balanced")
        test_pipeline_preview("fast_preview")
        test_pipeline_preview("high_quality")

        print("=" * 50)
        print("✅ Todos los tests completados")
        print("=" * 50)
        print()
        print("🌐 Abrir frontend: http://localhost:3000")
        print("📚 Abrir API docs: http://localhost:8000/docs")

    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback

        traceback.print_exc()
