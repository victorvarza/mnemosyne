"""Tests for Phase 3 lifecycle: decay, dedup, conflict detection."""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta

from mnemo.core.store import MemoryStore
from mnemo.core.types import Memory
from mnemo.lifecycle import (
    apply_decay,
    decay_score_for,
    find_conflicts,
    find_duplicates,
    run_lifecycle,
)


def _mem(content: str, embedding: list[float], **kwargs) -> Memory:
    return Memory(content=content, embedding=embedding, **kwargs)


def test_decay_score_halves_after_half_life():
    now = datetime.now(UTC)
    m = Memory(content="x", last_accessed=now - timedelta(days=30))
    score = decay_score_for(m, now, half_life_days=30.0)
    assert abs(score - 0.5) < 0.01


def test_apply_decay_updates_scores():
    store = MemoryStore(":memory:", dimensions=3)
    old = _mem("old", [1.0, 0.0, 0.0], last_accessed=datetime.now(UTC) - timedelta(days=60))
    new = _mem("new", [0.0, 1.0, 0.0])
    store.insert(old)
    store.insert(new)

    updated, pruned = apply_decay(store, half_life_days=30.0)
    assert updated == 2
    assert pruned == []
    old_after = store.get(old.id)
    new_after = store.get(new.id)
    assert old_after.decay_score < 0.3
    assert new_after.decay_score > 0.95
    store.close()


def test_apply_decay_prunes_below_threshold():
    store = MemoryStore(":memory:", dimensions=3)
    ancient = _mem("ancient", [1.0, 0.0, 0.0], last_accessed=datetime.now(UTC) - timedelta(days=365))
    store.insert(ancient)
    _, pruned = apply_decay(store, half_life_days=30.0, prune_below=0.05)
    assert pruned == [ancient.id]
    assert store.get(ancient.id) is None
    store.close()


def test_find_duplicates_clusters_near_identical():
    store = MemoryStore(":memory:", dimensions=3)
    a = _mem("User prefers Python", [1.0, 0.0, 0.0])
    b = _mem("User prefers Python.", [0.999, 0.044, 0.0])  # ~0.999 cosine
    c = _mem("User hates Java", [0.0, 1.0, 0.0])
    for m in (a, b, c):
        store.insert(m)
    clusters = find_duplicates(store, threshold=0.92)
    assert len(clusters) == 1
    ids = {m.id for m in clusters[0]}
    assert ids == {a.id, b.id}
    store.close()


def test_dedup_run_removes_copies():
    store = MemoryStore(":memory:", dimensions=3)
    a = _mem("User prefers Python", [1.0, 0.0, 0.0])
    b = _mem("User prefers Python.", [0.999, 0.044, 0.0])
    store.insert(a)
    store.insert(b)
    report = run_lifecycle(store, prune_below=None)
    assert report.duplicates_removed == 1
    assert store.count() == 1
    store.close()


def test_find_conflicts_value_mismatch():
    store = MemoryStore(":memory:", dimensions=3)
    old = _mem(
        "My preferred programming language is Python.",
        [1.0, 0.1, 0.0],
        last_accessed=datetime.now(UTC) - timedelta(days=10),
    )
    new = _mem(
        "My preferred programming language is TypeScript.",
        [0.98, 0.2, 0.0],  # similar subject, different value
    )
    other = _mem("The weather is nice today.", [0.0, 0.0, 1.0])
    for m in (old, new, other):
        store.insert(m)
    conflicts = find_conflicts(store, min_similarity=0.5)
    assert len(conflicts) == 1
    conflict = conflicts[0]
    assert conflict.reason == "value_mismatch"
    assert conflict.keeper.id == new.id  # newer wins
    assert conflict.stale.id == old.id
    store.close()


def test_find_conflicts_negation_mismatch():
    store = MemoryStore(":memory:", dimensions=3)
    a = _mem("User likes shellfish dishes", [1.0, 0.2, 0.0])
    b = _mem("User does not like shellfish dishes", [0.97, 0.24, 0.0])
    store.insert(a)
    store.insert(b)
    conflicts = find_conflicts(store, min_similarity=0.5)
    assert len(conflicts) == 1
    assert conflicts[0].reason == "negation_mismatch"
    store.close()


def test_run_lifecycle_dry_run_does_not_mutate():
    store = MemoryStore(":memory:", dimensions=3)
    ancient = _mem("ancient", [1.0, 0.0, 0.0], last_accessed=datetime.now(UTC) - timedelta(days=365))
    store.insert(ancient)
    report = run_lifecycle(store, dry_run=True)
    assert report.pruned_ids == [ancient.id]
    assert store.get(ancient.id) is not None  # untouched
    store.close()


