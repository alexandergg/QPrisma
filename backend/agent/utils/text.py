"""
Text Utilities
==============

Shared text cleaning and content validation for agent tools and services.
"""

import re

_LEADING_LIST_MARKER_RE = re.compile(r"^\d+\.\s*\*?\*?")

SCENE_DESCRIPTION_PREFIXES = (
    "General scene description:",
    "General description:",
    "Scene description:",
    "Descripción general de la escena:",
    "Descripción general:",
)

VIDEO_SUMMARY_PREFIXES = SCENE_DESCRIPTION_PREFIXES + (
    "The image shows",
    "La imagen muestra",
)

INVALID_CONTENT_PHRASES = (
    "black screen",
    "completely black",
    "no visible",
    "no information",
    "imagen negra",
    "completamente negra",
    "no contiene elementos",
    "no hay información",
)


def clean_generated_text(text: str, prefixes: tuple[str, ...]) -> str:
    """Normalize generated descriptions by stripping markdown, prefixes, and extra whitespace."""
    clean = _LEADING_LIST_MARKER_RE.sub("", text).replace("**", "").replace("\n", " ")
    clean = re.sub(r"\s+", " ", clean).strip()
    for prefix in prefixes:
        if clean.startswith(prefix):
            clean = clean[len(prefix) :].strip()
    return clean


def is_valid_content(desc: str) -> bool:
    """Check if a frame description contains meaningful content (not black screen, etc.)."""
    if not desc:
        return False
    desc_lower = desc.lower()
    return not any(phrase in desc_lower for phrase in INVALID_CONTENT_PHRASES)
