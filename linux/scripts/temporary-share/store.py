"""SQLite-хранилище заявок temporary-share без plaintext-токенов."""

from __future__ import annotations

from datetime import datetime, timezone
from functools import wraps
import hmac
import json
import secrets
import sqlite3
from pathlib import Path
import threading
from typing import Callable, TypeVar

from core import ShareKind, ShareRecord, ShareState, clamp_ttl, generate_token, hash_token, new_expiry

T = TypeVar("T")


def locked(method: Callable[..., T]) -> Callable[..., T]:
    @wraps(method)
    def wrapper(self: "ShareStore", *args, **kwargs):
        with self._lock:
            return method(self, *args, **kwargs)
    return wrapper


class ShareStore:
    """Атомарное хранилище заявок для локального broker."""

    def __init__(self, database: str | Path, pepper: bytes, maximum_ttl: int = 600):
        if not pepper:
            raise ValueError("pepper is required")
        self.database = str(database)
        self.pepper = pepper
        self.maximum_ttl = maximum_ttl
        self._lock = threading.RLock()
        self._connection = sqlite3.connect(self.database, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA journal_mode=WAL")
        self._connection.execute("PRAGMA busy_timeout=5000")
        self._connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS shares (
                share_id TEXT PRIMARY KEY,
                token_hash TEXT NOT NULL UNIQUE,
                kind TEXT NOT NULL,
                created_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                state TEXT NOT NULL,
                metadata_json TEXT NOT NULL DEFAULT '{}',
                otp_hash TEXT,
                otp_attempts INTEGER NOT NULL DEFAULT 0
            );
            CREATE INDEX IF NOT EXISTS shares_expiry_idx ON shares (state, expires_at);
            """
        )
        self._connection.commit()

    @locked
    def close(self) -> None:
        self._connection.close()

    @locked
    def create(self, kind: ShareKind, ttl_seconds: int, metadata: dict[str, str] | None = None):
        ttl = clamp_ttl(ttl_seconds, self.maximum_ttl)
        token = generate_token()
        now = datetime.now(timezone.utc)
        record = ShareRecord(
            share_id=secrets.token_urlsafe(18),
            token_hash=hash_token(token, self.pepper),
            kind=kind,
            created_at=now,
            expires_at=new_expiry(ttl, self.maximum_ttl),
        )
        self._connection.execute(
            "INSERT INTO shares (share_id, token_hash, kind, created_at, expires_at, state, metadata_json) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (record.share_id, record.token_hash, record.kind.value, record.created_at.isoformat(), record.expires_at.isoformat(), record.state.value, json.dumps(metadata or {}, ensure_ascii=False, separators=(",", ":"))),
        )
        self._connection.commit()
        return record, token

    @locked
    def active_for_target(self, target: str) -> ShareRecord | None:
        rows = self._connection.execute("SELECT * FROM shares WHERE state = ?", (ShareState.OPEN.value,)).fetchall()
        for row in rows:
            metadata = json.loads(row["metadata_json"] or "{}")
            record = self._row_to_record(row)
            if metadata.get("target") == target and not record.is_expired():
                return record
        return None

    @locked
    def has_open(self, kind: ShareKind | None = None) -> bool:
        if kind is None:
            row = self._connection.execute("SELECT 1 FROM shares WHERE state = ? LIMIT 1", (ShareState.OPEN.value,)).fetchone()
        else:
            row = self._connection.execute("SELECT 1 FROM shares WHERE state = ? AND kind = ? LIMIT 1", (ShareState.OPEN.value, kind.value)).fetchone()
        return row is not None

    @locked
    def set_otp(self, share_id: str, otp_hash: str) -> None:
        self._connection.execute("UPDATE shares SET otp_hash = ?, otp_attempts = 0 WHERE share_id = ? AND state = ?", (otp_hash, share_id, ShareState.OPEN.value))
        self._connection.commit()

    @locked
    def verify_otp(self, share_id: str, otp_hash: str) -> bool:
        row = self._connection.execute("SELECT otp_hash, otp_attempts, state FROM shares WHERE share_id = ?", (share_id,)).fetchone()
        if not row or row["state"] != ShareState.OPEN.value or not row["otp_hash"] or row["otp_attempts"] >= 5:
            return False
        valid = hmac.compare_digest(row["otp_hash"], otp_hash)
        if valid:
            self._connection.execute("UPDATE shares SET otp_hash = NULL WHERE share_id = ? AND state = ?", (share_id, ShareState.OPEN.value))
        else:
            attempts = row["otp_attempts"] + 1
            state = ShareState.REVOKED.value if attempts >= 5 else ShareState.OPEN.value
            self._connection.execute("UPDATE shares SET otp_attempts = ?, state = ? WHERE share_id = ? AND state = ?", (attempts, state, share_id, ShareState.OPEN.value))
        self._connection.commit()
        return valid

    @locked
    def get_by_token(self, token: str) -> ShareRecord | None:
        row = self._connection.execute("SELECT * FROM shares WHERE token_hash = ?", (hash_token(token, self.pepper),)).fetchone()
        if row is None:
            return None
        record = self._row_to_record(row)
        if record.state is ShareState.OPEN and record.is_expired():
            self._connection.execute("UPDATE shares SET state = ? WHERE share_id = ? AND state = ?", (ShareState.EXPIRED.value, record.share_id, ShareState.OPEN.value))
            self._connection.commit()
            return None
        return record

    @locked
    def revoke(self, share_id: str) -> bool:
        cursor = self._connection.execute("UPDATE shares SET state = ? WHERE share_id = ? AND state = ?", (ShareState.REVOKED.value, share_id, ShareState.OPEN.value))
        self._connection.commit()
        return cursor.rowcount == 1

    @locked
    def consume(self, share_id: str) -> bool:
        cursor = self._connection.execute("UPDATE shares SET state = ? WHERE share_id = ? AND state = ?", (ShareState.CONSUMED.value, share_id, ShareState.OPEN.value))
        self._connection.commit()
        return cursor.rowcount == 1

    @locked
    def expire_due(self, now: datetime | None = None) -> int:
        cursor = self._connection.execute("UPDATE shares SET state = ? WHERE state = ? AND expires_at <= ?", (ShareState.EXPIRED.value, ShareState.OPEN.value, (now or datetime.now(timezone.utc)).isoformat()))
        self._connection.commit()
        return cursor.rowcount

    @staticmethod
    def _row_to_record(row: sqlite3.Row) -> ShareRecord:
        return ShareRecord(share_id=row["share_id"], token_hash=row["token_hash"], kind=ShareKind(row["kind"]), created_at=datetime.fromisoformat(row["created_at"]), expires_at=datetime.fromisoformat(row["expires_at"]), state=ShareState(row["state"]))
