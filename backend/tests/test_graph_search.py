"""
Tests para Graph-Enhanced Search de QPrisma

Ejecutar con: python tests/test_graph_search.py
Requiere: Neo4j corriendo en localhost:7687

Uso:
    python tests/test_graph_search.py --check       # Solo verificar servicios
    python tests/test_graph_search.py --demo       # Ejecutar demo completo
    python tests/test_graph_search.py --embeddings # Probar generación de embeddings
"""

import argparse
import os
import sys
from datetime import datetime
from uuid import uuid4

# Agregar backend al path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

load_dotenv()

from models.graph_models import NodeType
from services.embedding_service import EmbeddingService
from services.graph_search_service import GraphSearchService
from services.knowledge_graph import KnowledgeGraphService


def print_header(title: str):
    """Imprime un header decorativo."""
    print("\n" + "=" * 60)
    print(f"  {title}")
    print("=" * 60)


def print_step(step: str):
    """Imprime un paso."""
    print(f"\n>>> {step}")


def print_result(label: str, value):
    """Imprime un resultado."""
    print(f"    {label}: {value}")


class GraphSearchTester:
    """Clase para probar Graph-Enhanced Search."""

    def __init__(self):
        self.graph_service = KnowledgeGraphService()
        self.embedding_service = EmbeddingService()
        self.search_service = None

        # IDs de prueba
        self.test_video_id = f"search-test-{uuid4().hex[:8]}"

    def check_services(self) -> bool:
        """Verifica que los servicios estén disponibles."""
        print_header("Verificando Servicios")

        # Neo4j
        print_step("Conectando a Neo4j")
        connected = self.graph_service.connect()
        print_result("Neo4j", "✅ Conectado" if connected else "❌ Error")

        if not connected:
            print("\n⚠️  Neo4j no está disponible.")
            print("    Ejecuta: docker-compose up -d neo4j")
            return False

        # Embedding Service
        print_step("Verificando Azure OpenAI (Embeddings)")
        has_key = bool(self.embedding_service.api_key)
        has_endpoint = bool(self.embedding_service.endpoint)
        print_result("API Key", "✅ Configurada" if has_key else "❌ Falta")
        print_result("Endpoint", "✅ Configurado" if has_endpoint else "❌ Falta")

        if not has_key or not has_endpoint:
            print("\n⚠️  Azure OpenAI no está configurado.")
            print("    Configura AZURE_OPENAI_API_KEY y AZURE_OPENAI_ENDPOINT en .env")

        # Inicializar Search Service
        self.search_service = GraphSearchService(
            graph_service=self.graph_service,
            embedding_service=self.embedding_service,
        )

        return connected

    def test_embedding_generation(self):
        """Prueba la generación de embeddings."""
        print_step("Probando generación de embeddings")

        test_texts = [
            "A person presenting slides on a large screen",
            "Coffee cup on a wooden table",
            "Group of people in a meeting room discussing",
        ]

        try:
            for text in test_texts:
                embedding = self.embedding_service.generate_embedding(text)
                print_result(f"'{text[:40]}...'", f"✅ {len(embedding)} dims")

            # Test batch
            print_step("Probando batch embedding")
            embeddings = self.embedding_service.generate_embeddings_batch(test_texts)
            print_result("Batch de 3 textos", f"✅ {len(embeddings)} embeddings generados")

            # Test similarity
            print_step("Probando similitud")
            sim = self.embedding_service.compute_similarity(embeddings[0], embeddings[2])
            print_result("Similitud (presentación vs reunión)", f"{sim:.4f}")

            sim2 = self.embedding_service.compute_similarity(embeddings[0], embeddings[1])
            print_result("Similitud (presentación vs café)", f"{sim2:.4f}")

            return True

        except Exception as e:
            print(f"\n❌ Error: {e}")
            return False

    def setup_test_data(self):
        """Crea datos de prueba con embeddings."""
        print_step("Creando datos de prueba")

        # Crear nodo de video
        from models.graph_models import FrameNode, VideoNode

        video = VideoNode(
            video_id=self.test_video_id,
            title="Test Video for Search",
            description="A test video demonstrating graph-enhanced search",
            duration_seconds=60.0,
            fps=30.0,
            resolution=(1920, 1080),
            file_size_bytes=10_000_000,
            format="mp4",
            total_frames=1800,
            extracted_frames=6,
        )

        self.graph_service.create_video_node(video)
        print_result("Video creado", self.test_video_id)

        # Crear frames con descripciones variadas
        frame_descriptions = [
            ("A presenter standing in front of a whiteboard explaining a diagram", 5.0),
            ("Close-up of a laptop screen showing code editor with Python code", 15.0),
            ("Two people shaking hands in a business meeting", 25.0),
            ("A coffee cup next to a notebook on a wooden desk", 35.0),
            ("Team of developers looking at multiple monitors", 45.0),
            ("Person writing notes in a notebook during presentation", 55.0),
        ]

        frame_ids = []
        for desc, timestamp in frame_descriptions:
            frame = FrameNode(
                video_id=self.test_video_id,
                timestamp=timestamp,
                frame_number=int(timestamp * 30),
                description=desc,
                is_keyframe=True,
            )
            frame_id = self.graph_service.create_frame_node(frame)
            frame_ids.append((frame_id, desc))

        print_result("Frames creados", len(frame_ids))

        # Generar embeddings para los frames
        print_step("Generando embeddings para frames")
        for frame_id, desc in frame_ids:
            try:
                embedding = self.embedding_service.generate_embedding(desc)
                self.search_service.store_embedding(frame_id, embedding, NodeType.FRAME)
            except Exception as e:
                print(f"    ⚠️  Error generando embedding: {e}")

        print_result("Embeddings generados", len(frame_ids))

        return frame_ids

    def test_vector_search(self):
        """Prueba búsqueda vectorial."""
        print_step("Probando búsqueda vectorial")

        # Buscar frames similares a una query
        queries = [
            "someone giving a presentation",
            "programming and coding",
            "business meeting handshake",
        ]

        for query in queries:
            print(f"\n    Query: '{query}'")

            try:
                query_embedding = self.embedding_service.generate_embedding(query)
                results = self.search_service.vector_search(
                    query_embedding=query_embedding,
                    node_type=NodeType.FRAME,
                    limit=3,
                    video_id=self.test_video_id,
                    min_score=0.0,
                )

                for i, r in enumerate(results):
                    desc = r.content.get("description", "N/A")[:50]
                    print(f"      {i+1}. [{r.vector_score:.3f}] {desc}...")

            except Exception as e:
                print(f"      ❌ Error: {e}")

    def test_hybrid_search(self):
        """Prueba búsqueda híbrida."""
        print_step("Probando búsqueda híbrida")

        queries = [
            "presentation whiteboard",
            "laptop code",
            "meeting notes",
        ]

        for query in queries:
            print(f"\n    Query: '{query}'")

            try:
                response = self.search_service.hybrid_search(
                    query_text=query,
                    node_types=[NodeType.FRAME],
                    video_id=self.test_video_id,
                    limit=3,
                    expansion_hops=1,
                    use_reranking=True,
                )

                print(f"      Tiempo: {response.search_time_ms:.1f}ms")
                print(f"      Resultados: {response.total_results}")

                for i, r in enumerate(response.results[:3]):
                    desc = r.content.get("description", "N/A")[:40]
                    print(
                        f"        {i+1}. [v:{r.vector_score:.2f} g:{r.graph_score:.2f} c:{r.combined_score:.2f}] {desc}..."
                    )

            except Exception as e:
                print(f"      ❌ Error: {e}")

    def test_scoring_weights(self):
        """Prueba diferentes configuraciones de pesos."""
        print_step("Probando configuraciones de scoring")

        weight_configs = [
            {"vector": 0.8, "fulltext": 0.1, "graph": 0.05, "temporal": 0.05},  # Vector-heavy
            {"vector": 0.3, "fulltext": 0.3, "graph": 0.3, "temporal": 0.1},  # Balanced
            {"vector": 0.2, "fulltext": 0.2, "graph": 0.5, "temporal": 0.1},  # Graph-heavy
        ]

        query = "presentation explaining"

        for config in weight_configs:
            config_name = max(config, key=config.get)
            print(f"\n    Config: {config_name}-heavy")

            try:
                search_svc = GraphSearchService(
                    graph_service=self.graph_service,
                    embedding_service=self.embedding_service,
                    weights=config,
                )

                response = search_svc.hybrid_search(
                    query_text=query,
                    node_types=[NodeType.FRAME],
                    video_id=self.test_video_id,
                    limit=3,
                )

                for i, r in enumerate(response.results[:2]):
                    desc = r.content.get("description", "N/A")[:35]
                    print(f"      {i+1}. [{r.combined_score:.3f}] {desc}...")

            except Exception as e:
                print(f"      ❌ Error: {e}")

    def cleanup(self):
        """Limpia datos de prueba."""
        print_step("Limpiando datos de prueba")

        deleted = self.graph_service.delete_video_graph(self.test_video_id)
        print_result("Nodos eliminados", deleted)

    def disconnect(self):
        """Cierra conexiones."""
        self.graph_service.disconnect()
        print("\n✅ Conexiones cerradas")

    def print_stats(self):
        """Imprime estadísticas."""
        print_step("Estadísticas del servicio de embeddings")

        stats = self.embedding_service.get_stats()
        print_result("Total requests", stats["total_requests"])
        print_result("Cache hits", stats["cache_hits"])
        print_result("Hit rate", f"{stats['cache_hit_rate']:.1%}")
        print_result("Tokens usados", stats["tokens_used"])


