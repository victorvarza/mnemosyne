"""Memory lifecycle management.

Implements the three lifecycle duties from the project requirements:

- **Decay**: memories lose relevance over time unless they are accessed.
  ``apply_decay`` recomputes ``Memory.decay_score`` as an exponential decay of
  the time since ``last_accessed`` and optionally prunes memories whose score
  falls below a threshold.
- **Deduplication**: ``find_duplicates`` clusters memories whose embeddings are
  nearly identical (cosine similarity above a threshold) so redundant copies
  can be merged or pruned.
- **Stale/conflicting memories**: ``find_conflicts`` pairs near-duplicate
  memories that contradict each other (negation cues) or share a subject but
  carry different values, flagging the older one as stale.

Everything is heuristic and local; the optional LLM-based contradiction check
can be layered on top later without changing these APIs.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime

from mnemo.core.store import MemoryStore
from mnemo.core.types import Memory

# Half-life for the decay curve, in days. After this many days without access,
# a memory's decay_score halves.
DEFAULT_HALF_LIFE_DAYS = 30.0

# Similarity at/above which two memories are considered duplicates.
DEFAULT_DUPLICATE_THRESHOLD = 0.92

# Minimum embedding similarity for two memories to be conflict *candidates*.
# There is no upper bound: "I use Neovim as my editor." and "I use VS Code as
# my editor." can embed above the duplicate threshold while still disagreeing.
# Disagreement is decided by the value/negation checks, not by similarity.
DEFAULT_CONFLICT_MIN_SIMILARITY = 0.55

# Minimum token Jaccard overlap for two memories to be "about the same
# subject". Guards against flagging unrelated "I use X" / "I use Y" sentences
# (different subjects, same verb) as conflicts.
DEFAULT_SUBJECT_OVERLAP = 0.5
# Lower bar for the negation path: negation inherently adds tokens ("does
# not") and changes inflection ("likes" -> "like"), which dilutes raw Jaccard.
DEFAULT_SUBJECT_OVERLAP_NEGATION = 0.3

# Decay score below which a memory is eligible for pruning.
DEFAULT_PRUNE_THRESHOLD = 0.05

# Negation / contradiction cues used by the heuristic conflict detector.
_NEGATION_RE = re.compile(
    r"\b(not|no|never|n't|without|stopped|quit|avoid|hate|dislike|allergic)\b",
    re.IGNORECASE,
)
# "X is/uses/prefers Y" style value extraction for conflict detection. Covers
# first- and third-person forms plus the verb patterns used by the eval
# dataset's fact templates (runs, deploy on, live in, work on/at/for).
_VALUE_RE = re.compile(
    r"\b(?:is|are|was|were|uses?|prefers?|likes?|runs?|deploy(?:s|ed)? on|"
    r"live(?:s)? in|work(?:s)? (?:at|on|for)|switched to|moved to)\b\s+(.+?)\s*$",
    re.IGNORECASE,
)


def decay_score_for(memory: Memory, now: datetime, half_life_days: float) -> float:
    """Exponential decay of a memory based on time since last access."""
    last = memory.last_accessed
    if last.tzinfo is None:
        last = last.replace(tzinfo=UTC)
    age_days = max(0.0, (now - last).total_seconds() / 86400.0)
    return math.exp(-math.log(2) * age_days / half_life_days)


def apply_decay(
    store: MemoryStore,
    *,
    half_life_days: float = DEFAULT_HALF_LIFE_DAYS,
    prune_below: float | None = None,
    now: datetime | None = None,
) -> tuple[int, list[str]]:
    """Recompute decay_score for every memory; optionally prune stale ones.

    Returns (updated_count, pruned_ids).
    """
    now = now or datetime.now(UTC)
    updated = 0
    pruned: list[str] = []
    for memory in store.list_all():
        score = decay_score_for(memory, now, half_life_days)
        store.update_decay_score(memory.id, score)
        updated += 1
        if prune_below is not None and score < prune_below:
            store.delete(memory.id)
            pruned.append(memory.id)
    return updated, pruned


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


def _pairwise_similar(store: MemoryStore):
    """Yield (memory_a, memory_b, cosine_similarity) for all pairs with embeddings."""
    memories = [m for m in store.list_all()]
    embeddings = store.get_embeddings([m.id for m in memories])
    for i in range(len(memories)):
        if memories[i].id not in embeddings:
            continue
        for j in range(i + 1, len(memories)):
            if memories[j].id not in embeddings:
                continue
            sim = _cosine(embeddings[memories[i].id], embeddings[memories[j].id])
            yield memories[i], memories[j], sim


def find_duplicates(
    store: MemoryStore,
    *,
    threshold: float = DEFAULT_DUPLICATE_THRESHOLD,
) -> list[list[Memory]]:
    """Cluster near-duplicate memories (cosine >= threshold).

    Returns a list of clusters (each cluster has >= 2 memories), with the
    cluster members ordered so the "keeper" (most recently stated, then most
    accessed) is first.
    """
    parent: dict[str, str] = {}

    def find(x: str) -> str:
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: str, b: str) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    seen: dict[str, Memory] = {}
    for a, b, sim in _pairwise_similar(store):
        seen[a.id] = a
        seen[b.id] = b
        # Near-identical embeddings that carry *different values* are a
        # conflict, not a duplicate: merging them could keep the stale one.
        if sim >= threshold and _disagreement(a.content, b.content) is None:
            union(a.id, b.id)

    clusters: dict[str, list[Memory]] = {}
    for mid, memory in seen.items():
        clusters.setdefault(find(mid), []).append(memory)

    result = []
    for members in clusters.values():
        if len(members) < 2:
            continue
        # Keep the most recently *stated* memory (created_at), with access
        # count as a tie-breaker — consistent with the conflict policy.
        # Re-reading an old fact must not make it the survivor.
        members.sort(
            key=lambda m: (m.created_at, m.access_count),
            reverse=True,
        )
        result.append(members)
    return result


def deduplicate(
    store: MemoryStore,
    *,
    threshold: float = DEFAULT_DUPLICATE_THRESHOLD,
    dry_run: bool = False,
) -> list[list[Memory]]:
    """Remove near-duplicates, keeping the most accessed/newest of each cluster.

    Returns the clusters that were (or would be, with dry_run) merged.
    """
    clusters = find_duplicates(store, threshold=threshold)
    if not dry_run:
        for members in clusters:
            for duplicate in members[1:]:
                # Keep access history on the survivor before deleting the copy.
                store.touch(members[0].id)
                store.delete(duplicate.id)
    return clusters


def _extract_value(text: str) -> str | None:
    match = _VALUE_RE.search(text.strip())
    if not match:
        return None
    # Strip trailing punctuation so "Python" and "Python." compare equal.
    return match.group(1).strip().lower().rstrip(".!?,;:") or None


def _negation_signature(text: str) -> frozenset[str]:
    return frozenset(m.group(1).lower() for m in _NEGATION_RE.finditer(text))


_WORD_RE = re.compile(r"[a-z0-9']+")


# Tokens ignored when computing subject overlap: pure stopwords plus negation
# cues, so that "likes" vs "does not like" still register as the same subject.
_OVERLAP_STOPWORDS = frozenset(
    {
        "a", "an", "the", "i", "my", "me", "we", "our", "you", "your", "is",
        "are", "was", "were", "do", "does", "did", "not", "no", "never",
        "as", "to", "for", "on", "at", "in",
    }
)


def subject_overlap(a: str, b: str) -> float:
    """Token Jaccard overlap — a cheap "same subject" signal.

    Stopwords and negation cues are excluded so that negated variants of the
    same statement still overlap strongly.
    """
    ta = set(_WORD_RE.findall(a.lower())) - _OVERLAP_STOPWORDS
    tb = set(_WORD_RE.findall(b.lower())) - _OVERLAP_STOPWORDS
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def _common_word_prefix_len(a: str, b: str) -> int:
    wa = _WORD_RE.findall(a.lower())
    wb = _WORD_RE.findall(b.lower())
    n = 0
    for x, y in zip(wa, wb, strict=False):
        if x != y:
            break
        n += 1
    return n


def _disagreement(
    a: str, b: str, *, min_overlap: float = DEFAULT_SUBJECT_OVERLAP
) -> str | None:
    """Return the conflict reason if two texts share a subject but disagree.

    Subject match is established by token overlap, with two relaxations:
    - the negation path uses a lower bar (negation adds tokens and dilutes
      raw Jaccard);
    - a long shared word prefix (>= 2 content words) counts as same subject
      even in short sentences ("We deploy on X" vs "We deploy on Y").
    """
    value_a = _extract_value(a)
    value_b = _extract_value(b)
    neg_a = _negation_signature(a)
    neg_b = _negation_signature(b)
    negation_mismatch = neg_a != neg_b and bool(neg_a or neg_b)

    overlap = subject_overlap(a, b)
    same_subject = (
        overlap >= min_overlap
        or (negation_mismatch and overlap >= DEFAULT_SUBJECT_OVERLAP_NEGATION)
        or _common_word_prefix_len(a, b) >= 2
    )
    if not same_subject:
        return None

    if value_a is not None and value_b is not None and value_a != value_b:
        return "value_mismatch"
    if negation_mismatch:
        return "negation_mismatch"
    return None


@dataclass
class ConflictPair:
    """A pair of memories that appear to be about the same subject but disagree."""

    keeper: Memory  # newer / more trusted memory
    stale: Memory  # older memory, candidate for refresh or deletion
    similarity: float
    reason: str


def find_conflicts(
    store: MemoryStore,
    *,
    min_similarity: float = DEFAULT_CONFLICT_MIN_SIMILARITY,
    min_subject_overlap: float = DEFAULT_SUBJECT_OVERLAP,
) -> list[ConflictPair]:
    """Detect pairs of memories that likely contradict or supersede each other.

    Heuristics:
    - Similar subject: embedding similarity >= ``min_similarity`` AND token
      overlap >= ``min_subject_overlap`` (lower bar on the negation path), AND
      - both match a "subject <verb> value" pattern with different values, OR
      - one negates a term the other asserts (negation-cue mismatch).

    There is intentionally no similarity upper bound: near-identical
    embeddings with different values are conflicts, not duplicates.

    The more recently *stated* memory (``created_at``) is the keeper; the other
    is stale. Access recency is only a tie-breaker, because re-reading an old
    fact does not make it current.
    """
    conflicts: list[ConflictPair] = []
    for a, b, sim in _pairwise_similar(store):
        if sim < min_similarity:
            continue
        reason = _disagreement(a.content, b.content, min_overlap=min_subject_overlap)
        if reason is None:
            continue
        a_key = (a.created_at, a.last_accessed)
        b_key = (b.created_at, b.last_accessed)
        keeper, stale = (a, b) if a_key >= b_key else (b, a)
        conflicts.append(
            ConflictPair(keeper=keeper, stale=stale, similarity=sim, reason=reason)
        )
    return conflicts


@dataclass
class LifecycleReport:
    """Summary of a full lifecycle maintenance pass."""

    decayed: int = 0
    pruned_ids: list[str] = field(default_factory=list)
    duplicate_clusters: list[list[Memory]] = field(default_factory=list)
    conflicts: list[ConflictPair] = field(default_factory=list)
    dry_run: bool = False

    @property
    def duplicates_removed(self) -> int:
        return sum(len(c) - 1 for c in self.duplicate_clusters)


def run_lifecycle(
    store: MemoryStore,
    *,
    half_life_days: float = DEFAULT_HALF_LIFE_DAYS,
    prune_below: float | None = DEFAULT_PRUNE_THRESHOLD,
    dedup_threshold: float = DEFAULT_DUPLICATE_THRESHOLD,
    resolve_conflicts: bool = False,
    dry_run: bool = False,
) -> LifecycleReport:
    """Run one full maintenance pass: decay -> dedup -> conflict handling.

    - Recomputes every memory's decay_score; prunes those below ``prune_below``
      (set to None to disable pruning).
    - Merges near-duplicate memories.
    - Flags conflicting pairs; with ``resolve_conflicts=True`` the stale member
      of each pair is deleted.
    """
    report = LifecycleReport(dry_run=dry_run)

    if dry_run:
        # Compute what would change without mutating the store.
        now = datetime.now(UTC)
        for memory in store.list_all():
            score = decay_score_for(memory, now, half_life_days)
            report.decayed += 1
            if prune_below is not None and score < prune_below:
                report.pruned_ids.append(memory.id)
        report.duplicate_clusters = find_duplicates(store, threshold=dedup_threshold)
        report.conflicts = find_conflicts(store)
        return report

    report.decayed, report.pruned_ids = apply_decay(
        store, half_life_days=half_life_days, prune_below=prune_below
    )
    report.duplicate_clusters = deduplicate(store, threshold=dedup_threshold)
    report.conflicts = find_conflicts(store)
    if resolve_conflicts:
        for conflict in report.conflicts:
            store.delete(conflict.stale.id)
    return report
