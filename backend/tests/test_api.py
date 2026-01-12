"""
Script para probar la API de QPrisma
"""

import json

import requests

BASE_URL = "http://localhost:8000"


def test_health():
    """Test health endpoint"""
    print("🔍 Testing health endpoint...")
    response = requests.get(f"{BASE_URL}/")
    print(f"Status: {response.status_code}")
    print(f"Response: {json.dumps(response.json(), indent=2)}")
    print()


def test_detailed_health():
    """Test detailed health endpoint"""
    print("🔍 Testing detailed health endpoint...")
    response = requests.get(f"{BASE_URL}/health")
    print(f"Status: {response.status_code}")
    print(f"Response: {json.dumps(response.json(), indent=2)}")
    print()


def test_config():
    """Test configuration endpoint"""
    print("🔍 Testing configuration endpoint...")
    response = requests.get(f"{BASE_URL}/config")
    print(f"Status: {response.status_code}")
    print(f"Response: {json.dumps(response.json(), indent=2)}")
    print()


if __name__ == "__main__":
    print("=" * 50)
    print("QPrisma API Test Suite")
    print("=" * 50)
    print()

    try:
        test_health()
        test_detailed_health()
        test_config()

        print("✅ All tests passed!")
    except Exception as e:
        print(f"❌ Error: {e}")
