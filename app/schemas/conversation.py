"""
Conversation and message schemas for request validation and response serialization.
"""

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field


class MessageBase(BaseModel):
    """Base message schema."""

    role: str = Field(..., pattern="^(user|assistant)$")
    content: str = Field(..., min_length=1, max_length=50000)


class MessageCreate(BaseModel):
    """Schema for creating a new message."""

    content: str = Field(..., min_length=1, max_length=50000)


class MessageResponse(MessageBase):
    """Schema for message data in responses."""

    id: int
    conversation_id: int
    created_at: datetime

    class Config:
        from_attributes = True


class ConversationBase(BaseModel):
    """Base conversation schema."""

    title: str = Field(..., min_length=1, max_length=255)


class ConversationCreate(ConversationBase):
    """Schema for creating a new conversation."""

    pass


class ConversationUpdate(BaseModel):
    """Schema for updating a conversation."""

    title: Optional[str] = Field(None, min_length=1, max_length=255)


class ConversationResponse(ConversationBase):
    """Schema for conversation data in responses."""

    id: int
    user_id: int
    created_at: datetime
    updated_at: datetime
    messages: List[MessageResponse] = []
    summary: Optional[str] = None

    class Config:
        from_attributes = True


class ConversationListResponse(BaseModel):
    """Schema for conversation list (without messages)."""

    id: int
    title: str
    created_at: datetime
    updated_at: datetime
    message_count: int = 0

    class Config:
        from_attributes = True


class ChatRequest(BaseModel):
    """Schema for chat request."""

    message: str = Field(..., min_length=1, max_length=50000)
    conversation_id: Optional[int] = None
    mode: Optional[str] = Field(None, pattern="^(general|programming|reasoning|creative)$")
    stream: bool = False


class ImportMessage(BaseModel):
    """Schema for a message to import into a conversation (no AI call)."""

    role: str = Field(..., pattern="^(user|assistant)$")
    content: str = Field(..., min_length=1, max_length=50000)


class ConversationImport(BaseModel):
    """Schema for importing a conversation with its full message history."""

    title: str = Field(..., min_length=1, max_length=255)
    messages: List[ImportMessage] = []


class ChatResponse(BaseModel):
    """Schema for chat response."""

    message: MessageResponse
    conversation_id: int


class StreamChatResponse(BaseModel):
    """Schema for streaming chat response events."""

    type: str  # "content", "done", "error"
    content: Optional[str] = None
    message: Optional[MessageResponse] = None
    conversation_id: Optional[int] = None
    error: Optional[str] = None
    code: Optional[str] = None


class ConversationSummary(BaseModel):
    """Schema for conversation summary."""

    id: int
    title: str
    summary: Optional[str] = None
    message_count: int
    created_at: datetime
    updated_at: datetime
