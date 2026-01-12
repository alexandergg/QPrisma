"""Test rápido de chat"""

import requests

API_URL = "http://localhost:8000"

print("Test 1: Chat simple sin contexto")
try:
    response = requests.post(
        f"{API_URL}/chat", json={"message": "Hola, di 'test exitoso' en español"}
    )
    print(f"Status: {response.status_code}")
    if response.status_code == 200:
        data = response.json()
        print(f"✓ Respuesta: {data['response']}")
        print(f"  Tokens: {data['tokens_used']}")
    else:
        print(f"✗ Error: {response.text}")
except Exception as e:
    print(f"✗ Exception: {e}")

print("\nTest 2: Chat con media_id inexistente")
try:
    response = requests.post(
        f"{API_URL}/chat", json={"message": "¿Qué ves en la imagen?", "media_id": "test-id-123"}
    )
    print(f"Status: {response.status_code}")
    if response.status_code == 200:
        data = response.json()
        print(f"✓ Respuesta: {data['response']}")
    else:
        print(f"✗ Error: {response.text}")
except Exception as e:
    print(f"✗ Exception: {e}")
