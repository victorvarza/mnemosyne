from __future__ import annotations

from mnemo.core.types import MemoryResult


def format_memories_block(results: list[MemoryResult]) -> str:
    if not results:
        return ""

    lines = ["## Remembered Context", ""]
    for r in results:
        m = r.memory
        tag = f"[{m.memory_type.value}|{m.trust_level.value}]"
        lines.append(f"- {tag} {m.content}")

    return "\n".join(lines)
