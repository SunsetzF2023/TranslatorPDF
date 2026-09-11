"""On-disk translation cache so re-runs are free."""

from __future__ import annotations

import hashlib
import sqlite3
import threading
from pathlib import Path

CACHE_PATH = Path.home() / ".pdf_bilingual_translator" / "cache.sqlite3"


class TranslationCache:
    def __init__(self, path: Path = CACHE_PATH):
        path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS translations ("
            "hash TEXT PRIMARY KEY, provider TEXT, target TEXT, text TEXT)"
        )
        self._conn.commit()

    @staticmethod
    def _hash(provider: str, target: str, source: str) -> str:
        raw = f"{provider}\x00{target}\x00{source}".encode("utf-8")
        return hashlib.sha256(raw).hexdigest()

    def get(self, provider: str, target: str, source: str) -> str | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT text FROM translations WHERE hash = ?",
                (self._hash(provider, target, source),),
            ).fetchone()
        return row[0] if row else None

    def put(self, provider: str, target: str, source: str, translated: str) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO translations VALUES (?, ?, ?, ?)",
                (self._hash(provider, target, source), provider, target, translated),
            )
            self._conn.commit()

    def clear(self) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM translations")
            self._conn.commit()
