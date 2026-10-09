"""Memory lifecycle management: decay, deduplication, conflict detection (Phase 3)."""

from mnemo.lifecycle.manager import (
    ConflictPair,
    LifecycleReport,
    apply_decay,
    decay_score_for,
    deduplicate,
    find_conflicts,
    find_duplicates,
    run_lifecycle,
)

__all__ = [
    "ConflictPair",
    "LifecycleReport",
    "apply_decay",
    "decay_score_for",
    "deduplicate",
    "find_conflicts",
    "find_duplicates",
    "run_lifecycle",
]
