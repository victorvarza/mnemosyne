from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import sqlite_vec

from mnemo.core.store import _deserialize_f32, _serialize_f32
from mnemo.core.types import ProfileEntry, TargetProfile, TrustLevel


class ProfileStore:
    """Dedicated storage for user-provided target-system profiles.

    Profiles and their entries live in their own tables, separate from the
    global memory store, so a profile is an explicit, user-owned container
    bound to a target. Entry embeddings use the same ``sqlite-vec`` virtual
    table mechanism as memories, which lets profile retrieval reuse the shared
    similarity/recency/usefulness pipeline.
    """

    def __init__(self, db_path: str | Path = ":memory:", dimensions: int | None = 768):
        self.db_path = str(db_path)
        self.dimensions = dimensions
        self._conn = sqlite3.connect(self.db_path)
        self._conn.enable_load_extension(True)
        sqlite_vec.load(self._conn)
        self._conn.enable_load_extension(False)
        self._init_tables()

    def _init_tables(self) -> None:
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS profiles (
                id TEXT PRIMARY KEY,
                target TEXT NOT NULL,
                authorization TEXT DEFAULT '',
                description TEXT DEFAULT '',
                created_at TEXT NOT NULL,
                metadata TEXT DEFAULT '{}'
            );

            CREATE TABLE IF NOT EXISTS profile_entries (
                id TEXT PRIMARY KEY,
                profile_id TEXT NOT NULL,
                content TEXT NOT NULL,
                trust_level TEXT NOT NULL DEFAULT 'external_document',
                source TEXT DEFAULT '',
                created_at TEXT NOT NULL,
                last_accessed TEXT NOT NULL,
                access_count INTEGER DEFAULT 0,
                metadata TEXT DEFAULT '{}',
                FOREIGN KEY (profile_id) REFERENCES profiles(id)
            );
        """)
        if self.dimensions is not None:
            self._conn.execute(f"""
                CREATE VIRTUAL TABLE IF NOT EXISTS profile_entry_embeddings USING vec0(
                    id TEXT PRIMARY KEY,
                    embedding float[{self.dimensions}]
                )
            """)
        self._conn.commit()

    # --- Profiles ----------------------------------------------------------

    def create_profile(self, profile: TargetProfile) -> None:
        self._conn.execute(
            """INSERT INTO profiles
               (id, target, authorization, description, created_at, metadata)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                profile.id,
                profile.target,
                profile.authorization,
                profile.description,
                profile.created_at.isoformat(),
                json.dumps(profile.metadata),
            ),
        )
        self._conn.commit()

    def get_profile(self, profile_id: str) -> TargetProfile | None:
        row = self._conn.execute(
            "SELECT id, target, authorization, description, created_at, metadata "
            "FROM profiles WHERE id = ?",
            (profile_id,),
        ).fetchone()
        if row is None:
            return None
        return TargetProfile(
            id=row[0],
            target=row[1],
            authorization=row[2],
            description=row[3],
            created_at=datetime.fromisoformat(row[4]),
            metadata=json.loads(row[5]),
        )

    def list_profiles(self) -> list[TargetProfile]:
        rows = self._conn.execute(
            "SELECT id, target, authorization, description, created_at, metadata "
            "FROM profiles ORDER BY created_at DESC"
        ).fetchall()
        return [
            TargetProfile(
                id=row[0],
                target=row[1],
                authorization=row[2],
                description=row[3],
                created_at=datetime.fromisoformat(row[4]),
                metadata=json.loads(row[5]),
            )
            for row in rows
        ]

    def delete_profile(self, profile_id: str) -> int:
        entries = self.list_entries(profile_id)
        for entry in entries:
            self._conn.execute(
                "DELETE FROM profile_entry_embeddings WHERE id = ?", (entry.id,)
            )
        self._conn.execute(
            "DELETE FROM profile_entries WHERE profile_id = ?", (profile_id,)
        )
        self._conn.execute("DELETE FROM profiles WHERE id = ?", (profile_id,))
        self._conn.commit()
        return len(entries)

    # --- Entries -----------------------------------------------------------

    def add_entry(self, entry: ProfileEntry) -> None:
        if entry.embedding is None:
            raise ValueError("ProfileEntry must have an embedding before insertion")
        self._conn.execute(
            """INSERT OR REPLACE INTO profile_entries
               (id, profile_id, content, trust_level, source, created_at,
                last_accessed, access_count, metadata)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                entry.id,
                entry.profile_id,
                entry.content,
                entry.trust_level.value,
                entry.source,
                entry.created_at.isoformat(),
                entry.last_accessed.isoformat(),
                entry.access_count,
                json.dumps(entry.metadata),
            ),
        )
        self._conn.execute(
            "INSERT OR REPLACE INTO profile_entry_embeddings (id, embedding) VALUES (?, ?)",
            (entry.id, _serialize_f32(entry.embedding)),
        )
        self._conn.commit()

    def _row_to_entry(self, row: tuple) -> ProfileEntry:
        return ProfileEntry(
            id=row[0],
            profile_id=row[1],
            content=row[2],
            trust_level=TrustLevel(row[3]),
            source=row[4],
            created_at=datetime.fromisoformat(row[5]),
            last_accessed=datetime.fromisoformat(row[6]),
            access_count=row[7],
            metadata=json.loads(row[8]),
        )

    def list_entries(self, profile_id: str) -> list[ProfileEntry]:
        rows = self._conn.execute(
            "SELECT id, profile_id, content, trust_level, source, created_at, "
            "last_accessed, access_count, metadata "
            "FROM profile_entries WHERE profile_id = ? ORDER BY created_at DESC",
            (profile_id,),
        ).fetchall()
        return [self._row_to_entry(row) for row in rows]

    def search(
        self, profile_id: str, query_embedding: list[float], top_k: int = 5
    ) -> list[tuple[ProfileEntry, float]]:
        """Return the ``top_k`` entries of a profile nearest to the query
        embedding, as ``(entry, similarity)`` pairs."""
        rows = self._conn.execute(
            """
            SELECT e.id, e.profile_id, e.content, e.trust_level, e.source,
                   e.created_at, e.last_accessed, e.access_count, e.metadata,
                   v.distance
            FROM profile_entry_embeddings v
            INNER JOIN profile_entries e ON e.id = v.id
            WHERE v.embedding MATCH ? AND k = ? AND e.profile_id = ?
            ORDER BY v.distance
            """,
            (_serialize_f32(query_embedding), top_k, profile_id),
        ).fetchall()
        results: list[tuple[ProfileEntry, float]] = []
        for row in rows:
            entry = self._row_to_entry(row[:9])
            similarity = 1.0 - row[9]
            results.append((entry, similarity))
        return results

    def get_embeddings(self, entry_ids: list[str]) -> dict[str, list[float]]:
        if not entry_ids:
            return {}
        placeholders = ",".join("?" for _ in entry_ids)
        rows = self._conn.execute(
            f"SELECT id, embedding FROM profile_entry_embeddings WHERE id IN ({placeholders})",
            entry_ids,
        ).fetchall()
        return {row[0]: _deserialize_f32(row[1]) for row in rows}

    def touch(self, entry_id: str) -> None:
        now = datetime.now(UTC).isoformat()
        self._conn.execute(
            "UPDATE profile_entries SET last_accessed = ?, access_count = access_count + 1 "
            "WHERE id = ?",
            (now, entry_id),
        )
        self._conn.commit()

    def entry_count(self, profile_id: str | None = None) -> int:
        if profile_id is None:
            return self._conn.execute(
                "SELECT COUNT(*) FROM profile_entries"
            ).fetchone()[0]
        return self._conn.execute(
            "SELECT COUNT(*) FROM profile_entries WHERE profile_id = ?",
            (profile_id,),
        ).fetchone()[0]

    def close(self) -> None:
        self._conn.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
