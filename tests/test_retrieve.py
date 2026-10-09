from unittest.mock import MagicMock

import pytest

from mnemo.core.store import MemoryStore
from mnemo.core.types import Memory, MemoryQuery, MemoryType
from mnemo.ops.retrieve import _recency_score, retrieve

DIMS = 4


@pytest.fixture
def store():
    s = MemoryStore(dimensions=DIMS)
    yield s
    s.close()


def _mock_embedder(return_embedding: list[float] | None = None):
    embedder = MagicMock()
    embedder.embed.return_value = return_embedding or [1.0, 0.0, 0.0, 0.0]
    return embedder


class TestRetrieve:
    def test_basic_retrieval(self, store: MemoryStore):
        store.insert(Memory(content="python", embedding=[1.0, 0.0, 0.0, 0.0]))
        store.insert(Memory(content="java", embedding=[0.0, 1.0, 0.0, 0.0]))

        embedder = _mock_embedder([1.0, 0.0, 0.0, 0.0])
        query = MemoryQuery(text="python stuff", top_k=1, recency_weight=0.0)
        results = retrieve(store, embedder, query)

        assert len(results) == 1
        assert results[0].memory.content == "python"

    def test_filter_by_type(self, store: MemoryStore):
        store.insert(Memory(content="a", embedding=[1.0, 0.0, 0.0, 0.0], memory_type=MemoryType.SEMANTIC))
        store.insert(Memory(content="b", embedding=[0.9, 0.1, 0.0, 0.0], memory_type=MemoryType.EPISODIC))

        embedder = _mock_embedder([1.0, 0.0, 0.0, 0.0])
        query = MemoryQuery(text="test", top_k=5, memory_type=MemoryType.EPISODIC, recency_weight=0.0)
        results = retrieve(store, embedder, query)

        assert len(results) == 1
        assert results[0].memory.memory_type == MemoryType.EPISODIC

    def test_empty_store(self, store: MemoryStore):
        embedder = _mock_embedder()
        query = MemoryQuery(text="anything")
        results = retrieve(store, embedder, query)
        assert results == []


class TestRecencyScore:
    def test_fresh_memory_scores_high(self):
        m = Memory(content="fresh", embedding=[0.0])
        score = _recency_score(m)
        assert score > 0.9

    def test_score_between_zero_and_one(self):
        m = Memory(content="test", embedding=[0.0])
        score = _recency_score(m)
        assert 0.0 <= score <= 1.0
