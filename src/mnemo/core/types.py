from __future__ import annotations

import uuid
from datetime import UTC, datetime
from enum import Enum

from pydantic import BaseModel, Field


class MemoryType(str, Enum):
    EPISODIC = "episodic"
    SEMANTIC = "semantic"
    PROCEDURAL = "procedural"


class TrustLevel(str, Enum):
    USER_STATED = "user_stated"
    AGENT_INFERRED = "agent_inferred"
    EXTERNAL_DOCUMENT = "external_document"
    UNKNOWN = "unknown"


class Memory(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    content: str
    memory_type: MemoryType = MemoryType.SEMANTIC
    trust_level: TrustLevel = TrustLevel.UNKNOWN
    source: str = ""
    embedding: list[float] | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    last_accessed: datetime = Field(default_factory=lambda: datetime.now(UTC))
    access_count: int = 0
    decay_score: float = 1.0
    metadata: dict = Field(default_factory=dict)


class MemoryQuery(BaseModel):
    text: str
    top_k: int = 5
    memory_type: MemoryType | None = None
    trust_level: TrustLevel | None = None
    min_score: float = 0.0
    recency_weight: float = 0.3


class MemoryResult(BaseModel):
    memory: Memory
    score: float
    retrieval_rank: int
