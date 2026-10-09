"""Train/serve parity for the Phase 4 benchmark (review: constant features).

The usefulness model is trained on recency/trust features, so the benchmark
must insert memories whose features vary the way they do in training: the
superseded fact is old, the update is fresh, and evaluation queries must not
refresh ``last_accessed`` between questions.
"""

from __future__ import annotations

from datetime import UTC, datetime

from mnemo.core.store import MemoryStore
from mnemo.core.types import MemoryQuery
from mnemo.eval.benchmark import SESSION1_AGE_DAYS, build_conversation_memories
from mnemo.eval.dataset import generate_conversation
from mnemo.ops.retrieve import _recency_score, retrieve
from tests.test_usefulness import FakeEmbedder


def test_stale_and_updated_facts_have_different_recency():
    conv = generate_conversation(seed=42)
    now = datetime.now(UTC)
    memories = build_conversation_memories(conv, FakeEmbedder(), now=now)
    by_content = {m.content: m for m in memories}

    stale = next(m for m in memories if conv.stale_value in m.content and m.content in conv.memories)
    updated = by_content[conv.updated_memory]

    assert (now - stale.created_at).days == SESSION1_AGE_DAYS
    assert updated.created_at == now
    assert _recency_score(updated) > 0.99
    assert _recency_score(stale) < 0.05


def test_retrieve_without_touch_preserves_recency_features():
    embedder = FakeEmbedder()
    conv = generate_conversation(seed=42)
    store = MemoryStore(":memory:", dimensions=embedder.dimensions)
    memories = build_conversation_memories(conv, embedder)
    for m in memories:
        store.insert(m)

    before = {m.id: (m.last_accessed, m.access_count) for m in store.list_all()}
    for qa in conv.qa_pairs:
        retrieve(store, embedder, MemoryQuery(text=qa.question, top_k=5), touch=False)
    after = {m.id: (m.last_accessed, m.access_count) for m in store.list_all()}

    assert before == after
    store.close()
