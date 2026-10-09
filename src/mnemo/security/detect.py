from __future__ import annotations

import math

from mnemo.core.types import Memory, MemoryType

IMPERATIVE_WORDS = {
    "must", "always", "never", "shall", "should", "ensure", "require",
    "execute", "run", "ignore", "override", "disregard", "obey", "comply",
}


def instruction_density(content: str) -> float:
    words = content.lower().split()
    if not words:
        return 0.0
    count = sum(1 for w in words if w.strip(".,!?;:") in IMPERATIVE_WORDS)
    return count / len(words)


def _cosine_distance(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0 or norm_b == 0:
        return 1.0
    return 1.0 - dot / (norm_a * norm_b)


def check_embedding_outlier(
    embedding: list[float],
    type_centroids: dict[str, list[float]],
    memory_type: str,
    threshold: float = 0.5,
) -> bool:
    centroid = type_centroids.get(memory_type)
    if centroid is None:
        return False
    return _cosine_distance(embedding, centroid) > threshold


_DENSITY_THRESHOLDS: dict[MemoryType, float] = {
    MemoryType.SEMANTIC: 0.15,
    MemoryType.EPISODIC: 0.15,
    MemoryType.PROCEDURAL: 0.30,
}


def detect_suspicious(
    memory: Memory,
    type_centroids: dict[str, list[float]] | None = None,
) -> list[str]:
    flags: list[str] = []

    density = instruction_density(memory.content)
    threshold = _DENSITY_THRESHOLDS.get(memory.memory_type, 0.15)
    if density > threshold:
        flags.append(f"high_instruction_density ({density:.2f} > {threshold})")

    if (
        memory.embedding
        and type_centroids
        and check_embedding_outlier(memory.embedding, type_centroids, memory.memory_type.value)
    ):
        flags.append("embedding_outlier")

    if len(memory.content) > 500:
        flags.append("unusually_long_content")

    return flags
