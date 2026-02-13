"""
Tests para el Knowledge Graph de QPrisma

Ejecutar con: python tests/test_knowledge_graph.py
Requiere: Neo4j corriendo en localhost:7687

Uso:
    python tests/test_knowledge_graph.py --check       # Solo verificar conexión
    python tests/test_knowledge_graph.py --demo       # Ejecutar demo completo
    python tests/test_knowledge_graph.py --clean      # Limpiar datos de prueba
"""

import argparse
import os
from datetime import datetime
from uuid import uuid4

import pytest

if os.getenv("RUN_INTEGRATION_TESTS", "").lower() not in {"1", "true", "yes"}:
    pytest.skip(
        "Manual knowledge-graph demo tests are disabled. Set RUN_INTEGRATION_TESTS=true to enable.",
        allow_module_level=True,
    )

from dotenv import load_dotenv

load_dotenv()

from models.graph_models import (
    EntityType,
    FrameNode,
    SceneNode,
    VideoNode,
)
from services.knowledge_graph import KnowledgeGraphService
from services.relation_builder import RelationBuilder


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


class KnowledgeGraphTester:
    """Clase para probar el Knowledge Graph."""

    def __init__(self):
        self.graph_service = KnowledgeGraphService()
        self.entity_extractor = None  # Se inicializa solo si se necesita
        self.relation_builder = None

        # IDs de prueba
        self.test_video_id = f"test-video-{uuid4().hex[:8]}"

    def check_connection(self) -> bool:
        """Verifica la conexión con Neo4j."""
        print_header("Verificando conexión con Neo4j")

        connected = self.graph_service.connect()
        print_result("URI", self.graph_service.uri)
        print_result("Conectado", "✅ Sí" if connected else "❌ No")

        if not connected:
            print("\n⚠️  No se pudo conectar a Neo4j.")
            print("    Asegúrate de que Neo4j está corriendo:")
            print("    $ docker-compose up -d neo4j")
            print("    Y espera ~30 segundos para que inicie.")
            return False

        return True

    def initialize_schema(self):
        """Inicializa el schema de Neo4j."""
        print_step("Inicializando schema (índices y constraints)")
        self.graph_service.initialize_schema()
        print("    ✅ Schema inicializado correctamente")

    def create_test_video(self) -> str:
        """Crea un video de prueba."""
        print_step(f"Creando video de prueba: {self.test_video_id}")

        video = VideoNode(
            video_id=self.test_video_id,
            title="Video de Prueba - QPrisma Demo",
            description="Video sintético para testing del Knowledge Graph",
            duration_seconds=120.0,
            fps=30.0,
            resolution=(1920, 1080),
            file_size_bytes=50_000_000,
            format="mp4",
            total_frames=3600,
            extracted_frames=10,
            ai_summary="Video de demostración con escenas de oficina y personas interactuando.",
            topics=["oficina", "reunión", "trabajo", "tecnología"],
        )

        node_id = self.graph_service.create_video_node(video)
        print_result("Video ID", node_id)
        return node_id

    def create_test_scenes(self) -> list[str]:
        """Crea escenas de prueba."""
        print_step("Creando escenas de prueba")

        scenes_data = [
            {"start": 0, "end": 30, "desc": "Introducción en sala de reuniones", "type": "indoor"},
            {"start": 30, "end": 60, "desc": "Presentación en pantalla", "type": "indoor"},
            {"start": 60, "end": 90, "desc": "Discusión en grupo", "type": "indoor"},
            {"start": 90, "end": 120, "desc": "Cierre y despedida", "type": "indoor"},
        ]

        scene_ids = []
        for i, data in enumerate(scenes_data):
            scene = SceneNode(
                video_id=self.test_video_id,
                start_time=data["start"],
                end_time=data["end"],
                scene_index=i,
                description=data["desc"],
                scene_type=data["type"],
                dominant_colors=["#FFFFFF", "#000000", "#0066CC"],
            )
            scene_id = self.graph_service.create_scene_node(scene)
            scene_ids.append(scene_id)
            print_result(f"Escena {i}", f"{data['desc']} ({data['start']}-{data['end']}s)")

        return scene_ids

    def create_test_frames(self) -> list[str]:
        """Crea frames de prueba."""
        print_step("Creando frames de prueba (batch)")

        frames = []
        timestamps = [5, 15, 25, 35, 45, 55, 65, 75, 85, 95, 105, 115]

        descriptions = [
            "Vista general de sala de reuniones con mesa de conferencias",
            "Persona presentando frente a una pantalla con gráficos",
            "Laptop abierta mostrando código en la pantalla",
            "Dos personas discutiendo sobre documentos",
            "Pizarra blanca con diagramas de arquitectura",
            "Taza de café sobre la mesa junto a un notebook",
            "Grupo de personas mirando hacia la pantalla",
            "Primer plano de manos escribiendo en teclado",
            "Ventana con vista a la ciudad al fondo",
            "Persona tomando notas en cuaderno",
            "Teléfono móvil sobre la mesa mostrando notificación",
            "Personas despidiéndose al final de la reunión",
        ]

        for i, (ts, desc) in enumerate(zip(timestamps, descriptions)):
            frame = FrameNode(
                video_id=self.test_video_id,
                timestamp=ts,
                frame_number=int(ts * 30),
                description=desc,
                perceptual_hash=f"phash_{i:04d}",
                is_keyframe=True,
                blur_score=0.1,
                brightness=0.5,
            )
            frames.append(frame)

        created = self.graph_service.create_frames_batch(frames)
        print_result("Frames creados", created)
        return [f.id for f in frames]

    def create_test_entities(self):
        """Crea entidades de prueba."""
        print_step("Creando entidades de prueba")

        # Simular entidades extraídas
        entities = [
            ("María García", EntityType.PERSON, "Presentadora principal", 0.95),
            ("Carlos Ruiz", EntityType.PERSON, "Asistente tomando notas", 0.88),
            ("Ana López", EntityType.PERSON, "Participante en discusión", 0.92),
            ("Laptop Dell", EntityType.OBJECT, "Laptop con código en pantalla", 0.9),
            ("Pantalla de proyección", EntityType.OBJECT, "Pantalla mostrando gráficos", 0.95),
            ("Mesa de conferencias", EntityType.OBJECT, "Mesa grande central", 0.98),
            ("Pizarra blanca", EntityType.OBJECT, "Pizarra con diagramas", 0.85),
            ("Taza de café", EntityType.OBJECT, "Taza sobre la mesa", 0.75),
            ("Sala de reuniones", EntityType.LOCATION, "Espacio interior de oficina", 0.99),
            ("Ciudad al fondo", EntityType.LOCATION, "Vista exterior desde ventana", 0.7),
            ("Presentación de proyecto", EntityType.ACTION, "Actividad principal", 0.9),
            ("Discusión técnica", EntityType.ACTION, "Intercambio de ideas", 0.85),
            ("Toma de notas", EntityType.ACTION, "Documentación de la reunión", 0.8),
        ]

        # Usar el RelationBuilder para tracking
        self.relation_builder = RelationBuilder(graph_service=self.graph_service)

        # Simular detecciones en diferentes frames
        frame_entity_map = [
            (5, ["María García", "Sala de reuniones", "Mesa de conferencias"]),
            (15, ["María García", "Pantalla de proyección", "Presentación de proyecto"]),
            (25, ["Laptop Dell", "Carlos Ruiz", "Toma de notas"]),
            (35, ["María García", "Carlos Ruiz", "Ana López", "Discusión técnica"]),
            (45, ["Pizarra blanca", "María García"]),
            (55, ["Taza de café", "Laptop Dell"]),
            (65, ["María García", "Carlos Ruiz", "Ana López", "Pantalla de proyección"]),
            (75, ["Carlos Ruiz", "Laptop Dell", "Toma de notas"]),
            (85, ["Ciudad al fondo", "Sala de reuniones"]),
            (95, ["Ana López", "Toma de notas"]),
        ]

        entity_lookup = {e[0]: (e[1], e[2], e[3]) for e in entities}

        created_count = 0
        for timestamp, entity_names in frame_entity_map:
            frame_id = f"frame_{timestamp}"

            for name in entity_names:
                if name in entity_lookup:
                    entity_type, description, confidence = entity_lookup[name]

                    # Track para relaciones
                    self.relation_builder.track_entity(
                        entity_name=name,
                        entity_type=entity_type,
                        frame_id=frame_id,
                        timestamp=timestamp,
                        confidence=confidence,
                    )
                    created_count += 1

        print_result("Entidades rastreadas", created_count)

        # Construir relaciones
        print_step("Construyendo relaciones")

        # Co-ocurrencias
        cooccurrence = self.relation_builder.build_cooccurrence_relations(min_cooccurrences=1)
        print_result("Relaciones APPEARS_WITH", len(cooccurrence))

        # Temporales
        temporal = self.relation_builder.build_temporal_relations(time_threshold=10.0)
        print_result("Relaciones temporales", len(temporal))

        return created_count

    def test_search(self):
        """Prueba la búsqueda en el grafo."""
        print_step("Probando búsqueda en el grafo")

        # Búsqueda de frames por descripción
        results = self.graph_service.search_frames_by_description(
            query_text="presentación pantalla",
            video_id=self.test_video_id,
            limit=5,
        )
        print_result("Búsqueda 'presentación pantalla'", f"{len(results)} resultados")

        for r in results[:3]:
            frame = r["frame"]
            print(f"      - {frame.get('description', 'N/A')[:50]}... (score: {r['score']:.2f})")

    def test_graph_expansion(self):
        """Prueba la expansión de contexto."""
        print_step("Probando expansión de contexto")

        # Obtener un nodo para expandir
        video = self.graph_service.get_video_node(self.test_video_id)
        if video:
            expansion = self.graph_service.expand_context(
                node_id=video["id"],
                hops=2,
                max_nodes=30,
            )
            print_result("Nodos en contexto", expansion["total_nodes"])
            print_result(
                "Por distancia",
                {k: len(v) for k, v in expansion["nodes_by_distance"].items()},
            )

    def get_stats(self):
        """Obtiene estadísticas del grafo."""
        print_step("Estadísticas del Knowledge Graph")

        stats = self.graph_service.get_stats()
        print_result("Total nodos", stats.total_nodes)
        print_result("Total relaciones", stats.total_relations)
        print_result("Videos", stats.total_videos)
        print_result("Frames", stats.total_frames_indexed)
        print_result("Entidades", stats.total_entities_extracted)

        if stats.nodes_by_type:
            print("\n    Nodos por tipo:")
            for label, count in stats.nodes_by_type.items():
                print(f"      - {label}: {count}")

        if stats.relations_by_type:
            print("\n    Relaciones por tipo:")
            for rel_type, count in stats.relations_by_type.items():
                print(f"      - {rel_type}: {count}")

    def cleanup(self):
        """Limpia los datos de prueba."""
        print_step(f"Limpiando datos del video de prueba: {self.test_video_id}")

        deleted = self.graph_service.delete_video_graph(self.test_video_id)
        print_result("Nodos eliminados", deleted)

    def disconnect(self):
        """Cierra la conexión."""
        self.graph_service.disconnect()
        print("\n✅ Conexión cerrada")


