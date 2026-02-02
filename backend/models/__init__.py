"""
Models package for QPrisma.

This package contains all Pydantic models, database models, and configuration types.
"""

from .api_schemas import (
    # Auth
    RegisterRequest,
    LoginRequest,
    TokenResponse,
    UserResponse,
    # Chat
    ChatMessage,
    ChatRequest,
    ChatResponse,
    SearchRequest,
    SearchResult,
    SearchResponse,
    AgentChatRequest,
    AgentChatResponse,
    # Batch
    BatchStatusResponse,
    CostEstimateResponse,
    # Processing
    ProcessingSearchRequest,
    EnhancedSearchRequest,
)
from .user import User, UserCreate, UserInDB, Token, TokenData

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
