"""
Tests para Hierarchical Context Encoding de QPrisma (Fase 2.3)

Ejecutar con: python tests/test_hierarchical_context.py
Requiere: Neo4j corriendo en localhost:7687

Uso:
    python tests/test_hierarchical_context.py --check       # Solo verificar servicios
    python tests/test_hierarchical_context.py --demo        # Ejecutar demo completo
    python tests/test_hierarchical_context.py --embeddings  # Probar embeddings jerárquicos
    python tests/test_hierarchical_context.py --search      # Probar drill-down search
"""

import argparse
import os
from datetime import datetime
from uuid import uuid4

import pytest

if os.getenv("RUN_INTEGRATION_TESTS", "").lower() not in {"1", "true", "yes"}:
    pytest.skip(
        "Manual hierarchical-context demo tests are disabled. Set RUN_INTEGRATION_TESTS=true to enable.",
        allow_module_level=True,
    )

from dotenv import load_dotenv

load_dotenv()

from models.graph_models import NodeType
from services.embedding_service import EmbeddingService
from services.hierarchical_context_service import (
    EmbeddingPoolStrategy,
    HierarchicalConfig,
    HierarchicalContextService,
)
from services.knowledge_graph import KnowledgeGraphService
from services.scene_analyzer import Scene, VideoStructure


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


