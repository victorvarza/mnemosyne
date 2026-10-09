from __future__ import annotations

from mnemo.core.types import TrustLevel

SOURCE_TRUST_MAP: dict[str, TrustLevel] = {
    "cli": TrustLevel.USER_STATED,
    "user": TrustLevel.USER_STATED,
    "chat": TrustLevel.USER_STATED,
    "agent": TrustLevel.AGENT_INFERRED,
    "assistant": TrustLevel.AGENT_INFERRED,
    "extraction": TrustLevel.AGENT_INFERRED,
    "document": TrustLevel.EXTERNAL_DOCUMENT,
    "file": TrustLevel.EXTERNAL_DOCUMENT,
    "url": TrustLevel.EXTERNAL_DOCUMENT,
    "web": TrustLevel.EXTERNAL_DOCUMENT,
}

TRUST_BOOST: dict[TrustLevel, float] = {
    TrustLevel.USER_STATED: 1.0,
    TrustLevel.AGENT_INFERRED: 0.85,
    TrustLevel.EXTERNAL_DOCUMENT: 0.7,
    TrustLevel.UNKNOWN: 0.5,
}


def assign_trust(content: str, source: str) -> TrustLevel:
    source_lower = source.lower().strip()
    for key, level in SOURCE_TRUST_MAP.items():
        if key in source_lower:
            return level
    return TrustLevel.UNKNOWN


def boost_by_trust(score: float, trust_level: TrustLevel) -> float:
    return score * TRUST_BOOST[trust_level]