def main():
    parser = argparse.ArgumentParser(description="Tests de Graph-Enhanced Search")
    parser.add_argument("--check", action="store_true", help="Solo verificar servicios")
    parser.add_argument("--demo", action="store_true", help="Ejecutar demo completo")
    parser.add_argument("--embeddings", action="store_true", help="Solo probar embeddings")

    args = parser.parse_args()

    print_header("QPrisma Graph-Enhanced Search - Tests")
    print(f"Timestamp: {datetime.now().isoformat()}")

    tester = GraphSearchTester()

    try:
        # Verificar servicios
        if not tester.check_services():
            return 1

        if args.check:
            print("\n✅ Servicios verificados correctamente")
            return 0

        if args.embeddings:
            # Solo probar embeddings
            success = tester.test_embedding_generation()
            tester.print_stats()
            return 0 if success else 1

        if args.demo or not any([args.check, args.embeddings]):
            # Demo completo
            print_header("Ejecutando Demo Completo")

            # 1. Test embeddings
            if not tester.test_embedding_generation():
                print("\n⚠️  Embeddings no disponibles, algunas pruebas pueden fallar")

            # 2. Setup datos
            tester.setup_test_data()

            # 3. Tests de búsqueda
            tester.test_vector_search()
            tester.test_hybrid_search()
            tester.test_scoring_weights()

            # 4. Stats
            tester.print_stats()

            # 5. Cleanup
            tester.cleanup()

            print_header("Demo Completado")
            print("\n🎉 Graph-Enhanced Search funcionando correctamente!")
            print("\nEndpoints disponibles:")
            print("   POST /graph/search/hybrid     - Búsqueda híbrida")
            print("   POST /graph/search/cross-video - Búsqueda cross-video")
            print("   POST /graph/embeddings/initialize - Crear índices vectoriales")
            print("   POST /graph/embeddings/generate  - Generar embeddings en bulk")

    finally:
        tester.disconnect()

    return 0


if __name__ == "__main__":
    sys.exit(main())
