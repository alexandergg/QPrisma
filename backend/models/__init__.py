"""
Models package for QPrisma.

This package contains all Pydantic models, database models, and configuration types.
"""

from .api_schemas import (
    AgentChatRequest,
    AgentChatResponse,
    # Batch
    BatchStatusResponse,
    # Chat
    ChatMessage,
    ChatRequest,
    ChatResponse,
    CostEstimateResponse,
    EnhancedSearchRequest,
    LoginRequest,
    # Processing
    ProcessingSearchRequest,
    # Auth
    RegisterRequest,
    SearchRequest,
    SearchResponse,
    SearchResult,
    TokenResponse,
    UserResponse,
)
from .user import Token, TokenData, User, UserCreate, UserInDB

__all__ = [
    # User models
    "User",
    "UserCreate",
    "UserInDB",
    "Token",
    "TokenData",
    # API Schemas - Auth
    "RegisterRequest",
    "LoginRequest",
    "TokenResponse",
    "UserResponse",
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
