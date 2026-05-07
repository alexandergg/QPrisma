"""
Models package for QPrisma.

This package contains all Pydantic models, database models, and configuration types.
"""

from .api_schemas import (
    AuthConfigResponse,
    EnhancedSearchRequest,
    # Processing
    ProcessingSearchRequest,
    SearchRequest,
    SearchResponse,
    SearchResult,
    # Auth
    UserResponse,
)
from .user import EntraTokenData, User, UserInDB

__all__ = [
    # User models
    "User",
    "UserInDB",
    "EntraTokenData",
    # API Schemas - Auth
    "UserResponse",
    "AuthConfigResponse",
    # API Schemas - Search
    "SearchRequest",
    "SearchResult",
    "SearchResponse",
    # API Schemas - Processing
    "ProcessingSearchRequest",
    "EnhancedSearchRequest",
]