def main():
    parser = argparse.ArgumentParser(description="Tests del Knowledge Graph de QPrisma")
    parser.add_argument("--check", action="store_true", help="Solo verificar conexión")
    parser.add_argument("--demo", action="store_true", help="Ejecutar demo completo")
    parser.add_argument("--clean", action="store_true", help="Limpiar datos de prueba")
    parser.add_argument("--stats", action="store_true", help="Mostrar estadísticas")

    args = parser.parse_args()

    print_header("QPrisma Knowledge Graph - Tests")
    print(f"Timestamp: {datetime.now().isoformat()}")

    tester = KnowledgeGraphTester()

    try:
        # Siempre verificar conexión
        if not tester.check_connection():
            return 1

        if args.check:
            print("\n✅ Conexión verificada exitosamente")
            tester.get_stats()

        elif args.clean:
            tester.cleanup()
            print("\n✅ Limpieza completada")

        elif args.stats:
            tester.get_stats()

        elif args.demo or not any([args.check, args.clean, args.stats]):
            # Demo completo
            print_header("Ejecutando Demo Completo")

            # 1. Inicializar schema
            tester.initialize_schema()

            # 2. Crear estructura de prueba
            tester.create_test_video()
            tester.create_test_scenes()
            tester.create_test_frames()
            tester.create_test_entities()

            # 3. Probar funcionalidad
            tester.test_search()
            tester.test_graph_expansion()

            # 4. Mostrar estadísticas
            tester.get_stats()

            print_header("Demo Completado")
            print("\n🎉 Knowledge Graph configurado correctamente!")
            print("\nPuedes explorar el grafo en Neo4j Browser:")
            print("   URL: http://localhost:7474")
            print("   Usuario: neo4j")
            print("   Password: qprisma123")
            print("\nQuery sugerido para visualizar:")
            print("   MATCH (n) RETURN n LIMIT 50")

    finally:
        tester.disconnect()

    return 0
