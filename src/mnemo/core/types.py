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


class TargetProfile(BaseModel):
    """A user-provided profile describing a target system under assessment.

    This is the security-domain analogue of the LaMP "user profile": a
    collection of entries (``ProfileEntry``) that personalize a scan/test
    prompt to a specific target. Retrieval selects the entries relevant to a
    given prompt and injects them, instead of pushing the whole profile.
    """

    id: str
    target: str
    authorization: str = ""
    description: str = ""
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    metadata: dict = Field(default_factory=dict)


class ProfileEntry(BaseModel):
    """One retrievable item in a ``TargetProfile`` (e.g. an endpoint, the auth
    model, a stack note, a prior finding)."""

    id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    profile_id: str
    content: str
    trust_level: TrustLevel = TrustLevel.EXTERNAL_DOCUMENT
    source: str = ""
    embedding: list[float] | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    last_accessed: datetime = Field(default_factory=lambda: datetime.now(UTC))
    access_count: int = 0
    metadata: dict = Field(default_factory=dict)

    def as_memory(self) -> Memory:
        """View this entry as a ``Memory`` so it can reuse the shared
        retrieval-scoring and prompt-injection pipeline."""
        return Memory(
            id=self.id,
            content=self.content,
            memory_type=MemoryType.SEMANTIC,
            trust_level=self.trust_level,
            source=self.source,
            embedding=self.embedding,
            created_at=self.created_at,
            last_accessed=self.last_accessed,
            access_count=self.access_count,
            metadata={**self.metadata, "profile_id": self.profile_id},
        )
