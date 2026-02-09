"""
Method adapters for the evaluation framework.

Each adapter wraps a video understanding method behind a common interface
(BaseMethodAdapter) so the evaluation runner can treat them uniformly.
"""

from .base import BaseMethodAdapter

__all__ = ["BaseMethodAdapter"]
