"""SQLite store for unique Cursor credit links."""
from __future__ import annotations

import os
import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

BASE_DIR = Path(__file__).resolve().parent

try:
    from dotenv import load_dotenv

    load_dotenv(BASE_DIR / ".env")
except ImportError:
    pass

DEFAULT_DB_PATH = BASE_DIR / "data" / "credits.sqlite"

_db_lock = threading.Lock()


@dataclass(frozen=True)
class ClaimResult:
    link_id: int
    url: str
    guest_id: str
    guest_name: str
    guest_email: str | None
    already_claimed: bool
    claimed_at: str | None


@dataclass(frozen=True)
class PoolStatus:
    available: int
    claimed: int
    void: int
    total: int
    recent: list[dict[str, Any]]


def db_path() -> Path:
    env = os.getenv("CREDITS_DB_PATH", "").strip()
    if env:
        return Path(env)
    return DEFAULT_DB_PATH


def _connect() -> sqlite3.Connection:
    path = db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def init_db() -> None:
    with _db_lock:
        conn = _connect()
        try:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS links (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    url TEXT NOT NULL UNIQUE,
                    status TEXT NOT NULL DEFAULT 'available'
                        CHECK (status IN ('available', 'claimed', 'void')),
                    guest_id TEXT,
                    guest_name TEXT,
                    guest_email TEXT,
                    claimed_at TEXT,
                    printed_at TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_links_status ON links(status);
                CREATE INDEX IF NOT EXISTS idx_links_guest_id ON links(guest_id);
                """
            )
            conn.commit()
        finally:
            conn.close()


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def import_urls(lines: list[str]) -> dict[str, int]:
    """Import one URL per line. Skips empty lines and duplicates."""
    init_db()
    added = 0
    skipped = 0
    with _db_lock:
        conn = _connect()
        try:
            for raw in lines:
                url = raw.strip()
                if not url:
                    continue
                try:
                    conn.execute(
                        "INSERT INTO links (url, status) VALUES (?, 'available')",
                        (url,),
                    )
                    added += 1
                except sqlite3.IntegrityError:
                    skipped += 1
            conn.commit()
        finally:
            conn.close()
    return {"added": added, "skipped": skipped}


def claim_for_guest(
    guest_id: str,
    guest_name: str,
    guest_email: str | None = None,
) -> ClaimResult:
    """Claim one link for a guest, or return an existing claim."""
    init_db()
    guest_id = guest_id.strip()
    guest_name = (guest_name or "").strip() or "Guest"
    guest_email = (guest_email or "").strip() or None

    with _db_lock:
        conn = _connect()
        try:
            existing = conn.execute(
                """
                SELECT id, url, guest_id, guest_name, guest_email, claimed_at
                FROM links
                WHERE guest_id = ? AND status = 'claimed'
                ORDER BY claimed_at DESC
                LIMIT 1
                """,
                (guest_id,),
            ).fetchone()
            if existing:
                conn.execute(
                    """
                    UPDATE links
                    SET guest_name = ?, guest_email = ?
                    WHERE id = ?
                    """,
                    (guest_name, guest_email, existing["id"]),
                )
                conn.commit()
                return ClaimResult(
                    link_id=existing["id"],
                    url=existing["url"],
                    guest_id=existing["guest_id"],
                    guest_name=guest_name,
                    guest_email=guest_email or existing["guest_email"],
                    already_claimed=True,
                    claimed_at=existing["claimed_at"],
                )

            now = _now_iso()
            cur = conn.execute(
                """
                UPDATE links
                SET status = 'claimed',
                    guest_id = ?,
                    guest_name = ?,
                    guest_email = ?,
                    claimed_at = ?
                WHERE id = (
                    SELECT id FROM links
                    WHERE status = 'available'
                    ORDER BY id ASC
                    LIMIT 1
                )
                RETURNING id, url, guest_id, guest_name, guest_email, claimed_at
                """,
                (guest_id, guest_name, guest_email, now),
            )
            row = cur.fetchone()
            if row is None:
                raise RuntimeError("No credit links remaining in the pool.")

            conn.commit()
            return ClaimResult(
                link_id=row["id"],
                url=row["url"],
                guest_id=row["guest_id"],
                guest_name=row["guest_name"] or guest_name,
                guest_email=row["guest_email"],
                already_claimed=False,
                claimed_at=row["claimed_at"],
            )
        finally:
            conn.close()


def mark_printed(link_id: int) -> None:
    init_db()
    with _db_lock:
        conn = _connect()
        try:
            conn.execute(
                "UPDATE links SET printed_at = ? WHERE id = ?",
                (_now_iso(), link_id),
            )
            conn.commit()
        finally:
            conn.close()


def get_claimed_url(guest_id: str) -> ClaimResult | None:
    init_db()
    with _db_lock:
        conn = _connect()
        try:
            row = conn.execute(
                """
                SELECT id, url, guest_id, guest_name, guest_email, claimed_at
                FROM links
                WHERE guest_id = ? AND status = 'claimed'
                ORDER BY claimed_at DESC
                LIMIT 1
                """,
                (guest_id.strip(),),
            ).fetchone()
            if row is None:
                return None
            return ClaimResult(
                link_id=row["id"],
                url=row["url"],
                guest_id=row["guest_id"],
                guest_name=row["guest_name"] or "Guest",
                guest_email=row["guest_email"],
                already_claimed=True,
                claimed_at=row["claimed_at"],
            )
        finally:
            conn.close()


def pool_status(recent_limit: int = 5) -> PoolStatus:
    init_db()
    with _db_lock:
        conn = _connect()
        try:
            counts = conn.execute(
                """
                SELECT status, COUNT(*) AS count
                FROM links
                GROUP BY status
                """
            ).fetchall()
            by_status = {row["status"]: row["count"] for row in counts}
            available = by_status.get("available", 0)
            claimed = by_status.get("claimed", 0)
            void = by_status.get("void", 0)
            total = available + claimed + void

            recent_rows = conn.execute(
                """
                SELECT guest_name, guest_email, claimed_at, printed_at
                FROM links
                WHERE status = 'claimed'
                ORDER BY claimed_at DESC
                LIMIT ?
                """,
                (recent_limit,),
            ).fetchall()
            recent = [
                {
                    "guest_name": row["guest_name"] or "Guest",
                    "guest_email": row["guest_email"],
                    "claimed_at": row["claimed_at"],
                    "printed_at": row["printed_at"],
                }
                for row in recent_rows
            ]
            return PoolStatus(
                available=available,
                claimed=claimed,
                void=void,
                total=total,
                recent=recent,
            )
        finally:
            conn.close()
