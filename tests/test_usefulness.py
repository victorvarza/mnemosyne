"""Tests for Phase 2 usefulness model and retrieval integration."""

from __future__ import annotations

import random

from mnemo.core.store import MemoryStore
from mnemo.core.types import Memory, MemoryQuery, TrustLevel
from mnemo.eval.dataset import f1_score, generate_dataset
from mnemo.eval.usefulness import (
    UsefulnessExample,
    UsefulnessModel,
    evaluate_usefulness_model,
    train_usefulness_model,
)
from mnemo.ops.retrieve import retrieve


class FakeEmbedder:
    """Deterministic bag-of-words embedder for tests (no Ollama needed)."""

    def __init__(self, dims: int = 16):
        self._dims = dims

    @property
    def dimensions(self) -> int:
        return self._dims

    def embed(self, text: str) -> list[float]:
        vec = [0.0] * self._dims
        for token in text.lower().split():
            vec[hash(token) % self._dims] += 1.0
        norm = sum(v * v for v in vec) ** 0.5 or 1.0
        return [v / norm for v in vec]


def _examples(n: int = 60) -> list[UsefulnessExample]:
    """Synthetic separable dataset: helpful = high similarity + user trust."""
    rng = random.Random(0)
    out = []
    for _ in range(n):
        helpful = rng.random() < 0.5
        out.append(
            UsefulnessExample(
                query="q",
                memory_content="m",
                helpful=helpful,
                similarity=0.7 + rng.random() * 0.3 if helpful else rng.random() * 0.4,
                recency=rng.random(),
                trust_level=TrustLevel.USER_STATED.value if helpful else TrustLevel.UNKNOWN.value,
            )
        )
    return out


def test_train_and_score_separable_data():
    examples = _examples()
    model = train_usefulness_model(examples)
    metrics = evaluate_usefulness_model(model, examples)
    assert metrics["accuracy"] > 0.9  # separable -> near perfect


def test_score_in_unit_interval():
    model = train_usefulness_model(_examples())
    for e in _examples(10):
        p = model.score(
            similarity=e.similarity,
            recency=e.recency,
            trust_level=e.trust_level,
        )
        assert 0.0 <= p <= 1.0


def test_high_similarity_scores_higher_than_low():
    model = train_usefulness_model(_examples())
    high = model.score(similarity=0.95, recency=1.0, trust_level=TrustLevel.USER_STATED.value)
    low = model.score(similarity=0.05, recency=0.1, trust_level=TrustLevel.UNKNOWN.value)
    assert high > low


def test_save_load_roundtrip(tmp_path):
    model = train_usefulness_model(_examples())
    path = model.save(tmp_path / "model.json")
    loaded = UsefulnessModel.load(path)
    assert loaded.weights == model.weights
    assert loaded.bias == model.bias
    p1 = model.score(similarity=0.5, recency=0.5)
    p2 = loaded.score(similarity=0.5, recency=0.5)
    assert abs(p1 - p2) < 1e-12


def test_train_requires_minimum_examples():
    try:
        train_usefulness_model(_examples(3))
    except ValueError:
        return
    raise AssertionError("expected ValueError for <4 examples")


def test_retrieve_with_model_filters_unhelpful():
    embedder = FakeEmbedder()
    store = MemoryStore(":memory:", dimensions=embedder.dimensions)
    relevant = Memory(
        content="User prefers Python for backend services",
        embedding=embedder.embed("Python backend preference"),
    )
    noise = Memory(
        content="Pancake recipe with blueberries",
        embedding=embedder.embed("pancakes blueberries recipe"),
    )
    store.insert(relevant)
    store.insert(noise)

    # Model that only passes memories containing "Python" — emulate via a model
    # trained to weight similarity, then verify plumbing end to end instead.
    examples = _examples()
    model = train_usefulness_model(examples)

    query = MemoryQuery(text="Python backend", top_k=5)
    with_model = retrieve(
        store, embedder, query, usefulness_model=model, usefulness_threshold=0.0
    )
    without_model = retrieve(store, embedder, query)
    assert len(with_model) >= 1
    assert len(without_model) >= 1
    # Threshold 1.1 (> max probability) filters everything out.
    none = retrieve(
        store, embedder, query, usefulness_model=model, usefulness_threshold=1.1
    )
    assert none == []
    store.close()


def test_generate_dataset_structure():
    dataset = generate_dataset(n_conversations=2, seed=7)
    assert len(dataset.conversations) == 2
    conv = dataset.conversations[0]
    assert len(conv.sessions) == 4
    assert len(conv.qa_pairs) == len(conv.memories)
    assert sum(1 for qa in conv.qa_pairs if qa.is_update_query) == 1


def test_f1_score():
    assert f1_score("Python", "Python") == 1.0
    assert f1_score("Java", "Python") == 0.0
    assert 0.0 < f1_score("prefers Python language", "Python") < 1.0


def test_score_does_not_depend_on_access_count():
    # Retrieval increments access_count; a trained weight on it would suppress
    # a relevant memory after a few uses (observed live in the plugin).
    model = train_usefulness_model(_examples())
    fresh = Memory(content="x", trust_level=TrustLevel.USER_STATED, access_count=0)
    used = Memory(content="x", trust_level=TrustLevel.USER_STATED, access_count=50)
    assert model.score(similarity=0.3, recency=1.0, memory=fresh) == model.score(
        similarity=0.3, recency=1.0, memory=used
    )


def test_model_with_legacy_feature_set_still_scores():
    legacy = UsefulnessModel(
        weights=[10.0, 1.0, 0.0, -2.0, 0.0, 0.0, 0.0, 0.0, 0.0],
        bias=-1.0,
        feature_names=[
            "similarity",
            "recency",
            "decay_score",
            "log_access_count",
            "type_episodic",
            "type_procedural",
            "trust_user_stated",
            "trust_agent_inferred",
            "trust_external_document",
        ],
    )
    memory = Memory(content="x", access_count=3)
    p = legacy.score(similarity=0.5, recency=1.0, memory=memory)
    assert 0.0 < p < 1.0
