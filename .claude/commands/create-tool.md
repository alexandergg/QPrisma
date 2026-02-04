# Create Agent Tool

Create a new tool for the LangGraph video agent following QPrisma patterns.

## Usage
```
/create-tool <tool_name> [--category search|editor|navigation|export]
```

## Instructions

When creating a new agent tool for QPrisma, follow these patterns:

### 1. Create the tool file at `backend/agent/tools/{category}_tools.py` (or add to existing)

```python
"""
{Category} Tools
{'=' * (len(category) + 6)}

Tools for {description}.
"""

import logging
from typing import Any

from langchain_core.tools import tool

from agent.tools.base import format_timestamp, get_media_context
from services.database_service import get_database_service
from services.knowledge_graph import get_knowledge_graph_service

logger = logging.getLogger(__name__)


@tool
async def {tool_name}(
    media_id: str,
    query: str,
    limit: int = 10,
) -> dict[str, Any]:
    """
    {Tool description for the LLM to understand when to use this tool}.

    Args:
        media_id: The video/media ID to operate on
        query: {Description of query parameter}
        limit: Maximum number of results to return

    Returns:
        Dictionary containing:
        - results: List of matching items with timestamps
        - count: Total number of results
        - query: The original query for reference
    """
    try:
        # Get services
        db = get_database_service()
        kg = get_knowledge_graph_service()

        # Validate media exists
        media = await db.get_media(media_id)
        if not media:
            return {
                "error": f"Media {media_id} not found",
                "results": [],
                "count": 0,
            }

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
from agent.tools.{category}_tools import {tool_name}
```

Add to the appropriate tool list:
```python
# For search/navigation tools
SEARCH_TOOLS = [
    # ... existing tools
    {tool_name},
]

# For editor tools
EDITOR_TOOLS = [
    # ... existing tools
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
- Always include `media_id` as first parameter for video context
- Use descriptive parameter names
- Provide sensible defaults for optional parameters
- Keep parameters simple (str, int, float, bool, list)

**Output Structure:**
- Always return a dict (never raise exceptions to the agent)
- Include `error` key if something went wrong
- Include `results` as a list for search-type tools
- Always format timestamps using `format_timestamp()` helper
- Include metadata like `count`, `query` for context

**Docstring:**
- Write clear description of WHEN the LLM should use this tool
- Document all parameters with types
- Document return structure

### 4. Test the tool at `backend/tests/test_{tool_name}.py`

```python
"""Tests for {tool_name} tool."""

import pytest

from agent.tools.{category}_tools import {tool_name}


class Test{ToolName}:
    """Test cases for {tool_name}."""

    @pytest.fixture
    def sample_media_id(self):
        return "test-media-123"

    @pytest.mark.asyncio
    async def test_{tool_name}_success(self, sample_media_id):
        """Test successful {tool_name} execution."""
        result = await {tool_name}(
            media_id=sample_media_id,
            query="test query",
        )
        assert "results" in result
        assert "error" not in result or result["error"] is None

    @pytest.mark.asyncio
    async def test_{tool_name}_invalid_media(self):
        """Test {tool_name} with invalid media ID."""
        result = await {tool_name}(
            media_id="invalid-id",
            query="test query",
        )
        assert "error" in result
```

## Tool Categories

| Category | Purpose | Examples |
|----------|---------|----------|
| `search` | Finding content in videos | `search_video`, `find_entity` |
| `navigation` | Moving through video timeline | `describe_scene`, `get_transcript` |
| `structure` | Video metadata and structure | `get_video_info`, `list_chapters` |
| `graph` | Knowledge graph operations | `get_related_content`, `navigate_timeline` |
| `editor` | Clip editing operations | `create_clip`, `modify_clip` |
| `export` | Exporting clips/content | `export_clip`, `export_all_clips` |
| `subtitle` | Subtitle operations | `add_subtitles`, `change_subtitle_style` |

## Checklist
- [ ] Tool function created with `@tool` decorator
- [ ] Async function with proper type hints
- [ ] Comprehensive docstring for LLM understanding
- [ ] Error handling returns dict, not exceptions
- [ ] Timestamps formatted for readability
- [ ] Tool exported in `__init__.py`
- [ ] Added to appropriate tool list (SEARCH_TOOLS/EDITOR_TOOLS)
- [ ] Tests created
