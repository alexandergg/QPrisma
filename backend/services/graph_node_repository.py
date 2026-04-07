"""
Graph Node Repository for QPrisma

Encapsulates all CRUD operations for graph nodes (Video, Scene, Frame, Entity,
AudioSegment) and relations.  Receives a callable that executes Cypher queries
so it stays decoupled from connection management.

The implementation is split into domain-specific mixins under
``services.graph.*``.  This module composes them into the single public class
:class:`GraphNodeRepository` so that existing imports remain unchanged.
"""

from collections.abc import Callable

from services.graph.agent_queries import AgentQueryMixin
from services.graph.audio_ops import AudioOpsMixin
from services.graph.community_ops import CommunityOpsMixin
from services.graph.entity_ops import EntityOpsMixin
from services.graph.frame_ops import FrameOpsMixin
from services.graph.relation_ops import RelationOpsMixin
from services.graph.video_ops import VideoOpsMixin

# Type alias for the session context-manager factory used by CRUD helpers
# that need raw session access (batch writes, etc.).
SessionFactory = Callable


class GraphNodeRepository(
    VideoOpsMixin,
    FrameOpsMixin,
    EntityOpsMixin,
    AudioOpsMixin,
    RelationOpsMixin,
    CommunityOpsMixin,
    AgentQueryMixin,
):
    """
    CRUD operations for Knowledge-Graph nodes and relations.

    Parameters
    ----------
    execute_query_fn:
        ``KnowledgeGraphService._execute_query`` (or compatible callable).
    get_session_fn:
        ``KnowledgeGraphService.get_session`` context-manager factory so that
        batch helpers can run multiple statements within one session.
    """

    def __init__(
        self,
        execute_query_fn: Callable,
        get_session_fn: SessionFactory,
    ):
        self._execute_query = execute_query_fn
        self._get_session = get_session_fn
