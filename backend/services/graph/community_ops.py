"""
Community node operations.

Covers creation (single and batch), entity linking, retrieval, and deletion
of Community nodes used for graph-community detection summaries.
"""

from __future__ import annotations

import logging

from models.graph_models import CommunityNode

logger = logging.getLogger(__name__)


class CommunityOpsMixin:
    """Mixin providing Community CRUD and membership helpers."""

    # =====================================================================
    # Community Node Operations
    # =====================================================================

    def create_community_node(self, community: CommunityNode) -> str:
        """Create a Community node and link it to its Video with SUMMARIZES."""
        query = """
        MATCH (v:Video {video_id: $video_id})
        CREATE (c:Community {
            id: $id,
            community_id: $community_id,
            video_id: $video_id,
            user_id: COALESCE($user_id, v.user_id),
            title: $title,
            summary: $summary,
            themes: $themes,
            themes_text: $themes_text,
            member_entity_ids: $member_entity_ids,
            member_count: $member_count,
            time_span_start: $time_span_start,
            time_span_end: $time_span_end,
            level: $level,
            created_at: datetime(),
            updated_at: datetime()
        })
        CREATE (c)-[:SUMMARIZES]->(v)
        RETURN c.id as id
        """
        record = self._execute_query(
            query,
            {
                "id": community.id,
                "community_id": community.community_id,
                "video_id": community.video_id,
                "user_id": community.user_id,
                "title": community.title,
                "summary": community.summary,
                "themes": community.themes,
                "themes_text": ", ".join(community.themes) if community.themes else "",
                "member_entity_ids": community.member_entity_ids,
                "member_count": community.member_count,
                "time_span_start": community.time_span_start,
                "time_span_end": community.time_span_end,
                "level": community.level,
            },
            single=True,
        )
        return record["id"] if record else community.id

    def create_communities_batch(self, communities: list[CommunityNode]) -> int:
        """Create multiple Community nodes in a single batch."""
        if not communities:
            return 0

        batch_data = [
            {
                "id": c.id,
                "community_id": c.community_id,
                "video_id": c.video_id,
                "user_id": c.user_id,
                "title": c.title,
                "summary": c.summary,
                "themes": c.themes,
                "themes_text": ", ".join(c.themes) if c.themes else "",
                "member_entity_ids": c.member_entity_ids,
                "member_count": c.member_count,
                "time_span_start": c.time_span_start,
                "time_span_end": c.time_span_end,
                "level": c.level,
            }
            for c in communities
        ]

        query = """
        UNWIND $communities AS comm
        MATCH (v:Video {video_id: comm.video_id})
        CREATE (c:Community {
            id: comm.id,
            community_id: comm.community_id,
            video_id: comm.video_id,
            user_id: COALESCE(comm.user_id, v.user_id),
            title: comm.title,
            summary: comm.summary,
            themes: comm.themes,
            themes_text: comm.themes_text,
            member_entity_ids: comm.member_entity_ids,
            member_count: comm.member_count,
            time_span_start: comm.time_span_start,
            time_span_end: comm.time_span_end,
            level: comm.level,
            created_at: datetime(),
            updated_at: datetime()
        })
        CREATE (c)-[:SUMMARIZES]->(v)
        RETURN count(c) as created
        """

        try:
            record = self._execute_query(query, {"communities": batch_data}, single=True)
            created = record["created"] if record else 0
            logger.info(f"Batch created {created} Community nodes")
            return created
        except Exception as e:
            logger.error(f"Batch community creation failed: {e}")
            return 0

    def link_entities_to_community(self, community_id: str, entity_ids: list[str]) -> int:
        """Create IN_COMMUNITY relationships from entities to a community."""
        if not entity_ids:
            return 0

        query = """
        UNWIND $entity_ids AS eid
        MATCH (e:Entity {id: eid})
        MATCH (c:Community {id: $community_id})
        CREATE (e)-[:IN_COMMUNITY]->(c)
        RETURN count(*) as linked
        """

        record = self._execute_query(
            query, {"community_id": community_id, "entity_ids": entity_ids}, single=True
        )
        return record["linked"] if record else 0

    def get_video_communities(self, video_id: str) -> list[dict]:
        """Retrieve all communities for a video, ordered by member count."""
        query = """
        MATCH (c:Community {video_id: $video_id})
        RETURN c {
            .id, .community_id, .video_id, .title, .summary,
            .themes, .member_entity_ids, .member_count,
            .time_span_start, .time_span_end, .level
        } AS community
        ORDER BY c.member_count DESC
        """

        return self._execute_query(query, {"video_id": video_id}, unpack_key="community")

    def get_community_members(self, community_id: str) -> list[dict]:
        """Retrieve all entities belonging to a community."""
        query = """
        MATCH (e:Entity)-[:IN_COMMUNITY]->(c:Community {id: $community_id})
        RETURN e {
            .id, .name, .normalized_name, .entity_type,
            .description, .occurrence_count,
            .first_seen_time, .last_seen_time
        } AS entity
        ORDER BY e.occurrence_count DESC
        """

        return self._execute_query(query, {"community_id": community_id}, unpack_key="entity")

    def delete_video_communities(self, video_id: str) -> int:
        """Delete all Community nodes and their relationships for a video."""
        query = """
        MATCH (c:Community {video_id: $video_id})
        DETACH DELETE c
        RETURN count(c) as deleted
        """

        record = self._execute_query(query, {"video_id": video_id}, single=True)
        deleted = record["deleted"] if record else 0
        logger.info(f"Deleted {deleted} community nodes for video {video_id}")
        return deleted
