import pytest

from mnemo.core.store import MemoryStore
from mnemo.core.types import Memory, MemoryType

DIMS = 4


def _make_memory(content: str, embedding: list[float] | None = None, **kwargs) -> Memory:
    return Memory(
        content=content,
        embedding=embedding or [0.1, 0.2, 0.3, 0.4],
        **kwargs,
    )


@pytest.fixture
def store():
    s = MemoryStore(dimensions=DIMS)
    yield s
    s.close()


class TestInsertAndGet:
    def test_insert_and_count(self, store: MemoryStore):
        store.insert(_make_memory("fact one"))
        store.insert(_make_memory("fact two"))
        assert store.count() == 2

    def test_get_returns_memory(self, store: MemoryStore):
        m = _make_memory("test content", memory_type=MemoryType.EPISODIC)
        store.insert(m)
        got = store.get(m.id)
        assert got is not None
        assert got.content == "test content"
        assert got.memory_type == MemoryType.EPISODIC

    def test_get_missing_returns_none(self, store: MemoryStore):
        assert store.get("nonexistent") is None

    def test_insert_requires_embedding(self, store: MemoryStore):
        m = Memory(content="no embedding")
        with pytest.raises(ValueError, match="embedding"):
            store.insert(m)


class TestSearch:
    def test_search_returns_results(self, store: MemoryStore):
        store.insert(_make_memory("python is great", [1.0, 0.0, 0.0, 0.0]))
        store.insert(_make_memory("java is okay", [0.0, 1.0, 0.0, 0.0]))
        store.insert(_make_memory("rust is fast", [0.0, 0.0, 1.0, 0.0]))

        results = store.search([1.0, 0.0, 0.0, 0.0], top_k=2)
        assert len(results) == 2
        assert results[0][0].content == "python is great"

    def test_search_empty_store(self, store: MemoryStore):
        results = store.search([1.0, 0.0, 0.0, 0.0], top_k=5)
        assert results == []


class TestDelete:
    def test_delete_existing(self, store: MemoryStore):
        m = _make_memory("to delete")
        store.insert(m)
        assert store.delete(m.id) is True
        assert store.count() == 0
        assert store.get(m.id) is None

    def test_delete_nonexistent(self, store: MemoryStore):
        assert store.delete("nonexistent") is False


class TestListAll:
    def test_list_all(self, store: MemoryStore):
        store.insert(_make_memory("one", memory_type=MemoryType.SEMANTIC))
        store.insert(_make_memory("two", memory_type=MemoryType.EPISODIC))
        store.insert(_make_memory("three", memory_type=MemoryType.PROCEDURAL))
        assert len(store.list_all()) == 3

    def test_list_filtered_by_type(self, store: MemoryStore):
        store.insert(_make_memory("one", memory_type=MemoryType.SEMANTIC))
        store.insert(_make_memory("two", memory_type=MemoryType.EPISODIC))
        assert len(store.list_all(memory_type=MemoryType.SEMANTIC)) == 1


class TestTouch:
    def test_touch_increments_access_count(self, store: MemoryStore):
        m = _make_memory("touchable")
        store.insert(m)
        store.touch(m.id)
        store.touch(m.id)
        got = store.get(m.id)
        assert got.access_count == 2
