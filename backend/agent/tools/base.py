"""
Base Tool Definition
====================

Base class for agent tools with Azure OpenAI function calling schema.
"""

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class ToolParameter:
    """Definition of a tool parameter."""

    name: str
    type: str  # "string", "number", "integer", "boolean", "array", "object"
    description: str
    required: bool = True
    enum: list[str] | None = None
    default: Any = None
    items: dict[str, str] | None = None  # For array types: {"type": "string"}


class BaseTool(ABC):
    """
    Base class for agent tools.

    Provides:
    - OpenAI function calling schema generation
    - Consistent error handling
    - Logging and metrics
    """

    name: str
    description: str
    parameters: list[ToolParameter]

    @property
    def definition(self) -> dict:
        """
        Generate OpenAI function calling schema.

        Returns:
            Dict in OpenAI tool format
        """
        properties = {}
        required = []

        for param in self.parameters:
            prop = {
                "type": param.type,
                "description": param.description,
            }
            if param.enum:
                prop["enum"] = param.enum
            if param.default is not None:
                prop["default"] = param.default
            if param.type == "array" and param.items:
                prop["items"] = param.items

            properties[param.name] = prop

            if param.required:
                required.append(param.name)

        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": properties,
                    "required": required,
                },
            },
        }

    @abstractmethod
    async def execute(self, media_id: str | None, **kwargs) -> dict[str, Any]:
        """
        Execute the tool.

        Args:
            media_id: Current video context
            **kwargs: Tool-specific parameters

        Returns:
            Tool result as dictionary
        """
        pass

    async def __call__(self, media_id: str | None, **kwargs) -> dict[str, Any]:
        """Execute the tool with error handling."""
        try:
            logger.info(f"Executing tool {self.name} with args: {kwargs}")
            result = await self.execute(media_id, **kwargs)
            logger.info(f"Tool {self.name} completed successfully")
            return result
        except Exception as e:
            logger.error(f"Tool {self.name} failed: {e}")
            return {
                "error": str(e),
                "tool": self.name,
            }


def format_timestamp(seconds: float) -> str:
    """Format seconds as MM:SS or HH:MM:SS."""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)

    if hours > 0:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def parse_timestamp(timestamp_str: str) -> float:
    """Parse MM:SS or HH:MM:SS to seconds."""
    parts = timestamp_str.split(":")
    if len(parts) == 2:
        return int(parts[0]) * 60 + int(parts[1])
    elif len(parts) == 3:
        return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
    return float(timestamp_str)
