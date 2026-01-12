"""
Script para configurar CORS en Azure Blob Storage
Permite acceso desde localhost para desarrollo
"""

import os
from pathlib import Path

from azure.storage.blob import BlobServiceClient
from dotenv import load_dotenv

# Cargar variables de entorno
env_path = Path(__file__).parent.parent / ".env"
load_dotenv(env_path)


def configure_cors():
    """Configura CORS en Azure Blob Storage para permitir acceso desde localhost"""

    conn_string = os.getenv("AZURE_STORAGE_CONNECTION_STRING")
    if not conn_string:
        print("❌ AZURE_STORAGE_CONNECTION_STRING no está configurado")
        return

    try:
        # Crear cliente del servicio
        blob_service = BlobServiceClient.from_connection_string(conn_string)

        # Configurar CORS
        from azure.storage.blob import CorsRule

        cors_rules = [
            CorsRule(
                allowed_origins=["http://localhost:3000"],
                allowed_methods=["GET", "HEAD", "OPTIONS"],
                allowed_headers=["*"],
                exposed_headers=["*"],
                max_age_in_seconds=3600,
            ),
            CorsRule(
                allowed_origins=["http://localhost:3001"],
                allowed_methods=["GET", "HEAD", "OPTIONS"],
                allowed_headers=["*"],
                exposed_headers=["*"],
                max_age_in_seconds=3600,
            ),
            CorsRule(
                allowed_origins=["*"],
                allowed_methods=["GET", "HEAD"],
                allowed_headers=["*"],
                exposed_headers=["*"],
                max_age_in_seconds=3600,
            ),
        ]

        # Aplicar configuración
        blob_service.set_service_properties(cors=cors_rules)

        print("✅ CORS configurado correctamente en Azure Blob Storage")
        print(f"   Reglas CORS aplicadas: {len(cors_rules)}")

    except Exception as e:
        print(f"❌ Error configurando CORS: {e}")
        import traceback

        traceback.print_exc()


if __name__ == "__main__":
    print("🔧 Configurando CORS en Azure Blob Storage...")
    configure_cors()
