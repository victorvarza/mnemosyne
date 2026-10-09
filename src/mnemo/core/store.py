from __future__ import annotations

import json
import sqlite3
import struct
from datetime import UTC, datetime
from pathlib import Path

import sqlite_vec

from mnemo.core.types import Memory, MemoryType, TrustLevel


def _serialize_f32(vector: list[float]) -> bytes:
    return struct.pack(f"{len(vector)}f", *vector)


def _deserialize_f32(blob: bytes) -> list[float]:
    n = len(blob) // 4
    return list(struct.unpack(f"{n}f", blob))


class MemoryStore:
    def __init__(self, db_path: str | Path = ":memory:", dimensions: int | None = 768):
        self.db_path = str(db_path)
        self.dimensions = dimensions
        self._conn = sqlite3.connect(self.db_path)
        self._conn.enable_load_extension(True)
        sqlite_vec.load(self._conn)
        self._conn.enable_load_extension(False)
        self._init_tables()

    def _init_tables(self):
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS memories (
                id TEXT PRIMARY KEY,
                content TEXT NOT NULL,
                memory_type TEXT NOT NULL DEFAULT 'semantic',
                trust_level TEXT NOT NULL DEFAULT 'unknown',
                source TEXT DEFAULT '',
                created_at TEXT NOT NULL,
                last_accessed TEXT NOT NULL,
                access_count INTEGER DEFAULT 0,
                decay_score REAL DEFAULT 1.0,
                metadata TEXT DEFAULT '{}'
            );

        """)
        if self.dimensions is not None:
            self._conn.execute(f"""
                CREATE VIRTUAL TABLE IF NOT EXISTS memory_embeddings USING vec0(
                    id TEXT PRIMARY KEY,
                    embedding float[{self.dimensions}]
                )
            """)
        self._conn.commit()

    def insert(self, memory: Memory) -> None:
        if memory.embedding is None:
            raise ValueError("Memory must have an embedding before insertion")

        self._conn.execute(
            """INSERT OR REPLACE INTO memories
               (id, content, memory_type, trust_level, source, created_at, last_accessed,
                access_count, decay_score, metadata)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                memory.id,
                memory.content,
                memory.memory_type.value,
                memory.trust_level.value,
                memory.source,
                memory.created_at.isoformat(),
                memory.last_accessed.isoformat(),
                memory.access_count,
                memory.decay_score,
                json.dumps(memory.metadata),
            ),
        )
        self._conn.execute(
            "INSERT OR REPLACE INTO memory_embeddings (id, embedding) VALUES (?, ?)",
            (memory.id, _serialize_f32(memory.embedding)),
        )
        self._conn.commit()

    def search(self, query_embedding: list[float], top_k: int = 5) -> list[tuple[Memory, float]]:
        rows = self._conn.execute(
            """
            SELECT m.id, m.content, m.memory_type, m.trust_level, m.source,
                   m.created_at, m.last_accessed, m.access_count, m.decay_score, m.metadata,
                   v.distance
            FROM memory_embeddings v
            INNER JOIN memories m ON m.id = v.id
            WHERE v.embedding MATCH ? AND k = ?
            ORDER BY v.distance
            """,
            (_serialize_f32(query_embedding), top_k),
        ).fetchall()

        results = []
        for row in rows:
            memory = Memory(
                id=row[0],
                content=row[1],
                memory_type=MemoryType(row[2]),
                trust_level=TrustLevel(row[3]),
                source=row[4],
                created_at=datetime.fromisoformat(row[5]),
                last_accessed=datetime.fromisoformat(row[6]),
                access_count=row[7],
                decay_score=row[8],
                metadata=json.loads(row[9]),
            )
            distance = row[10]
            similarity = 1.0 - distance
            results.append((memory, similarity))

        return results

    def get(self, memory_id: str) -> Memory | None:
        row = self._conn.execute(
            "SELECT id, content, memory_type, trust_level, source, created_at, last_accessed, "
            "access_count, decay_score, metadata FROM memories WHERE id = ?",
            (memory_id,),
        ).fetchone()
        if row is None:
            return None
        return Memory(
            id=row[0],
            content=row[1],
            memory_type=MemoryType(row[2]),
            trust_level=TrustLevel(row[3]),
            source=row[4],
            created_at=datetime.fromisoformat(row[5]),
            last_accessed=datetime.fromisoformat(row[6]),
            access_count=row[7],
            decay_score=row[8],
            metadata=json.loads(row[9]),
        )

    def delete(self, memory_id: str) -> bool:
        cursor = self._conn.execute("DELETE FROM memories WHERE id = ?", (memory_id,))
        self._conn.execute("DELETE FROM memory_embeddings WHERE id = ?", (memory_id,))
        self._conn.commit()
        return cursor.rowcount > 0

    def list_all(self, memory_type: MemoryType | None = None) -> list[Memory]:
        query = "SELECT id, content, memory_type, trust_level, source, created_at, last_accessed, access_count, decay_score, metadata FROM memories"
        params: list = []
        if memory_type:
            query += " WHERE memory_type = ?"
            params.append(memory_type.value)
        query += " ORDER BY created_at DESC"

        rows = self._conn.execute(query, params).fetchall()
        return [
            Memory(
                id=row[0],
                content=row[1],
                memory_type=MemoryType(row[2]),
                trust_level=TrustLevel(row[3]),
                source=row[4],
                created_at=datetime.fromisoformat(row[5]),
                last_accessed=datetime.fromisoformat(row[6]),
                access_count=row[7],
                decay_score=row[8],
                metadata=json.loads(row[9]),
            )
            for row in rows
        ]

    def update_decay_score(self, memory_id: str, score: float) -> None:
        self._conn.execute(
            "UPDATE memories SET decay_score = ? WHERE id = ?",
            (score, memory_id),
        )
        self._conn.commit()

    def get_embeddings(self, memory_ids: list[str]) -> dict[str, list[float]]:
        """Return {id: embedding} for the given ids that have embeddings."""
        if not memory_ids:
            return {}
        placeholders = ",".join("?" for _ in memory_ids)
        rows = self._conn.execute(
            f"SELECT id, embedding FROM memory_embeddings WHERE id IN ({placeholders})",
            memory_ids,
        ).fetchall()
        return {row[0]: _deserialize_f32(row[1]) for row in rows}

    def touch(self, memory_id: str) -> None:
        now = datetime.now(UTC).isoformat()
        self._conn.execute(
            "UPDATE memories SET last_accessed = ?, access_count = access_count + 1 WHERE id = ?",
            (now, memory_id),
        )
        self._conn.commit()

    def count(self) -> int:
        return self._conn.execute("SELECT COUNT(*) FROM memories").fetchone()[0]

    def close(self):
        self._conn.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
