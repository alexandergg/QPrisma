"""
Test de conexión con Azure OpenAI
"""

import os

from dotenv import load_dotenv
from openai import AzureOpenAI

load_dotenv()

endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")
api_key = os.getenv("AZURE_OPENAI_API_KEY")
resource_name = os.getenv("AZURE_OPENAI_RESOURCE_NAME", "openai-qprisma-dev")
gpt_deployment = os.getenv("AZURE_OPENAI_DEPLOYMENT_GPT")
embedding_deployment = os.getenv("AZURE_OPENAI_DEPLOYMENT_EMBEDDING")
api_version = os.getenv("AZURE_OPENAI_API_VERSION")

print("=" * 60)
print("Configuración Azure OpenAI")
print("=" * 60)
print(f"Endpoint original: {endpoint}")
print(f"API Key: {api_key[:8]}...")
print(f"GPT Deployment: {gpt_deployment}")
print(f"Embedding Deployment: {embedding_deployment}")
print(f"API Version: {api_version}")
print()

endpoint_final = endpoint
print(f"Endpoint final: {endpoint_final}")
print()

# Test 1: Crear cliente
print("Test 1: Creando cliente...")
try:
    client = AzureOpenAI(azure_endpoint=endpoint_final, api_key=api_key, api_version=api_version)
    print("✓ Cliente creado correctamente")
except Exception as e:
    print(f"✗ Error creando cliente: {e}")
    exit(1)

# Test 2: Generar embedding
print("\nTest 2: Generando embedding...")
try:
    response = client.embeddings.create(model=embedding_deployment, input="Hello world")
    embedding = response.data[0].embedding
    print(f"✓ Embedding generado: {len(embedding)} dimensiones")
    print(f"  Primeros 5 valores: {embedding[:5]}")
except Exception as e:
    print(f"✗ Error generando embedding: {e}")
    import traceback

    traceback.print_exc()

# Test 3: Chat completion
print("\nTest 3: Chat completion...")
try:
    response = client.chat.completions.create(
        model=gpt_deployment,
        messages=[{"role": "user", "content": "Say hello in Spanish"}],
        max_tokens=50,
    )
    message = response.choices[0].message.content
    print("✓ Chat completion exitoso")
    print(f"  Respuesta: {message}")
except Exception as e:
    print(f"✗ Error en chat: {e}")
    import traceback

    traceback.print_exc()

print("\n" + "=" * 60)
print("Tests completados")
print("=" * 60)
