from unittest.mock import MagicMock

import pytest

from mnemo.core.profiles import ProfileStore
from mnemo.core.types import MemoryQuery, ProfileEntry, TargetProfile, TrustLevel
from mnemo.ops.inject import build_personalized_prompt, format_profile_block
from mnemo.ops.retrieve import retrieve_profile

DIMS = 4


@pytest.fixture
def pstore():
    s = ProfileStore(dimensions=DIMS)
    yield s
    s.close()


def _mock_embedder(return_embedding: list[float] | None = None):
    embedder = MagicMock()
    embedder.embed.return_value = return_embedding or [1.0, 0.0, 0.0, 0.0]
    return embedder


def _entry(profile_id: str, content: str, embedding: list[float], **kwargs) -> ProfileEntry:
    return ProfileEntry(
        profile_id=profile_id, content=content, embedding=embedding, **kwargs
    )


class TestProfileStore:
    def test_create_and_get_profile(self, pstore: ProfileStore):
        pstore.create_profile(TargetProfile(id="app", target="https://app.example.com"))
        got = pstore.get_profile("app")
        assert got is not None
        assert got.target == "https://app.example.com"

    def test_add_and_count_entries(self, pstore: ProfileStore):
        pstore.create_profile(TargetProfile(id="app", target="t"))
        pstore.add_entry(_entry("app", "auth is JWT", [1.0, 0.0, 0.0, 0.0]))
        pstore.add_entry(_entry("app", "uses GraphQL", [0.0, 1.0, 0.0, 0.0]))
        assert pstore.entry_count("app") == 2

    def test_entry_requires_embedding(self, pstore: ProfileStore):
        pstore.create_profile(TargetProfile(id="app", target="t"))
        with pytest.raises(ValueError):
            pstore.add_entry(ProfileEntry(profile_id="app", content="x"))

    def test_search_scoped_to_profile(self, pstore: ProfileStore):
        pstore.create_profile(TargetProfile(id="a", target="t1"))
        pstore.create_profile(TargetProfile(id="b", target="t2"))
        pstore.add_entry(_entry("a", "a-entry", [1.0, 0.0, 0.0, 0.0]))
        pstore.add_entry(_entry("b", "b-entry", [1.0, 0.0, 0.0, 0.0]))

        results = pstore.search("a", [1.0, 0.0, 0.0, 0.0], top_k=5)
        assert [e.content for e, _ in results] == ["a-entry"]

    def test_delete_profile_removes_entries(self, pstore: ProfileStore):
        pstore.create_profile(TargetProfile(id="app", target="t"))
        pstore.add_entry(_entry("app", "x", [1.0, 0.0, 0.0, 0.0]))
        removed = pstore.delete_profile("app")
        assert removed == 1
        assert pstore.get_profile("app") is None
        assert pstore.entry_count() == 0


class TestRetrieveProfile:
    def test_retrieves_relevant_entry(self, pstore: ProfileStore):
        pstore.create_profile(TargetProfile(id="app", target="t"))
        pstore.add_entry(_entry("app", "auth is JWT", [1.0, 0.0, 0.0, 0.0]))
        pstore.add_entry(_entry("app", "uses GraphQL", [0.0, 1.0, 0.0, 0.0]))

        embedder = _mock_embedder([1.0, 0.0, 0.0, 0.0])
        query = MemoryQuery(text="how does login work", top_k=1, recency_weight=0.0)
        results = retrieve_profile(pstore, embedder, "app", query)

        assert len(results) == 1
        assert results[0].memory.content == "auth is JWT"

    def test_empty_profile(self, pstore: ProfileStore):
        pstore.create_profile(TargetProfile(id="app", target="t"))
        embedder = _mock_embedder()
        results = retrieve_profile(pstore, embedder, "app", MemoryQuery(text="x"))
        assert results == []


class TestProfileInjection:
    def test_format_profile_block(self, pstore: ProfileStore):
        pstore.create_profile(TargetProfile(id="app", target="t"))
        pstore.add_entry(
            _entry("app", "auth is JWT", [1.0, 0.0, 0.0, 0.0], trust_level=TrustLevel.USER_STATED)
        )
        embedder = _mock_embedder([1.0, 0.0, 0.0, 0.0])
        results = retrieve_profile(
            pstore, embedder, "app", MemoryQuery(text="auth", top_k=1, recency_weight=0.0)
        )
        block = format_profile_block(results, target="app.example.com")
        assert "Target Profile Context" in block
        assert "app.example.com" in block
        assert "auth is JWT" in block

    def test_build_personalized_prompt_combines(self, pstore: ProfileStore):
        pstore.create_profile(TargetProfile(id="app", target="t"))
        pstore.add_entry(_entry("app", "auth is JWT", [1.0, 0.0, 0.0, 0.0]))
        embedder = _mock_embedder([1.0, 0.0, 0.0, 0.0])
        results = retrieve_profile(
            pstore, embedder, "app", MemoryQuery(text="test login", top_k=1, recency_weight=0.0)
        )
        combined = build_personalized_prompt("test login", results, target="t")
        assert "auth is JWT" in combined
        assert "Task: test login" in combined

    def test_build_personalized_prompt_no_results_is_plain(self):
        assert build_personalized_prompt("do x", []) == "do x"
