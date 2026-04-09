"""
QPrisma Agent Tool Definitions
===============================

OpenAI function-calling schema for all 17 QPrisma LangGraph agent tools.
Used by Foundry tool evaluators (``tool_call_accuracy``, ``tool_selection``,
``tool_input_accuracy``, ``tool_output_utilization``) to assess whether the
agent selected the right tools with correct parameters.

Only *user-facing* parameters are included.  ``InjectedState`` parameters
(``media_id``, ``user_id``, ``media_ids``, ``session_id``) are framework-
injected and invisible to the LLM, so they are excluded.
"""

from __future__ import annotations

TOOL_DEFINITIONS: list[dict] = [
    # -----------------------------------------------------------------------
    # search_tools.py
    # -----------------------------------------------------------------------
    {
        "type": "function",
        "function": {
            "name": "search_video",
            "description": (
                "Primary search tool. Uses hybrid retrieval (semantic, lexical, graph, and "
                "reranking) to find specific moments, objects, or discussions in the video. "
                "Returns ranked results with timestamps, descriptions, and relevance scores."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "What to search for in the video",
                    },
                    "content_type": {
                        "type": "string",
                        "description": "Type of content: 'all', 'visual', or 'audio'",
                        "default": "all",
                    },
                    "time_range_start": {
                        "type": "number",
                        "description": "Start of time range in seconds",
                    },
                    "time_range_end": {
                        "type": "number",
                        "description": "End of time range in seconds",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum results to return",
                        "default": 5,
                    },
                    "target_video_id": {
                        "type": "string",
                        "description": (
                            "When several videos are selected, specify which video to search"
                        ),
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "find_entity",
            "description": (
                "Quick entity lookup — find where a specific person, object, or concept "
                "appears. Returns timestamps and brief descriptions for each occurrence."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "entity_name": {
                        "type": "string",
                        "description": "Name of the entity to find",
                    },
                    "entity_type": {
                        "type": "string",
                        "description": (
                            "Type: 'person', 'object', 'concept', 'location', or 'any'"
                        ),
                        "default": "any",
                    },
                },
                "required": ["entity_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_transcript",
            "description": (
                "Get the exact transcript (spoken words/narration) for a video. Use this tool "
                "to quote verbatim dialogue, narration, or any exact words spoken."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "start_time": {
                        "type": "number",
                        "description": "Start time in seconds (omit for full transcript)",
                    },
                    "end_time": {
                        "type": "number",
                        "description": "End time in seconds (omit for full transcript)",
                    },
                    "include_speakers": {
                        "type": "boolean",
                        "description": "Include speaker identification if available",
                        "default": True,
                    },
                    "target_video_id": {
                        "type": "string",
                        "description": (
                            "When several videos are selected, specify which video's "
                            "transcript to retrieve"
                        ),
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "describe_scene",
            "description": (
                "Point-in-time visual lookup — shows what is happening at a specific timestamp "
                "by returning the nearest frame's detailed description."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "timestamp": {
                        "type": "number",
                        "description": "Timestamp in seconds to describe",
                    },
                    "target_video_id": {
                        "type": "string",
                        "description": (
                            "When several videos are selected, specify which video to describe"
                        ),
                    },
                },
                "required": ["timestamp"],
            },
        },
    },
    # -----------------------------------------------------------------------
    # context_tools.py
    # -----------------------------------------------------------------------
    {
        "type": "function",
        "function": {
            "name": "list_chapters",
            "description": (
                "Get the chronological chapter structure and timeline of the video. Returns "
                "scenes grouped into chapters with titles, time ranges, and summaries."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "target_video_id": {
                        "type": "string",
                        "description": (
                            "When several videos are selected, specify which video's "
                            "chapters to retrieve"
                        ),
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_video_info",
            "description": (
                "Get basic info about a video: title, duration, resolution, fps, and "
                "processing status."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "target_video_id": {
                        "type": "string",
                        "description": (
                            "When several videos are selected, specify which video's info "
                            "to retrieve"
                        ),
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_summary",
            "description": (
                "Get a single synopsis summary of the video with title, topics, and duration."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "level": {
                        "type": "string",
                        "description": (
                            "Hint for response style: 'brief', 'detailed', or 'comprehensive'"
                        ),
                        "default": "brief",
                    },
                    "target_video_id": {
                        "type": "string",
                        "description": (
                            "When several videos are selected, specify which video to summarize"
                        ),
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_scene_context",
            "description": (
                "Get comprehensive context around a specific moment in the video using a time "
                "window. Returns frames and audio organized as before/during/after phases."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "timestamp": {
                        "type": "number",
                        "description": "Center timestamp in seconds",
                    },
                    "window_seconds": {
                        "type": "number",
                        "description": "Context window size (seconds before and after)",
                        "default": 30.0,
                    },
                    "target_video_id": {
                        "type": "string",
                        "description": (
                            "When several videos are selected, specify which video's scene "
                            "to examine"
                        ),
                    },
                },
                "required": ["timestamp"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_community_overview",
            "description": (
                "Get thematic community summaries for a video. Communities are pre-computed "
                "clusters of related entities and content that reveal major themes."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "topic": {
                        "type": "string",
                        "description": "Optional topic to filter communities by",
                    },
                    "target_video_id": {
                        "type": "string",
                        "description": (
                            "When several videos are selected, specify which video's "
                            "communities to retrieve"
                        ),
                    },
                },
                "required": [],
            },
        },
    },
    # -----------------------------------------------------------------------
    # analysis_tools.py
    # -----------------------------------------------------------------------
    {
        "type": "function",
        "function": {
            "name": "get_related_content",
            "description": (
                "Explore the knowledge graph to find related entities and connections by "
                "traversing relationships (1-3 hops from matching nodes)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "topic": {
                        "type": "string",
                        "description": "Topic or concept to explore connections for",
                    },
                    "depth": {
                        "type": "integer",
                        "description": "How many relationship hops to explore (1-3)",
                        "default": 2,
                    },
                },
                "required": ["topic"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_entity_timeline",
            "description": (
                "Build a complete chronological timeline of all appearances of an entity "
                "throughout the video. Returns ordered moments with rich detail."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "entity_name": {
                        "type": "string",
                        "description": "Name of the entity to track",
                    },
                    "entity_type": {
                        "type": "string",
                        "description": (
                            "Type: 'person', 'object', 'concept', 'location', or 'any'"
                        ),
                        "default": "any",
                    },
                    "include_context": {
                        "type": "boolean",
                        "description": "Include surrounding context for each appearance",
                        "default": True,
                    },
                },
                "required": ["entity_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "compare_moments",
            "description": (
                "Compare multiple moments in the video side by side. Useful for understanding "
                "progression, changes, or differences between scenes."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "timestamps": {
                        "type": "array",
                        "items": {"type": "number"},
                        "description": "List of timestamps (in seconds) to compare (2-5)",
                    },
                    "comparison_aspect": {
                        "type": "string",
                        "description": "What to compare: 'visual', 'audio', 'all'",
                        "default": "all",
                    },
                },
                "required": ["timestamps"],
            },
        },
    },
    # -----------------------------------------------------------------------
    # multi_video_tools.py
    # -----------------------------------------------------------------------
    {
        "type": "function",
        "function": {
            "name": "search_across_videos",
            "description": (
                "Search for content across multiple videos. Returns results grouped by video."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "What to search for across all videos",
                    },
                    "limit_per_video": {
                        "type": "integer",
                        "description": "Maximum results per video",
                        "default": 3,
                    },
                    "max_videos": {
                        "type": "integer",
                        "description": "Maximum number of videos to search",
                        "default": 5,
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "compare_videos",
            "description": (
                "Compare content across multiple selected videos. Finds how each video covers "
                "a given topic and highlights similarities and differences."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": (
                            "What aspect to compare across the selected videos "
                            "(e.g., 'revenue growth', 'main topics', 'speakers')"
                        ),
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "find_common_entities",
            "description": (
                "Find entities (people, objects, concepts) that appear across multiple "
                "selected videos. Returns entities sorted by how many videos they appear in."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "entity_type": {
                        "type": "string",
                        "description": (
                            "Type filter: 'person', 'object', 'concept', 'location', or 'any'"
                        ),
                        "default": "any",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max entities to return",
                        "default": 15,
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_library_overview",
            "description": (
                "Get an overview of all selected videos: titles, summaries, topics, and "
                "durations. Use this to understand what videos are loaded before doing "
                "cross-video analysis."
            ),
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
    # -----------------------------------------------------------------------
    # highlight_tools.py
    # -----------------------------------------------------------------------
    {
        "type": "function",
        "function": {
            "name": "find_highlights",
            "description": (
                "Identify highlight moments suitable for clips or social media. Returns "
                "exportable time ranges with descriptions of why they're highlights."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "criteria": {
                        "type": "string",
                        "description": (
                            "What makes a moment a highlight: 'engagement', 'action', "
                            "'key_topics', 'all'"
                        ),
                        "default": "all",
                    },
                    "max_clips": {
                        "type": "integer",
                        "description": "Maximum number of highlight clips to suggest",
                        "default": 5,
                    },
                    "min_duration": {
                        "type": "number",
                        "description": "Minimum clip duration in seconds",
                        "default": 10.0,
                    },
                    "max_duration": {
                        "type": "number",
                        "description": "Maximum clip duration in seconds",
                        "default": 60.0,
                    },
                },
                "required": [],
            },
        },
    },
]