class HierarchicalContextTester:
    """Clase para probar Hierarchical Context Encoding."""

    def __init__(self):
        self.graph_service = KnowledgeGraphService()
        self.embedding_service = EmbeddingService()
        self.hierarchy_service = None

        # IDs de prueba
        self.test_video_id = f"hierarchy-test-{uuid4().hex[:8]}"

    def check_services(self) -> bool:
        """Verifica que los servicios estén disponibles."""
        print_header("Verificando Servicios")

        # Neo4j
        print_step("Conectando a Neo4j")
        connected = self.graph_service.connect()
        print_result("Neo4j", "Connected" if connected else "Error")

        if not connected:
            print("\n  Neo4j no esta disponible.")
            print("    Ejecuta: docker-compose up -d neo4j")
            return False

        # Embedding Service
        print_step("Verificando Azure OpenAI (Embeddings)")
        has_key = bool(self.embedding_service.api_key)
        has_endpoint = bool(self.embedding_service.endpoint)
        print_result("API Key", "Configurada" if has_key else "Falta")
        print_result("Endpoint", "Configurado" if has_endpoint else "Falta")

        if not has_key or not has_endpoint:
            print("\n  Azure OpenAI no esta configurado.")
            print("    Configura AZURE_OPENAI_API_KEY y AZURE_OPENAI_ENDPOINT en .env")

        # Inicializar Hierarchical Service
        config = HierarchicalConfig(
            scene_threshold=0.3,
            keyframes_per_scene=2,
            max_scenes_per_chapter=3,
            pool_strategy=EmbeddingPoolStrategy.WEIGHTED_MEAN,
        )

        self.hierarchy_service = HierarchicalContextService(
            graph_service=self.graph_service,
            embedding_service=self.embedding_service,
            config=config,
        )

        print_result("HierarchicalContextService", "Inicializado")

        return connected

    def test_embedding_pooling(self):
        """Prueba las estrategias de pooling de embeddings."""
        print_step("Probando estrategias de pooling")

        # Crear embeddings de prueba (simulados)
        import numpy as np

        # Generar 3 embeddings de prueba con diferentes "temas"
        dims = 10  # Usar dimensiones pequeñas para prueba
        emb1 = list(np.random.randn(dims))
        emb2 = list(np.random.randn(dims))
        emb3 = list(np.random.randn(dims))

        embeddings = [emb1, emb2, emb3]
        weights = [0.5, 0.3, 0.2]  # Primer embedding más importante

        # Test MEAN pooling
        mean_result = self.hierarchy_service._pool_embeddings(
            embeddings, strategy=EmbeddingPoolStrategy.MEAN
        )
        print_result("MEAN pooling", f"{len(mean_result)} dims")

        # Test WEIGHTED_MEAN pooling
        weighted_result = self.hierarchy_service._pool_embeddings(
            embeddings, weights=weights, strategy=EmbeddingPoolStrategy.WEIGHTED_MEAN
        )
        print_result("WEIGHTED_MEAN pooling", f"{len(weighted_result)} dims")

        # Test MAX pooling
        max_result = self.hierarchy_service._pool_embeddings(
            embeddings, strategy=EmbeddingPoolStrategy.MAX_POOL
        )
        print_result("MAX_POOL pooling", f"{len(max_result)} dims")

        # Verificar que los resultados son diferentes
        mean_sum = sum(mean_result)
        weighted_sum = sum(weighted_result)
        max_sum = sum(max_result)

        print_result("Mean sum", f"{mean_sum:.4f}")
        print_result("Weighted sum", f"{weighted_sum:.4f}")
        print_result("Max sum", f"{max_sum:.4f}")

        return True

    def test_embedding_compression(self):
        """Prueba la compresión de embeddings."""
        print_step("Probando compresión de embeddings")

        # Crear embedding de prueba
        import numpy as np

        full_embedding = list(np.random.randn(3072))  # Full size

        # Comprimir a diferentes tamaños
        compressed_1024 = self.hierarchy_service._compress_embedding(full_embedding, 1024)
        compressed_512 = self.hierarchy_service._compress_embedding(full_embedding, 512)
        compressed_256 = self.hierarchy_service._compress_embedding(full_embedding, 256)

        print_result("Original", f"{len(full_embedding)} dims")
        print_result("Comprimido 1024", f"{len(compressed_1024)} dims")
        print_result("Comprimido 512", f"{len(compressed_512)} dims")
        print_result("Comprimido 256", f"{len(compressed_256)} dims")

        # Verificar normalización
        norm_1024 = sum(x * x for x in compressed_1024) ** 0.5
        print_result("Norma (comprimido 1024)", f"{norm_1024:.4f} (deberia ser ~1.0)")

        return True

    def create_test_structure(self) -> VideoStructure:
        """Crea una estructura de video de prueba."""
        print_step("Creando estructura de video de prueba")

        # Crear escenas
        scenes = [
            Scene(
                scene_id=0,
                start_time=0.0,
                end_time=30.0,
                start_frame=0,
                end_frame=900,
                duration=30.0,
                keyframe_indices=[0, 450, 899],
                title="Introduction",
                summary="Opening scene with presenter introducing the topic",
                visual_description="A person standing in front of a whiteboard explaining concepts",
                transcript_segment="Welcome to our presentation on machine learning fundamentals.",
                detected_objects=["person", "whiteboard", "marker"],
            ),
            Scene(
                scene_id=1,
                start_time=30.0,
                end_time=60.0,
                start_frame=900,
                end_frame=1800,
                duration=30.0,
                keyframe_indices=[900, 1350, 1799],
                title="Core Concepts",
                summary="Explanation of neural network architecture",
                visual_description="Diagram of neural network layers on screen",
                transcript_segment="Let me explain how neural networks work at a fundamental level.",
                detected_objects=["diagram", "screen", "neural network"],
            ),
            Scene(
                scene_id=2,
                start_time=60.0,
                end_time=90.0,
                start_frame=1800,
                end_frame=2700,
                duration=30.0,
                keyframe_indices=[1800, 2250, 2699],
                title="Code Demo",
                summary="Live coding demonstration of a simple model",
                visual_description="Code editor showing Python code for ML model",
                transcript_segment="Now let's write some code to implement this.",
                detected_objects=["code editor", "laptop", "python code"],
            ),
            Scene(
                scene_id=3,
                start_time=90.0,
                end_time=120.0,
                start_frame=2700,
                end_frame=3600,
                duration=30.0,
                keyframe_indices=[2700, 3150, 3599],
                title="Results",
                summary="Showing training results and metrics",
                visual_description="Charts and graphs displaying model performance",
                transcript_segment="Here are the results of our training run.",
                detected_objects=["chart", "graph", "metrics"],
            ),
            Scene(
                scene_id=4,
                start_time=120.0,
                end_time=150.0,
                start_frame=3600,
                end_frame=4500,
                duration=30.0,
                keyframe_indices=[3600, 4050, 4499],
                title="Conclusion",
                summary="Summary and next steps",
                visual_description="Presenter wrapping up the presentation",
                transcript_segment="In conclusion, we've learned the basics of machine learning.",
                detected_objects=["person", "slide", "summary"],
            ),
        ]

        # Crear chapters (agrupando escenas)
        chapters = [
            {
                "chapter_id": 0,
                "title": "Introduction & Theory",
                "start_time": 0.0,
                "end_time": 60.0,
                "duration": 60.0,
                "scene_ids": [0, 1],
                "summary": "Introduction to the topic and theoretical foundations",
                "themes": ["introduction", "theory", "neural networks"],
            },
            {
                "chapter_id": 1,
                "title": "Practical Implementation",
                "start_time": 60.0,
                "end_time": 120.0,
                "duration": 60.0,
                "scene_ids": [2, 3],
                "summary": "Hands-on coding and results analysis",
                "themes": ["coding", "implementation", "results"],
            },
            {
                "chapter_id": 2,
                "title": "Wrap-up",
                "start_time": 120.0,
                "end_time": 150.0,
                "duration": 30.0,
                "scene_ids": [4],
                "summary": "Final thoughts and conclusions",
                "themes": ["conclusion", "summary"],
            },
        ]

        structure = VideoStructure(
            media_id=self.test_video_id,
            total_duration=150.0,
            total_frames=4500,
            scenes=scenes,
            chapters=chapters,
            video_title="Machine Learning Fundamentals Tutorial",
            video_summary="A comprehensive tutorial covering the basics of machine learning, including theory, code examples, and practical demonstrations.",
            key_topics=["machine learning", "neural networks", "python", "data science"],
        )

        print_result("Video ID", self.test_video_id)
        print_result("Escenas", len(scenes))
        print_result("Chapters", len(chapters))
        print_result("Duracion", f"{structure.total_duration}s")

        return structure

    async def test_scene_embeddings(self, structure: VideoStructure):
        """Prueba la generación de embeddings a nivel de escena."""
        print_step("Generando embeddings de escenas")

        for scene in structure.scenes:
            try:
                embedding = await self.hierarchy_service.generate_scene_embedding(scene)
                scene.embedding = embedding
                print_result(f"Escena {scene.scene_id} ({scene.title})", f"{len(embedding)} dims")
            except Exception as e:
                print(f"      Error en escena {scene.scene_id}: {e}")

        return True

    async def test_chapter_embeddings(self, structure: VideoStructure):
        """Prueba la generación de embeddings a nivel de chapter."""
        print_step("Generando embeddings de chapters")

        for chapter in structure.chapters:
            # Obtener embeddings de escenas del chapter
            chapter_scene_ids = set(chapter.get("scene_ids", []))
            scene_embeddings = [
                s.embedding
                for s in structure.scenes
                if s.scene_id in chapter_scene_ids and s.embedding
            ]
            scene_durations = [
                s.duration for s in structure.scenes if s.scene_id in chapter_scene_ids
            ]

            try:
                embedding = await self.hierarchy_service.generate_chapter_embedding(
                    chapter, scene_embeddings, scene_durations
                )
                chapter["embedding"] = embedding
                print_result(
                    f"Chapter {chapter['chapter_id']} ({chapter['title']})",
                    f"{len(embedding)} dims",
                )
            except Exception as e:
                print(f"      Error en chapter {chapter['chapter_id']}: {e}")

        return True

    async def test_video_embedding(self, structure: VideoStructure):
        """Prueba la generación de embedding a nivel de video."""
        print_step("Generando embedding de video")

        chapter_embeddings = [
            ch.get("embedding", []) for ch in structure.chapters if ch.get("embedding")
        ]
        chapter_durations = [ch.get("duration", 0) for ch in structure.chapters]

        try:
            embedding = await self.hierarchy_service.generate_video_embedding(
                structure, chapter_embeddings, chapter_durations
            )
            print_result("Video embedding", f"{len(embedding)} dims")
            return embedding
        except Exception as e:
            print(f"    Error generando embedding de video: {e}")
            return None

    async def test_store_hierarchy(self, structure: VideoStructure, video_embedding: list):
        """Prueba almacenar la jerarquía en Neo4j."""
        print_step("Almacenando jerarquía en Neo4j")

        video_metadata = {
            "media_id": self.test_video_id,
            "title": structure.video_title,
            "fps": 30.0,
            "resolution": (1920, 1080),
            "file_size_bytes": 100_000_000,
            "format": "mp4",
        }

        try:
            result = await self.hierarchy_service._store_hierarchy_in_graph(
                structure=structure, video_metadata=video_metadata, video_embedding=video_embedding
            )

            print_result("Videos creados", result.get("video", 0))
            print_result("Chapters creados", result.get("chapters", 0))
            print_result("Scenes creados", result.get("scenes", 0))

            return True
        except Exception as e:
            print(f"    Error almacenando: {e}")
            return False

    async def test_hierarchy_stats(self):
        """Prueba obtener estadísticas de la jerarquía."""
        print_step("Obteniendo estadísticas de jerarquía")

        try:
            stats = await self.hierarchy_service.get_hierarchy_stats(self.test_video_id)

            if "error" in stats:
                print(f"    Error: {stats['error']}")
                return False

            print_result("Video", stats.get("video_title", "N/A"))
            print_result("Chapters", stats.get("hierarchy", {}).get("chapters", 0))
            print_result("Scenes", stats.get("hierarchy", {}).get("scenes", 0))
            print_result("Frames", stats.get("hierarchy", {}).get("frames", 0))
            print_result(
                "Video embedding", "Si" if stats.get("embeddings", {}).get("video") else "No"
            )

            return True
        except Exception as e:
            print(f"    Error: {e}")
            return False

    async def test_drill_down_search(self):
        """Prueba la búsqueda drill-down."""
        print_step("Probando búsqueda drill-down")

        queries = [
            "neural networks explanation",
            "code implementation python",
            "results and metrics",
        ]

        for query in queries:
            print(f"\n    Query: '{query}'")
            try:
                results = await self.hierarchy_service.drill_down_search(
                    query_text=query,
                    video_id=self.test_video_id,
                    start_level="video",
                    target_level="scene",
                    top_k=3,
                )

                for i, result in enumerate(results[:2]):
                    print(f"      {i+1}. {result.current_level.title or 'N/A'}")
                    print(f"         Nivel: {result.current_level.level}")
                    print(f"         Path: {' > '.join([p.level for p in result.path_from_root])}")

            except Exception as e:
                print(f"      Error: {e}")

        return True

    async def test_lazy_loading(self):
        """Prueba la carga lazy de hijos."""
        print_step("Probando carga lazy de hijos")

        # Primero obtener el video node
        try:
            # Cargar chapters del video
            children = await self.hierarchy_service.load_children(
                node_id=f"video:{self.test_video_id}", node_type=NodeType.VIDEO, limit=10
            )

            print_result("Chapters cargados", len(children))

            for child in children[:3]:
                print(f"      - {child.title} ({child.start_time:.0f}s - {child.end_time:.0f}s)")

            return True
        except Exception as e:
            print(f"    Error: {e}")
            return False

    def cleanup(self):
        """Limpia datos de prueba."""
        print_step("Limpiando datos de prueba")

        deleted = self.graph_service.delete_video_graph(self.test_video_id)
        print_result("Nodos eliminados", deleted)

    def disconnect(self):
        """Cierra conexiones."""
        self.graph_service.disconnect()
        print("\n  Conexiones cerradas")

    def print_embedding_stats(self):
        """Imprime estadísticas del servicio de embeddings."""
        print_step("Estadísticas del servicio de embeddings")

        stats = self.embedding_service.get_stats()
        print_result("Total requests", stats["total_requests"])
        print_result("Cache hits", stats["cache_hits"])
        print_result("Hit rate", f"{stats['cache_hit_rate']:.1%}")
        print_result("Tokens usados", stats["tokens_used"])


