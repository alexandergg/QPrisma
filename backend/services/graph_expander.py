"""
Graph Expander for QPrisma

Handles graph expansion, subgraph retrieval, analytics (timelines, related
entities, cross-video queries), statistics, and cleanup operations.
"""

import logging
from collections.abc import Callable

from core.serializers import sanitize_for_json
from models.graph_models import (
    GraphStats,
    RelationType,
)

logger = logging.getLogger(__name__)

# Type alias for the session context-manager factory.
SessionFactory = Callable


class GraphExpander:
    """
    Graph expansion, analytics, statistics, and cleanup operations.

    Parameters
    ----------
    execute_query_fn:
        ``KnowledgeGraphService._execute_query`` (or compatible callable).
    get_session_fn:
        ``KnowledgeGraphService.get_session`` context-manager factory.
    """

    def __init__(
        self,
        execute_query_fn: Callable,
        get_session_fn: SessionFactory,
    ):
        self._execute_query = execute_query_fn
        self._get_session = get_session_fn

    # =====================================================================
    # Graph Expansion for RAG
    # =====================================================================

    def expand_context(
        self,
        node_id: str,
        hops: int = 2,
        relation_types: list[RelationType] | None = None,
        max_nodes: int = 50,
    ) -> dict:
        """
        Expand the context of a node for RAG.

        Returns related nodes up to N hops away.
        """
        if relation_types:
            rel_types = "|".join([r.value for r in relation_types])
            rel_filter = f"[:{rel_types}]"
        else:
            rel_filter = ""

        cypher = f"""
        MATCH (start {{id: $node_id}})
        CALL apoc.path.subgraphNodes(start, {{
            maxLevel: $hops,
            relationshipFilter: '{rel_filter}',
            limit: $max_nodes
        }}) YIELD node
        WHERE node <> start
        RETURN node,
               length(shortestPath((start)-[*]-(node))) as distance
        ORDER BY distance
        """

        with self._get_session() as session:
            result = session.run(cypher, node_id=node_id, hops=hops, max_nodes=max_nodes)

            nodes_by_distance = {0: []}  # Include start node at distance 0

            # Get start node data
            start_result = session.run("MATCH (n {id: $node_id}) RETURN n", node_id=node_id)
            start_record = start_result.single()
            if start_record:
                nodes_by_distance[0].append(dict(start_record["n"]))

            for record in result:
                distance = record["distance"]
                node_data = dict(record["node"])

                if distance not in nodes_by_distance:
                    nodes_by_distance[distance] = []
                nodes_by_distance[distance].append(node_data)

            return {
                "center_node_id": node_id,
                "hops": hops,
                "total_nodes": sum(len(v) for v in nodes_by_distance.values()),
                "nodes_by_distance": nodes_by_distance,
            }

    # =====================================================================
    # Entity Timeline & Related Entities
    # =====================================================================

    def get_entity_timeline(self, entity_name: str, video_id: str) -> list[dict]:
        """
        Retrieve the appearance timeline of an entity within a video.
        """
        cypher = """
        MATCH (v:Video {video_id: $video_id})-[:CONTAINS*..2]->(f:Frame)-[:CONTAINS]->(e:Entity)
        WHERE e.normalized_name = $entity_name
        RETURN f.timestamp as timestamp, f.id as frame_id, f.description as context
        ORDER BY f.timestamp
        """
        normalized = entity_name.lower().strip()
        results = self._execute_query(cypher, {"video_id": video_id, "entity_name": normalized})
        return [
            {"timestamp": r["timestamp"], "frame_id": r["frame_id"], "context": r["context"]}
            for r in results
        ]

    def get_related_entities(
        self,
        entity_id: str,
        relation_types: list[RelationType] | None = None,
        limit: int = 20,
    ) -> list[dict]:
        """Retrieve entities related to a given entity."""
        if relation_types:
            rel_types = "|".join([r.value for r in relation_types])
            rel_filter = f"[r:{rel_types}]"
        else:
            rel_filter = "[r]"

        cypher = f"""
        MATCH (e:Entity {{id: $entity_id}})-{rel_filter}-(related:Entity)
        RETURN related, type(r) as relation,
               CASE WHEN startNode(r) = e THEN 'outgoing' ELSE 'incoming' END as direction
        LIMIT $limit
        """
        results = self._execute_query(cypher, {"entity_id": entity_id, "limit": limit})
        return [
            {"entity": dict(r["related"]), "relation": r["relation"], "direction": r["direction"]}
            for r in results
        ]

    # =====================================================================
    # Cross-Video Queries
    # =====================================================================

    def find_common_entities(
        self,
        video_ids: list[str],
        entity_type: str | None = None,
        limit: int = 20,
    ) -> list[dict]:
        """Find entities that appear in multiple videos."""
        type_filter = ""
        if entity_type and entity_type != "any":
            type_filter = "AND e.entity_type = $entity_type"

        cypher = f"""
        MATCH (f:Frame)-[:CONTAINS]->(e:Entity)
        WHERE f.video_id IN $video_ids {type_filter}
        WITH e.name AS name, e.entity_type AS etype,
             collect(DISTINCT f.video_id) AS videos,
             count(DISTINCT f) AS total_appearances
        WHERE size(videos) >= 2
        RETURN name, etype, videos, total_appearances
        ORDER BY size(videos) DESC, total_appearances DESC
        LIMIT $limit
        """

        params: dict = {"video_ids": video_ids, "limit": limit}
        if entity_type and entity_type != "any":
            params["entity_type"] = entity_type

        with self._get_session() as session:
            result = session.run(cypher, **params)
            return [
                {
                    "name": r["name"],
                    "entity_type": r["etype"],
                    "shared_across": r["videos"],
                    "total_appearances": r["total_appearances"],
                }
                for r in result
            ]

    def get_video_topics(
        self,
        video_ids: list[str],
    ) -> list[dict]:
        """Get topics and summaries for multiple videos."""
        cypher = """
        MATCH (v:Video)
        WHERE v.video_id IN $video_ids
        RETURN v.video_id AS video_id,
               v.title AS title,
               v.summary AS summary,
               v.topics AS topics,
               v.duration AS duration
        """

        with self._get_session() as session:
            result = session.run(cypher, video_ids=video_ids)
            return [dict(r) for r in result]

    # =====================================================================
    # Statistics
    # =====================================================================

    def get_stats(self) -> GraphStats:
        """Retrieve statistics for the Knowledge Graph."""
        cypher = """
        CALL {
            MATCH (n) RETURN count(n) as total_nodes
        }
        CALL {
            MATCH ()-[r]->() RETURN count(r) as total_relations
        }
        CALL {
            MATCH (v:Video) RETURN count(v) as total_videos
        }
        CALL {
            MATCH (f:Frame) RETURN count(f) as total_frames
        }
        CALL {
            MATCH (e:Entity) RETURN count(e) as total_entities
        }
        RETURN total_nodes, total_relations, total_videos, total_frames, total_entities
        """

        nodes_by_type_cypher = """
        MATCH (n)
        RETURN labels(n)[0] as label, count(n) as count
        """

        relations_by_type_cypher = """
        MATCH ()-[r]->()
        RETURN type(r) as type, count(r) as count
        """

        with self._get_session() as session:
            # General statistics
            result = session.run(cypher)
            record = result.single()

            # Nodes by type
            nodes_result = session.run(nodes_by_type_cypher)
            nodes_by_type = {r["label"]: r["count"] for r in nodes_result}

            # Relations by type
            rels_result = session.run(relations_by_type_cypher)
            relations_by_type = {r["type"]: r["count"] for r in rels_result}

            total_nodes = record["total_nodes"]
            total_relations = record["total_relations"]

            return GraphStats(
                total_nodes=total_nodes,
                nodes_by_type=nodes_by_type,
                total_relations=total_relations,
                relations_by_type=relations_by_type,
                total_videos=record["total_videos"],
                total_frames_indexed=record["total_frames"],
                total_entities_extracted=record["total_entities"],
                avg_relations_per_node=total_relations / total_nodes if total_nodes > 0 else 0,
            )

    # =====================================================================
    # Graph Visualization (NVL-compatible)
    # =====================================================================

    def get_video_subgraph(
        self,
        video_id: str,
        depth: int = 2,
        include_entities: bool = True,
        max_nodes: int = 200,
    ) -> dict:
        """
        Return a balanced subgraph for a video as nodes + relationships.

        Instead of letting a single label (e.g. Frame) flood the result,
        we collect each label separately and apply per-type quotas so the
        visualization always shows a representative mix of labels.

        Returns NVL-compatible structure:
        {
            "nodes": [{"id", "labels", "properties"}, ...],
            "relationships": [{"id", "start", "end", "type", "properties"}, ...],
        }

        Args:
            video_id: The video to visualize.
            depth: How many relationship hops to traverse (1-4).
            include_entities: Whether to include Entity nodes.
            max_nodes: Maximum total nodes to return.
        """
        # ── Step 1: collect per-label node samples ──────────────────────────
        # Quotas per label type (order matters for budget allocation).
        # The Video root always gets 1 slot; remaining budget is split among
        # the other types with a priority order that favours higher-level
        # structures (Chapters, Scenes) over dense leaves (Frames, Audio).
        label_configs = [
            ("Chapter", 0.15),  # 15 % of budget
            ("Scene", 0.25),  # 25 %
            ("AudioSegment", 0.20),  # 20 %
            ("Frame", 0.30),  # 30 %
        ]
        if include_entities:
            label_configs.append(("Entity", 0.10))  # 10 %

        budget = max_nodes - 1  # reserve 1 for the Video node itself

        # Collect the Video root node first
        cypher_video = """
        MATCH (v:Video)
        WHERE v.video_id = $video_id OR v.id = $video_id
        RETURN {
            id: coalesce(v.id, v.video_id, elementId(v)),
            labels: labels(v),
            properties: properties(v)
        } AS node
        """

        # For each label, collect connected nodes up to a per-type limit.
        # We use a depth-aware pattern: the relationship path differs per type.
        _label_cypher: dict[str, str] = {
            "Chapter": f"""
                MATCH (v:Video)-[:HAS_CHAPTER|CONTAINS*1..{depth}]->(n:Chapter)
                WHERE v.video_id = $video_id OR v.id = $video_id
                RETURN DISTINCT {{
                    id: coalesce(n.id, elementId(n)),
                    labels: labels(n),
                    properties: properties(n)
                }} AS node
                LIMIT $limit
            """,
            "Scene": f"""
                MATCH (v:Video)-[:HAS_SCENE|CONTAINS*1..{depth}]->(n:Scene)
                WHERE v.video_id = $video_id OR v.id = $video_id
                RETURN DISTINCT {{
                    id: coalesce(n.id, elementId(n)),
                    labels: labels(n),
                    properties: properties(n)
                }} AS node
                LIMIT $limit
            """,
            "Frame": f"""
                MATCH (v:Video)-[:HAS_FRAME|CONTAINS*1..{depth}]->(n:Frame)
                WHERE v.video_id = $video_id OR v.id = $video_id
                WITH n ORDER BY n.timestamp
                WITH collect(n) AS frames
                WITH frames, size(frames) AS total
                WITH frames,
                     CASE WHEN total <= $limit THEN 1
                          ELSE toInteger(ceil(toFloat(total) / $limit))
                     END AS step
                UNWIND range(0, size(frames) - 1, step) AS idx
                WITH frames[idx] AS n
                RETURN {{
                    id: coalesce(n.id, elementId(n)),
                    labels: labels(n),
                    properties: properties(n)
                }} AS node
                LIMIT $limit
            """,
            "AudioSegment": f"""
                MATCH (v:Video)-[:HAS_TRANSCRIPT|HAS_AUDIO|CONTAINS*1..{depth}]->(n:AudioSegment)
                WHERE v.video_id = $video_id OR v.id = $video_id
                WITH n ORDER BY n.start_time
                With collect(n) AS segs
                With segs, size(segs) AS total
                WITH segs,
                     CASE WHEN total <= $limit THEN 1
                          ELSE toInteger(ceil(toFloat(total) / $limit))
                     END AS step
                UNWIND range(0, size(segs) - 1, step) AS idx
                WITH segs[idx] AS n
                RETURN {{
                    id: coalesce(n.id, elementId(n)),
                    labels: labels(n),
                    properties: properties(n)
                }} AS node
                LIMIT $limit
            """,
            "Entity": f"""
                MATCH (v:Video)-[*1..{depth}]->(n:Entity)
                WHERE v.video_id = $video_id OR v.id = $video_id
                RETURN DISTINCT {{
                    id: coalesce(n.id, elementId(n)),
                    labels: labels(n),
                    properties: properties(n)
                }} AS node
                LIMIT $limit
            """,
        }

        all_nodes: list[dict] = []
        collected_ids: set[str] = set()

        with self._get_session() as session:
            # Video root
            rec = session.run(cypher_video, video_id=video_id).single()
            if not rec:
                return {"nodes": [], "relationships": []}
            video_node = dict(rec["node"])
            vid = video_node.get("id")
            all_nodes.append(video_node)
            if vid:
                collected_ids.add(str(vid))

            # Per-label queries
            for label, fraction in label_configs:
                limit = max(5, int(budget * fraction))
                cypher = _label_cypher.get(label)
                if not cypher:
                    continue
                result = session.run(
                    cypher,
                    video_id=video_id,
                    limit=limit,
                )
                for record in result:
                    node = dict(record["node"])
                    nid = str(node.get("id", ""))
                    if nid and nid not in collected_ids:
                        collected_ids.add(nid)
                        all_nodes.append(node)

            # ── Step 2: fetch relationships between collected nodes ─────────
            # Use the video as anchor and match direct relationships to
            # collected nodes, which is far more efficient than a full scan.
            node_ids = list(collected_ids)
            cypher_rels = """
            MATCH (a)-[r]->(b)
            WHERE (coalesce(a.id, a.video_id, elementId(a)) IN $node_ids)
              AND (coalesce(b.id, b.video_id, elementId(b)) IN $node_ids)
            RETURN DISTINCT
                elementId(r) AS rid,
                coalesce(a.id, a.video_id, elementId(a)) AS start_id,
                coalesce(b.id, b.video_id, elementId(b)) AS end_id,
                type(r) AS rel_type,
                properties(r) AS props
            """
            rel_result = session.run(cypher_rels, node_ids=node_ids)
            raw_rels = [
                {
                    "id": rec["rid"],
                    "start": rec["start_id"],
                    "end": rec["end_id"],
                    "type": rec["rel_type"],
                    "properties": rec["props"],
                }
                for rec in rel_result
            ]

        # ── Step 3: deduplicate & sanitize ──────────────────────────────────
        seen_node_ids: set[str] = set()
        nodes = []
        for n in all_nodes:
            nid = str(n.get("id", ""))
            if nid and nid not in seen_node_ids:
                seen_node_ids.add(nid)
                nodes.append(sanitize_for_json(n))

        seen_rel_keys: set[str] = set()
        relationships = []
        for r in raw_rels:
            key = f"{r.get('start')}-{r.get('type')}-{r.get('end')}"
            if key not in seen_rel_keys:
                seen_rel_keys.add(key)
                relationships.append(sanitize_for_json(r))

        return {"nodes": nodes, "relationships": relationships}

    def expand_node_subgraph(
        self,
        node_id: str,
        hops: int = 1,
        max_nodes: int = 50,
    ) -> dict:
        """
        Expand a single node's neighborhood, returning nodes + relationships.

        Used for progressive lazy-load expansion in the graph viewer.
        """
        cypher = """
        MATCH (start)
        WHERE start.id = $node_id OR start.video_id = $node_id
        CALL apoc.path.subgraphAll(start, {
            maxLevel: $hops,
            limit: $max_nodes
        }) YIELD nodes, relationships
        RETURN
            [n IN nodes | {
                id: coalesce(n.id, n.video_id, elementId(n)),
                labels: labels(n),
                properties: properties(n)
            }] AS nodes,
            [r IN relationships | {
                id: elementId(r),
                start: coalesce(startNode(r).id, startNode(r).video_id, elementId(startNode(r))),
                end: coalesce(endNode(r).id, endNode(r).video_id, elementId(endNode(r))),
                type: type(r),
                properties: properties(r)
            }] AS relationships
        """

        with self._get_session() as session:
            result = session.run(cypher, node_id=node_id, hops=hops, max_nodes=max_nodes)
            record = result.single()

            if not record:
                return {"nodes": [], "relationships": []}

            # Deduplicate
            seen_node_ids: set[str] = set()
            nodes = []
            for n in record["nodes"] or []:
                nid = n.get("id")
                if nid and nid not in seen_node_ids:
                    seen_node_ids.add(nid)
                    nodes.append(sanitize_for_json(dict(n)))

            seen_rel_keys: set[str] = set()
            relationships = []
            for r in record["relationships"] or []:
                key = f"{r.get('start')}-{r.get('type')}-{r.get('end')}"
                if key not in seen_rel_keys:
                    seen_rel_keys.add(key)
                    relationships.append(sanitize_for_json(dict(r)))

            return {"nodes": nodes, "relationships": relationships}

    # =====================================================================
    # Community Operations
    # =====================================================================

    def get_community_context(self, video_id: str, topic: str | None = None) -> list[dict]:
        """Retrieve community summaries for a video, optionally filtered by topic.

        Returns communities with their summaries, themes, and member counts.
        Useful for macro-level reasoning and thematic query routing.
        """
        if topic:
            cypher = """
            CALL db.index.fulltext.queryNodes('community_search', $topic)
            YIELD node AS c, score
            WHERE c.video_id = $video_id
            RETURN c {
                .id, .community_id, .title, .summary, .themes,
                .member_count, .time_span_start, .time_span_end, .level
            } AS community, score
            ORDER BY score DESC
            LIMIT 10
            """
            params = {"video_id": video_id, "topic": topic}
        else:
            cypher = """
            MATCH (c:Community {video_id: $video_id})
            RETURN c {
                .id, .community_id, .title, .summary, .themes,
                .member_count, .time_span_start, .time_span_end, .level
            } AS community, 1.0 AS score
            ORDER BY c.member_count DESC
            """
            params = {"video_id": video_id}

        with self._get_session() as session:
            result = session.run(cypher, **params)
            return [
                {**record["community"], "relevance_score": record["score"]} for record in result
            ]

    # =====================================================================
    # Cleanup Operations
    # =====================================================================

    def delete_video_graph(self, video_id: str) -> int:
        """Delete the entire subgraph for a video (scenes, frames, transcripts, entities)."""
        cypher = """
        MATCH (v:Video)
        WHERE v.video_id = $video_id OR v.id = $video_id
        OPTIONAL MATCH (v)-[*]->(n)
        DETACH DELETE v, n
        RETURN count(n) as deleted
        """
        result = self._execute_query(cypher, {"video_id": video_id}, single=True)
        count = result["deleted"] if result else 0
        logger.info(f"Deleted graph for video {video_id}: {count} nodes")
        return count

    def clear_all(self) -> None:
        """Delete all data from the graph. USE WITH CAUTION."""
        self._execute_query("MATCH (n) DETACH DELETE n")
        logger.warning("All graph data has been deleted")
