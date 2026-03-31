"""
Models package for QPrisma.

This package contains all Pydantic models, database models, and configuration types.
"""

from .api_schemas import (
    AgentChatRequest,
    AgentChatResponse,
    AuthConfigResponse,
    # Batch
    BatchStatusResponse,
    # Chat
    ChatMessage,
    ChatRequest,
    ChatResponse,
    CostEstimateResponse,
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
    # API Schemas - Chat
    "ChatMessage",
    "ChatRequest",
    "ChatResponse",
    "SearchRequest",
    "SearchResult",
    "SearchResponse",
    "AgentChatRequest",
    "AgentChatResponse",
    # API Schemas - Batch
    "BatchStatusResponse",
    "CostEstimateResponse",
    # API Schemas - Processing
    "ProcessingSearchRequest",
    "EnhancedSearchRequest",
]
