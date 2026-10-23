from __future__ import annotations

import math
from datetime import UTC, datetime

from mnemo.core.embeddings import EmbeddingModel
from mnemo.core.profiles import ProfileStore
from mnemo.core.store import MemoryStore
from mnemo.core.types import Memory, MemoryQuery, MemoryResult
from mnemo.eval.usefulness import UsefulnessModel


def _recency_score(memory: Memory, half_life_days: float = 7.0) -> float:
    age = (datetime.now(UTC) - memory.last_accessed).total_seconds()
    age_days = age / 86400.0
    return math.exp(-0.693 * age_days / half_life_days)


def retrieve(
    store: MemoryStore,
    embedder: EmbeddingModel,
    query: MemoryQuery,
    usefulness_model: UsefulnessModel | None = None,
    usefulness_threshold: float = 0.5,
    touch: bool = True,
) -> list[MemoryResult]:
    """Retrieve memories by similarity+recency, optionally re-ranked/filtered by
    the learned usefulness model.

    When ``usefulness_model`` is provided, each candidate is scored with the
    model's P(helpful | query, memory); candidates below
    ``usefulness_threshold`` are dropped and the remainder re-ranked by the
    model's probability (blended with the similarity/recency score).

    ``touch=False`` leaves ``last_accessed``/``access_count`` unchanged, so
    evaluation queries don't reset the recency features of later queries.
    """
    query_embedding = embedder.embed(query.text)

    raw_results = store.search(query_embedding, top_k=query.top_k * 3)

    scored: list[tuple[Memory, float]] = []
    for memory, similarity in raw_results:
        if query.memory_type and memory.memory_type != query.memory_type:
            continue
        if query.trust_level and memory.trust_level != query.trust_level:
            continue

        recency = _recency_score(memory)
        combined = (1.0 - query.recency_weight) * similarity + query.recency_weight * recency

        if usefulness_model is not None:
            p_helpful = usefulness_model.score(
                similarity=similarity, recency=recency, memory=memory
            )
            if p_helpful < usefulness_threshold:
                continue
            # Blend the model's probability with the retrieval score.
            combined = 0.5 * combined + 0.5 * p_helpful

        if combined >= query.min_score:
            scored.append((memory, combined))

    scored.sort(key=lambda x: x[1], reverse=True)
    top = scored[: query.top_k]

    results = []
    for rank, (memory, score) in enumerate(top):
        if touch:
            store.touch(memory.id)
        results.append(MemoryResult(memory=memory, score=score, retrieval_rank=rank))

    return results


def retrieve_profile(
    profile_store: ProfileStore,
    embedder: EmbeddingModel,
    profile_id: str,
    query: MemoryQuery,
    usefulness_model: UsefulnessModel | None = None,
    usefulness_threshold: float = 0.5,
    touch: bool = True,
) -> list[MemoryResult]:
    """Retrieve the entries of a target profile relevant to ``query``.

    This is the ``R(q, Pu, k)`` step of the LaMP retrieval-augmentation design,
    scoped to a single user-provided target profile. It mirrors ``retrieve()``:
    similarity + recency scoring with optional re-ranking/filtering by the
    learned usefulness model. Entries are returned as ``MemoryResult`` (their
    ``as_memory()`` view) so the same prompt-injection formatting applies.
    """
    query_embedding = embedder.embed(query.text)

    raw_results = profile_store.search(
        profile_id, query_embedding, top_k=query.top_k * 3
    )

    scored: list[tuple[Memory, float]] = []
    for entry, similarity in raw_results:
        memory = entry.as_memory()
        if query.trust_level and memory.trust_level != query.trust_level:
            continue

        recency = _recency_score(memory)
        combined = (1.0 - query.recency_weight) * similarity + query.recency_weight * recency

        if usefulness_model is not None:
            p_helpful = usefulness_model.score(
                similarity=similarity, recency=recency, memory=memory
            )
            if p_helpful < usefulness_threshold:
                continue
            combined = 0.5 * combined + 0.5 * p_helpful

        if combined >= query.min_score:
            scored.append((memory, combined))

    scored.sort(key=lambda x: x[1], reverse=True)
    top = scored[: query.top_k]

    results = []
    for rank, (memory, score) in enumerate(top):
        if touch:
            profile_store.touch(memory.id)
        results.append(MemoryResult(memory=memory, score=score, retrieval_rank=rank))

    return results

