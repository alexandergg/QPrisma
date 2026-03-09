"""
A2A Agent Card Definitions & Shared Helpers
============================================

Agent card builders and the ``get_executor`` factory used by
message and task route modules.  Extracted from ``a2a_routes.py``
to avoid circular imports between sub-routers.
"""

import logging

from agent.a2a import (
    A2AAgentExecutor,
    get_editor_a2a_executor,
    get_video_a2a_executor,
)

from core.config import settings
from models.a2a_models import (
    AgentCapabilities,
    AgentCard,
    AgentInterface,
    AgentProvider,
    AgentSkill,
)

logger = logging.getLogger(__name__)


# =============================================================================
# Helpers
# =============================================================================


def get_base_url() -> str:
    """Get the base URL for the A2A server."""
    return settings.app.api_base_url


def get_executor(agent_type: str = "video") -> A2AAgentExecutor:
    """Get the appropriate A2A executor based on agent type."""
    if agent_type == "editor":
        return get_editor_a2a_executor()
    return get_video_a2a_executor()


# =============================================================================
# Agent Card Definitions
# =============================================================================


def get_video_agent_card() -> AgentCard:
    """Build the AgentCard for the Video Agent."""
    base_url = get_base_url()

    return AgentCard(
        name="QPrisma Video Agent",
        description=(
            "An intelligent video analysis agent that helps users explore and understand "
            "video content. Capable of searching through visual content, audio transcriptions, "
            "detected entities, and relationships in videos. Provides timestamped answers "
            "with source citations for easy navigation."
        ),
        supportedInterfaces=[
            AgentInterface(
                url=f"{base_url}/a2a",
                protocolBinding="HTTP+JSON",
                protocolVersion="1.0",
            ),
        ],
        provider=AgentProvider(
            organization="QPrisma",
            url="https://github.com/alexandergg/QPrisma",
        ),
        version="1.0.0",
        documentationUrl="https://github.com/alexandergg/QPrisma/blob/main/API_DOCUMENTATION.md",
        capabilities=AgentCapabilities(
            streaming=True,
            pushNotifications=False,
            extendedAgentCard=True,
        ),
        defaultInputModes=["text/plain", "application/json"],
        defaultOutputModes=["text/plain", "application/json"],
        skills=[
            AgentSkill(
                id="video-search",
                name="Video Content Search",
                description=(
                    "Search through video content including visual scenes, audio transcriptions, "
                    "and detected entities. Uses hybrid search combining vector similarity, "
                    "full-text matching, and knowledge graph traversal."
                ),
                tags=["video", "search", "multimedia", "rag"],
                examples=[
                    "Find where the presenter discusses machine learning",
                    "Show me all scenes with the CEO",
                    "When does the chart appear?",
                    "What topics are covered in this video?",
                ],
            ),
            AgentSkill(
                id="video-qa",
                name="Video Question Answering",
                description=(
                    "Answer questions about video content with timestamped citations. "
                    "Synthesizes information from visual descriptions, speech transcripts, "
                    "and detected entities to provide comprehensive answers."
                ),
                tags=["qa", "video", "analysis", "comprehension"],
                examples=[
                    "What is the main topic of this video?",
                    "Summarize what happens in the first 5 minutes",
                    "Who are the speakers in this video?",
                    "What products are mentioned?",
                ],
            ),
            AgentSkill(
                id="entity-discovery",
                name="Entity Discovery",
                description=(
                    "Find and track entities (people, objects, brands, concepts) "
                    "throughout the video. Shows when and where entities appear."
                ),
                tags=["entities", "tracking", "detection", "ner"],
                examples=[
                    "List all people mentioned in this video",
                    "When does Apple appear in the video?",
                    "Track all mentions of the product name",
                ],
            ),
            AgentSkill(
                id="highlight-discovery",
                name="Highlight Discovery",
                description=(
                    "Find key moments, highlights, and viral-worthy segments in videos. "
                    "Identifies engaging content based on visual, audio, and semantic analysis."
                ),
                tags=["highlights", "clips", "viral", "engagement"],
                examples=[
                    "Find the most engaging moments",
                    "What are the key highlights?",
                    "Show me viral-worthy clips",
                ],
            ),
        ],
        iconUrl=f"{base_url}/static/qprisma-icon.png",
    )


def get_editor_agent_card() -> AgentCard:
    """Build the AgentCard for the Editor Agent."""
    base_url = get_base_url()

    return AgentCard(
        name="QPrisma Editor Agent",
        description=(
            "A conversational video editing agent (Chat-to-Edit). Create and modify "
            "video clips through natural language. Supports clip creation, subtitle "
            "styling, reordering, and project management."
        ),
        supportedInterfaces=[
            AgentInterface(
                url=f"{base_url}/a2a/editor",
                protocolBinding="HTTP+JSON",
                protocolVersion="1.0",
            ),
        ],
        provider=AgentProvider(
            organization="QPrisma",
            url="https://github.com/alexandergg/QPrisma",
        ),
        version="1.0.0",
        documentationUrl="https://github.com/alexandergg/QPrisma/blob/main/API_DOCUMENTATION.md",
        capabilities=AgentCapabilities(
            streaming=True,
            pushNotifications=False,
            extendedAgentCard=True,
        ),
        defaultInputModes=["text/plain", "application/json"],
        defaultOutputModes=["text/plain", "application/json"],
        skills=[
            AgentSkill(
                id="clip-creation",
                name="Clip Creation",
                description=(
                    "Create video clips from timestamps or search results. "
                    "Automatically finds relevant segments based on content queries."
                ),
                tags=["clips", "editing", "creation"],
                examples=[
                    "Create a clip from 1:30 to 2:45",
                    "Make a clip of when they discuss pricing",
                    "Extract the intro section as a clip",
                ],
            ),
            AgentSkill(
                id="clip-modification",
                name="Clip Modification",
                description=(
                    "Modify existing clips - change timing, add/remove subtitles, "
                    "update styling, and reorder within the project."
                ),
                tags=["editing", "modification", "subtitles"],
                examples=[
                    "Add subtitles to clip 1",
                    "Change the style of subtitles to bold white",
                    "Extend clip 2 by 5 seconds",
                    "Move clip 3 to the beginning",
                ],
            ),
            AgentSkill(
                id="highlight-clips",
                name="Auto-Generate Highlight Clips",
                description=(
                    "Automatically generate clips from video highlights and "
                    "viral-worthy moments detected in the video."
                ),
                tags=["highlights", "automation", "clips"],
                examples=[
                    "Create clips from the top highlights",
                    "Generate clips for social media",
                    "Make clips from the most engaging moments",
                ],
            ),
            AgentSkill(
                id="project-management",
                name="Project Management",
                description=(
                    "Manage editing projects - list clips, get project status, "
                    "export configurations, and organize content."
                ),
                tags=["project", "management", "export"],
                examples=[
                    "Show me all clips in this project",
                    "What's the total duration of all clips?",
                    "Prepare this project for export",
                ],
            ),
        ],
        iconUrl=f"{base_url}/static/qprisma-editor-icon.png",
    )
