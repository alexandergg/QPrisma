---
description: Create a new tool for the LangGraph video agent following QPrisma patterns
---

# Create Agent Tool

Create a new tool for the LangGraph video agent following QPrisma patterns.

## Usage
```
/create-tool <tool_name> [--category search|editor]
```

## Instructions

When creating a new agent tool for QPrisma, follow these patterns:

### 1. Add the tool to `backend/agent/tools/general.py` (search tools) or `backend/agent/tools/editor.py` (editor tools)

```python
import logging
from typing import Annotated, Any

from langchain_core.tools import tool
from langgraph.prebuilt import InjectedState

from agent.utils.formatting import format_timestamp

logger = logging.getLogger(__name__)


@tool
async def {tool_name}(
    query: Annotated[str, "What to search for"],
    limit: Annotated[int, "Maximum results to return"] = 10,
    media_id: Annotated[str | None, InjectedState("media_id")] = None,
) -> dict[str, Any]:
    """
    {Tool description for the LLM to understand when to use this tool}.

    Use when: {Describe when the LLM should choose this tool}.
    Do NOT use: {Describe when another tool is more appropriate}.

    Returns dict with 'results', 'count', and optional 'error'.
    """
    if not media_id:
        return {"error": "No video context available.", "results": [], "count": 0}

    try:
        from api.dependencies import get_graph_search_service

        search_service = get_graph_search_service()

        # Implementation
        results = []

        # Format timestamps for readability
        formatted_results = []
        for r in results:
            formatted_results.append({
                "timestamp": r.get("timestamp", 0),
                "timestamp_formatted": format_timestamp(r.get("timestamp", 0)),
                "content": r.get("content", ""),
                "type": r.get("type", "unknown"),
                "score": r.get("score", 0),
            })

        return {
            "results": formatted_results[:limit],
            "count": len(formatted_results),
            "query": query,
            "media_id": media_id,
        }

    except Exception as e:
        logger.error(f"Error in {tool_name}: {e}")
        return {
            "error": str(e),
            "results": [],
            "count": 0,
        }
```

### 2. Export the tool in `backend/agent/tools/__init__.py`

Add to imports:
```python
from .general import {tool_name}  # or from .editor import {tool_name}
```

Add to the appropriate tool list:
```python
# For search/analysis tools (in general.py)
SEARCH_TOOLS = [
    # ... existing 16 tools
    {tool_name},
]

# For editor tools (in editor.py)
EDITOR_TOOLS = [
    # ... existing 15 tools
    {tool_name},
]
```

Add to `__all__`:
```python
__all__ = [
    # ... existing exports
    "{tool_name}",
]
```

### 3. Tool Design Guidelines

**Input Parameters:**
- Use `Annotated[type, "description"]` for all parameters (LLM sees the description)
- Use `InjectedState("media_id")` for context injection (NOT a direct `media_id: str` parameter)
- `InjectedState` parameters are auto-injected by LangGraph and hidden from the LLM
- Provide sensible defaults for optional parameters
- Keep parameters simple (str, int, float, bool, list)

**Output Structure:**
- Always return a dict (never raise exceptions to the agent)
- Include `error` key if something went wrong
- Include `results` as a list for search-type tools
- Always format timestamps using `format_timestamp()` from `agent.utils.formatting`
- Include metadata like `count`, `query` for context

**Docstring:**
- Write clear description of WHEN the LLM should use this tool
- Include "Use when:" and "Do NOT use:" guidance
- Document return structure

### 4. Test the tool at `backend/tests/test_{tool_name}.py`

```python
"""Tests for {tool_name} tool."""

import pytest
from unittest.mock import AsyncMock, patch

from agent.tools.general import {tool_name}  # or editor


class Test{ToolName}:
    """Test cases for {tool_name}."""

    async def test_{tool_name}_no_media_id(self):
        """Test {tool_name} without media context returns error."""
        result = await {tool_name}.ainvoke(
            {"query": "test"},
            config={"configurable": {"media_id": None}},
        )
        assert "error" in result

    async def test_{tool_name}_success(self):
        """Test successful {tool_name} execution."""
        with patch("agent.tools.general.get_graph_search_service") as mock_svc:
            mock_svc.return_value = AsyncMock()
            result = await {tool_name}.ainvoke(
                {"query": "test query"},
                config={"configurable": {"media_id": "test-123"}},
            )
            assert "results" in result
```

## Tool File Structure

Tools live in two files only:

| File | Tool List | Count | Purpose |
|------|-----------|-------|---------|
| `agent/tools/general.py` | `SEARCH_TOOLS` | 16 (12 single-video + 4 multi-video) | Search, analysis, navigation |
| `agent/tools/editor.py` | `EDITOR_TOOLS` | 15 | Clip editing, subtitles, export |

### Search Tools (general.py)

| Tool | Purpose |
|------|---------|
| `search_video` | Semantic search for moments, topics, objects |
| `find_entity` | Find specific entities (person, object, concept) |
| `get_transcript` | Get transcript for a time range |
| `describe_scene` | Describe visual content at a timestamp |
| `get_scene_context` | Get context around a timestamp |
| `list_chapters` | List video chapters/sections |
| `get_video_info` | Get video metadata |
| `get_summary` | Get video summary (brief/detailed/comprehensive) |
| `get_related_content` | Explore knowledge graph connections |
| `get_entity_timeline` | Track entity appearances across video |
| `compare_moments` | Compare multiple timestamps |
| `find_highlights` | Find highlight-worthy moments |
| `search_across_videos` | Search across multiple videos |
| `compare_videos` | Compare aspects across videos |
| `find_common_entities` | Find shared entities across videos |
| `get_library_overview` | Overview of video library |

### Editor Tools (editor.py)

| Tool | Purpose |
|------|---------|
| `create_clip` | Create a new clip |
| `modify_clip` | Change clip properties |
| `delete_clip` | Remove a clip |
| `list_clips` | List all clips in project |
| `reorder_clips` | Change clip position |
| `generate_auto_clips` | AI-generated clip suggestions |
| `add_suggested_clips` | Accept AI suggestions |
| `add_subtitles` | Add subtitles to clip |
| `change_subtitle_style` | Change subtitle style |
| `remove_subtitles` | Remove subtitles |
| `list_subtitle_styles` | List available styles |
| `export_clip` | Export single clip |
| `export_all_clips` | Export all clips |
| `get_export_status` | Check export progress |
| `list_export_presets` | List export presets |

## Checklist
- [ ] Tool function created with `@tool` decorator
- [ ] Uses `Annotated[type, "description"]` for parameters
- [ ] Uses `InjectedState("media_id")` for video context (not direct parameter)
- [ ] Async function with `dict[str, Any]` return type
- [ ] Clear docstring with "Use when" / "Do NOT use" guidance
- [ ] Error handling returns dict, never raises exceptions
- [ ] Timestamps formatted with `format_timestamp()` from `agent.utils.formatting`
- [ ] Tool added to `SEARCH_TOOLS` or `EDITOR_TOOLS` list
- [ ] Tool exported in `__init__.py`
- [ ] Tests created
