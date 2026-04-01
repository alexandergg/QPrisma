"""
Community Detection Service for QPrisma

Implements hierarchical graph summarization using community detection
on entity co-occurrence graphs. Generates thematic community summaries
via LLM for macro-level reasoning in the knowledge graph.

Pipeline:
1. Extract entity co-occurrence graph from Neo4j into NetworkX
2. Run Leiden community detection (Louvain fallback) to cluster related entities
3. Generate LLM summaries for each community
4. Store Community nodes with embeddings back into Neo4j
"""

import logging
from uuid import uuid4

import networkx as nx

from core.config import settings
from models.graph_models import CommunityNode, NodeType

logger = logging.getLogger(__name__)


class CommunityDetectionService:
    """Detects entity communities and generates hierarchical summaries."""

    def __init__(
        self,
        knowledge_graph_service=None,
        embedding_service=None,
        openai_client=None,
    ):
        self._graph_service = knowledge_graph_service
        self._embedding_service = embedding_service
        self._openai_client = openai_client

    def _get_graph_service(self):
        if self._graph_service is None:
            from services.knowledge_graph import get_knowledge_graph_service

            self._graph_service = get_knowledge_graph_service()
        return self._graph_service

    def _get_embedding_service(self):
        if self._embedding_service is None:
            from services.embedding_service import get_embedding_service

            self._embedding_service = get_embedding_service()
        return self._embedding_service

    def _get_openai_client(self):
        if self._openai_client is None:
            from core.config import create_azure_openai_client

            self._openai_client = create_azure_openai_client()
        return self._openai_client

    # =========================================================================
    # Step 1: Build entity co-occurrence graph
    # =========================================================================

    def build_entity_graph(self, video_id: str) -> nx.Graph:
        """Extract entity co-occurrence data from Neo4j into a NetworkX graph.

        Nodes = entities (filtered by min occurrence count).
        Edges = APPEARS_WITH relationships (weight = co-occurrence count).
        """
        graph_svc = self._get_graph_service()
        min_occurrences = settings.community.min_entity_occurrences

        # Fetch entities with sufficient occurrences
        entity_query = """
        MATCH (e:Entity)
        WHERE e.video_id = $video_id
          AND coalesce(e.occurrence_count, 1) >= $min_occurrences
        RETURN e.id AS id, e.name AS name, e.normalized_name AS normalized_name,
               e.entity_type AS entity_type, e.description AS description,
               coalesce(e.occurrence_count, 1) AS occurrence_count,
               e.first_seen_time AS first_seen_time,
               e.last_seen_time AS last_seen_time
        """

        # Fetch co-occurrence edges
        cooccurrence_query = """
        MATCH (e1:Entity)-[r:APPEARS_WITH]-(e2:Entity)
        WHERE e1.video_id = $video_id
          AND e2.video_id = $video_id
          AND coalesce(e1.occurrence_count, 1) >= $min_occurrences
          AND coalesce(e2.occurrence_count, 1) >= $min_occurrences
          AND e1.id < e2.id
        RETURN e1.id AS source, e2.id AS target,
               coalesce(r.count, 1) AS weight
        """

        G = nx.Graph()

        with graph_svc.get_session() as session:
            # Add entity nodes
            entity_result = session.run(
                entity_query,
                video_id=video_id,
                min_occurrences=min_occurrences,
            )
            for record in entity_result:
                G.add_node(
                    record["id"],
                    name=record["name"],
                    normalized_name=record["normalized_name"],
                    entity_type=record["entity_type"],
                    description=record["description"] or "",
                    occurrence_count=record["occurrence_count"],
                    first_seen_time=record["first_seen_time"],
                    last_seen_time=record["last_seen_time"],
                )

            # Add co-occurrence edges
            edge_result = session.run(
                cooccurrence_query,
                video_id=video_id,
                min_occurrences=min_occurrences,
            )
            for record in edge_result:
                if record["source"] in G and record["target"] in G:
                    G.add_edge(
                        record["source"],
                        record["target"],
                        weight=record["weight"],
                    )

        logger.info(
            f"Built entity graph for video {video_id}: "
            f"{G.number_of_nodes()} nodes, {G.number_of_edges()} edges"
        )
        return G

    # =========================================================================
    # Step 2: Detect communities
    # =========================================================================

    def detect_communities(self, G: nx.Graph) -> list[set[str]]:
        """Run community detection on the entity graph.

        Returns a list of communities, each a set of entity node IDs.
        Communities smaller than min_community_size are discarded.
        """
        if G.number_of_nodes() == 0:
            return []

        algorithm = settings.community.algorithm
        min_size = settings.community.min_community_size
        max_communities = settings.community.max_communities_per_video

        if algorithm == "leiden":
            communities = self._detect_leiden(G)
        elif algorithm == "louvain":
            communities = self._detect_louvain(G)
        else:
            communities = self._detect_connected_components(G)

        # Filter by minimum size
        communities = [c for c in communities if len(c) >= min_size]

        # Sort by size descending and cap
        communities.sort(key=len, reverse=True)
        communities = communities[:max_communities]

        logger.info(
            f"Detected {len(communities)} communities "
            f"(algorithm={algorithm}, min_size={min_size})"
        )
        return communities

    def _detect_leiden(self, G: nx.Graph) -> list[set[str]]:
        """Leiden community detection with hierarchical multi-resolution support.

        Produces higher-quality partitions than Louvain (guaranteed connected
        communities) and supports multiple resolution levels for hierarchical
        graph summarization.
        """
        try:
            import igraph as ig
            import leidenalg
        except ImportError:
            logger.warning("leidenalg/igraph not installed, falling back to louvain")
            return self._detect_louvain(G)

        # Convert NetworkX graph to igraph
        node_list = list(G.nodes())
        node_index = {n: i for i, n in enumerate(node_list)}

        ig_graph = ig.Graph()
        ig_graph.add_vertices(len(node_list))

        edges = []
        weights = []
        for u, v, data in G.edges(data=True):
            edges.append((node_index[u], node_index[v]))
            weights.append(data.get("weight", 1.0))
        ig_graph.add_edges(edges)
        ig_graph.es["weight"] = weights

        resolution = settings.community.resolution
        hierarchical_levels = settings.community.hierarchical_levels

        all_communities: list[set[str]] = []

        for level in range(hierarchical_levels):
            level_resolution = resolution * (2.0**level)

            partition = leidenalg.find_partition(
                ig_graph,
                leidenalg.RBConfigurationVertexPartition,
                weights=weights,
                resolution_parameter=level_resolution,
                seed=42,
            )

            level_communities: dict[int, set[str]] = {}
            for node_idx, comm_id in enumerate(partition.membership):
                level_communities.setdefault(comm_id, set()).add(node_list[node_idx])

            # Tag communities with their hierarchy level
            for comm_set in level_communities.values():
                all_communities.append(comm_set)

            logger.info(
                f"Leiden level {level} (resolution={level_resolution:.2f}): "
                f"{len(level_communities)} communities"
            )

        # Deduplicate identical communities across levels
        unique_communities: list[set[str]] = []
        seen: set[frozenset[str]] = set()
        for comm in all_communities:
            key = frozenset(comm)
            if key not in seen:
                seen.add(key)
                unique_communities.append(comm)

        return unique_communities

    def _detect_louvain(self, G: nx.Graph) -> list[set[str]]:
        """Louvain community detection via python-louvain."""
        try:
            import community as community_louvain
        except ImportError:
            logger.warning("python-louvain not installed, falling back to connected_components")
            return self._detect_connected_components(G)

        resolution = settings.community.resolution
        partition = community_louvain.best_partition(G, resolution=resolution, random_state=42)

        # Group node IDs by community label
        community_map: dict[int, set[str]] = {}
        for node_id, comm_label in partition.items():
            community_map.setdefault(comm_label, set()).add(node_id)

        return list(community_map.values())

    def _detect_connected_components(self, G: nx.Graph) -> list[set[str]]:
        """Fallback: use connected components as communities."""
        return [set(c) for c in nx.connected_components(G)]

    # =========================================================================
    # Step 3: Generate community summaries
    # =========================================================================

    def generate_community_summaries(
        self,
        G: nx.Graph,
        communities: list[set[str]],
        video_id: str,
    ) -> list[CommunityNode]:
        """Generate LLM summaries for each community and build CommunityNode models."""
        if not communities:
            return []

        graph_svc = self._get_graph_service()
        client = self._get_openai_client()
        community_nodes: list[CommunityNode] = []

        for idx, entity_ids in enumerate(communities):
            # Collect entity info from the NetworkX graph
            entities_info = []
            first_time = float("inf")
            last_time = float("-inf")

            for eid in entity_ids:
                if eid in G.nodes:
                    data = G.nodes[eid]
                    entities_info.append(
                        f"- {data.get('name', 'unknown')} "
                        f"({data.get('entity_type', 'unknown')}): "
                        f"{data.get('description', 'no description')}"
                    )
                    ft = data.get("first_seen_time")
                    lt = data.get("last_seen_time")
                    if ft is not None and ft < first_time:
                        first_time = ft
                    if lt is not None and lt > last_time:
                        last_time = lt

            # Fetch supporting frame descriptions for context
            frame_context = self._get_supporting_frames(
                graph_svc, video_id, list(entity_ids), limit=5
            )

            # Build the summary prompt
            entities_text = "\n".join(entities_info[:20])
            frames_text = "\n".join(
                f"- [{f['timestamp']:.1f}s] {f['description']}" for f in frame_context
            )

            prompt = (
                "You are analyzing a video's knowledge graph. "
                "A community of related entities has been detected. "
                "Generate a concise thematic summary of this community.\n\n"
                f"## Entities in this community ({len(entity_ids)} total):\n"
                f"{entities_text}\n\n"
                f"## Representative video moments:\n"
                f"{frames_text}\n\n"
                "Respond with JSON:\n"
                '{"title": "short 3-6 word title", '
                '"summary": "2-3 sentence thematic summary", '
                '"themes": ["theme1", "theme2", ...]}'
            )

            try:
                response = client.chat.completions.create(
                    model=settings.azure.openai_deployment_gpt,
                    messages=[{"role": "user", "content": prompt}],
                    max_tokens=settings.community.summary_max_tokens,
                    temperature=0.3,
                    response_format={"type": "json_object"},
                )

                import json

                result = json.loads(response.choices[0].message.content)
                title = result.get("title", f"Community {idx}")
                summary = result.get("summary", "")
                themes = result.get("themes", [])
            except Exception as e:
                logger.warning(f"Failed to generate summary for community {idx}: {e}")
                title = f"Community {idx}"
                summary = f"A group of {len(entity_ids)} related entities."
                themes = []

            community_node = CommunityNode(
                id=str(uuid4()),
                community_id=f"{video_id}_c{idx}",
                video_id=video_id,
                title=title,
                summary=summary,
                themes=themes,
                member_entity_ids=list(entity_ids),
                member_count=len(entity_ids),
                time_span_start=first_time if first_time != float("inf") else None,
                time_span_end=last_time if last_time != float("-inf") else None,
                level=0,
            )
            community_nodes.append(community_node)

        logger.info(f"Generated {len(community_nodes)} community summaries for video {video_id}")
        return community_nodes

    def _get_supporting_frames(
        self, graph_svc, video_id: str, entity_ids: list[str], limit: int = 5
    ) -> list[dict]:
        """Fetch representative frame descriptions linked to community entities."""
        query = """
        MATCH (f:Frame {video_id: $video_id})-[:CONTAINS]->(e:Entity)
        WHERE e.id IN $entity_ids AND f.description IS NOT NULL
        RETURN DISTINCT f.timestamp AS timestamp, f.description AS description
        ORDER BY f.timestamp
        LIMIT $limit
        """
        with graph_svc.get_session() as session:
            result = session.run(query, video_id=video_id, entity_ids=entity_ids, limit=limit)
            return [{"timestamp": r["timestamp"], "description": r["description"]} for r in result]

    # =========================================================================
    # Step 4: Store communities in Neo4j
    # =========================================================================

    def store_communities(
        self,
        community_nodes: list[CommunityNode],
        video_id: str,
    ) -> int:
        """Persist community nodes to Neo4j with embeddings and entity links."""
        if not community_nodes:
            return 0

        graph_svc = self._get_graph_service()
        embedding_svc = self._get_embedding_service()

        # Delete existing communities for this video (idempotent re-runs)
        graph_svc.delete_video_communities(video_id)

        # Batch create community nodes
        created = graph_svc.create_communities_batch(community_nodes)

        # Link entities to communities and generate embeddings
        for comm in community_nodes:
            # Link entities
            graph_svc.link_entities_to_community(comm.id, comm.member_entity_ids)

            # Generate and store embedding for community summary
            try:
                summary_text = f"{comm.title}. {comm.summary}"
                embedding = embedding_svc.generate_embedding(summary_text)
                if embedding:
                    from services.graph_search_service import GraphSearchService

                    search_svc = GraphSearchService()
                    search_svc.graph_service = graph_svc
                    search_svc.store_embedding(comm.id, embedding, NodeType.COMMUNITY)
            except Exception as e:
                logger.warning(f"Failed to store embedding for community {comm.id}: {e}")

        logger.info(f"Stored {created} communities for video {video_id}")
        return created

    # =========================================================================
    # Orchestration
    # =========================================================================

    def run_pipeline(self, video_id: str) -> list[CommunityNode]:
        """Run the full community detection pipeline for a video.

        Steps:
        1. Build entity co-occurrence graph from Neo4j
        2. Detect communities via Leiden (or Louvain fallback)
        3. Generate LLM summaries for each community
        4. Store Community nodes with embeddings back into Neo4j

        Returns the list of created CommunityNode models.
        """
        if not settings.community.enabled:
            logger.info("Community detection disabled, skipping")
            return []

        logger.info(f"Starting community detection pipeline for video {video_id}")

        # Step 1: Build graph
        G = self.build_entity_graph(video_id)
        if G.number_of_nodes() < settings.community.min_community_size:
            logger.info(
                f"Not enough entities ({G.number_of_nodes()}) for community detection, skipping"
            )
            return []

        # Step 2: Detect communities
        communities = self.detect_communities(G)
        if not communities:
            logger.info("No communities detected")
            return []

        # Step 3: Generate summaries
        community_nodes = self.generate_community_summaries(G, communities, video_id)

        # Step 4: Store in Neo4j
        self.store_communities(community_nodes, video_id)

        logger.info(
            f"Community detection pipeline complete for video {video_id}: "
            f"{len(community_nodes)} communities created"
        )
        return community_nodes


# =============================================================================
# Singleton
# =============================================================================

_community_detection_service: CommunityDetectionService | None = None


def get_community_detection_service() -> CommunityDetectionService:
    """Return the singleton instance of CommunityDetectionService."""
    global _community_detection_service
    if _community_detection_service is None:
        _community_detection_service = CommunityDetectionService()
    return _community_detection_service