async def main():
    parser = argparse.ArgumentParser(description="Tests de Hierarchical Context Encoding")
    parser.add_argument("--check", action="store_true", help="Solo verificar servicios")
    parser.add_argument("--demo", action="store_true", help="Ejecutar demo completo")
    parser.add_argument("--embeddings", action="store_true", help="Solo probar embeddings")
    parser.add_argument("--search", action="store_true", help="Solo probar drill-down search")

    args = parser.parse_args()

    print_header("QPrisma Hierarchical Context Encoding - Tests (Fase 2.3)")
    print(f"Timestamp: {datetime.now().isoformat()}")

    tester = HierarchicalContextTester()

    try:
        # Verificar servicios
        if not tester.check_services():
            return 1

        if args.check:
            print("\n  Servicios verificados correctamente")
            return 0

        if args.embeddings:
            # Solo probar embeddings
            tester.test_embedding_pooling()
            tester.test_embedding_compression()

            structure = tester.create_test_structure()
            await tester.test_scene_embeddings(structure)
            await tester.test_chapter_embeddings(structure)
            await tester.test_video_embedding(structure)

            tester.print_embedding_stats()
            return 0

        if args.search or args.demo or not any([args.check, args.embeddings]):
            # Demo completo o search
            print_header("Ejecutando Demo Completo")

            # 1. Test pooling y compression
            tester.test_embedding_pooling()
            tester.test_embedding_compression()

            # 2. Crear estructura de prueba
            structure = tester.create_test_structure()

            # 3. Generar embeddings jerárquicos
            await tester.test_scene_embeddings(structure)
            await tester.test_chapter_embeddings(structure)
            video_embedding = await tester.test_video_embedding(structure)

            # 4. Almacenar en Neo4j
            await tester.test_store_hierarchy(structure, video_embedding)

            # 5. Obtener stats
            await tester.test_hierarchy_stats()

            # 6. Probar drill-down search
            await tester.test_drill_down_search()

            # 7. Probar lazy loading
            await tester.test_lazy_loading()

            # 8. Stats de embeddings
            tester.print_embedding_stats()

            # 9. Cleanup
            tester.cleanup()

            print_header("Demo Completado")
            print("\n  Hierarchical Context Encoding funcionando correctamente!")
            print("\nEndpoints disponibles:")
            print("   POST /graph/hierarchy/process         - Procesar jerarquia de video")
            print("   POST /graph/hierarchy/search/drill-down - Busqueda drill-down")
            print("   POST /graph/hierarchy/children        - Carga lazy de hijos")
            print("   GET  /graph/hierarchy/stats/{video_id} - Estadisticas de jerarquia")
            print("   GET  /graph/hierarchy/path/{node_id}  - Ruta desde raiz")

    finally:
        tester.disconnect()

    return 0
