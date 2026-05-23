"""Pydantic schemas — API contract cho team web tích hợp."""

from typing import Literal
from pydantic import BaseModel, Field

Topic = Literal["breed", "nutrition", "health", "care", "behavior", "auto"]
Level = Literal["beginner", "advanced", "auto"]


class Message(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class ChatRequest(BaseModel):
    messages: list[Message] = Field(..., min_length=1)
    session_id: str | None = None
    user_level: Level = "auto"
    topic_filter: Topic = "auto"
    top_k: int = Field(default=5, ge=1, le=20)


class Citation(BaseModel):
    index: int
    source_url: str
    source_name: str
    section_title: str | None = None
    snippet: str  # ~200 chars đầu của chunk


class ChatResponse(BaseModel):
    reply: str
    citations: list[Citation]
    topic_detected: str | None = None
    needs_vet: bool = False  # True nếu chunks có severity=high hoặc content_type=warning
    session_id: str