def test_resolve_conflicts_deletes_stale():
    store = MemoryStore(":memory:", dimensions=3)
    old = _mem(
        "My editor is Emacs.",
        [1.0, 0.1, 0.0],
        last_accessed=datetime.now(UTC) - timedelta(days=10),
    )
    new = _mem("My editor is Neovim.", [0.98, 0.2, 0.0])
    store.insert(old)
    store.insert(new)
    run_lifecycle(store, prune_below=None, resolve_conflicts=True)
    assert store.get(old.id) is None
    assert store.get(new.id) is not None
    store.close()


def test_decay_score_monotonic_in_age():
    now = datetime.now(UTC)
    scores = [
        decay_score_for(Memory(content="x", last_accessed=now - timedelta(days=d)), now, 30.0)
        for d in (0, 10, 30, 90)
    ]
    assert scores == sorted(scores, reverse=True)
    assert all(0.0 < s <= 1.0 for s in scores)
    assert math.isclose(scores[0], 1.0)


# --- Regression coverage for review findings ---------------------------------

from mnemo.lifecycle.manager import _disagreement, _extract_value, subject_overlap


def test_extract_value_strips_trailing_punctuation():
    assert _extract_value("User prefers Python") == "python"
    assert _extract_value("User prefers Python.") == "python"
    assert _extract_value("My editor is Neovim!") == "neovim"
    assert _extract_value("No verb match here at all") is None


def test_punctuation_only_difference_is_not_a_conflict():
    assert _disagreement("User prefers Python", "User prefers Python.") is None


def test_subject_overlap_excludes_negation_and_stopwords():
    # Raw Jaccard here is ~0.43 (negation adds tokens); after stopword/cue
    # removal the pair must register as the same subject.
    overlap = subject_overlap(
        "User likes shellfish dishes", "User does not like shellfish dishes"
    )
    assert overlap >= 0.5


def test_negation_conflict_detected_despite_low_raw_overlap():
    reason = _disagreement(
        "User likes shellfish dishes", "User does not like shellfish dishes"
    )
    assert reason == "negation_mismatch"


def test_disagreement_guard_blocks_unrelated_same_verb():
    # Same verb, different subjects AND different objects -> no conflict.
    assert _disagreement("I use Python daily", "She uses Kafka at scale") is None
    # Different subjects even with a conflicting value shape -> no conflict.
    assert _disagreement("My laptop runs macOS", "The server runs Ubuntu") is None


def test_dataset_fact_templates_detected_as_conflicts():
    """Every fact template in eval/dataset.py must be caught as value_mismatch."""
    templates = [
        "My preferred programming language is {}.",
        "I use {} as my editor.",
        "My machine runs {}.",
        "Our production database is {}.",
        "We deploy on {}.",
        "For tests I always use {}.",
        "I live in {}.",
        "I work on the {} team.",
    ]
    for t in templates:
        reason = _disagreement(t.format("Python"), t.format("TypeScript"))
        assert reason == "value_mismatch", f"missed template: {t}"


def test_conflicting_pair_is_not_merged_and_newest_survives():
    """Near-identical embeddings with different values must not dedup-merge;
    conflict resolution keeps the most recently stated fact."""
    store = MemoryStore(":memory:", dimensions=3)
    old = _mem(
        "My machine runs macOS.",
        [1.0, 0.1, 0.0],
        created_at=datetime.now(UTC) - timedelta(days=30),
        last_accessed=datetime.now(UTC),  # recently *read* but stale
        access_count=10,
    )
    new = _mem("My machine runs Ubuntu.", [0.98, 0.2, 0.0])
    store.insert(old)
    store.insert(new)

    report = run_lifecycle(store, prune_below=None, resolve_conflicts=True)
    assert report.duplicates_removed == 0  # NOT merged
    assert len(report.conflicts) == 1
    assert store.get(new.id) is not None
    assert store.get(old.id) is None  # stale deleted despite higher access_count
    store.close()


def test_dedup_keeper_prefers_recently_stated_over_access_count():
    store = MemoryStore(":memory:", dimensions=3)
    old_popular = _mem(
        "User prefers Python",
        [1.0, 0.0, 0.0],
        created_at=datetime.now(UTC) - timedelta(days=60),
        access_count=50,
    )
    new_copy = _mem("User prefers Python", [1.0, 0.0, 0.0])  # exact duplicate
    store.insert(old_popular)
    store.insert(new_copy)
    clusters = find_duplicates(store)
    assert len(clusters) == 1
    assert clusters[0][0].id == new_copy.id  # newest stated wins
    store.close()
