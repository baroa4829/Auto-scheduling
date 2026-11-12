"""SQLite 저장소: 받은 메시지(문맥용·중복 방지)와 등록한 일정(수정·취소 추적용)."""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .models import ChatMessage
from .usage import Usage

_SCHEMA = """
CREATE TABLE IF NOT EXISTS messages (
    fingerprint TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    room TEXT NOT NULL,
    sender TEXT NOT NULL,
    text TEXT NOT NULL,
    ts TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_messages_room_ts ON messages(source, room, ts);

CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    room TEXT NOT NULL,
    title TEXT NOT NULL,
    start TEXT NOT NULL,
    end TEXT,
    all_day INTEGER NOT NULL,
    location TEXT,
    status TEXT NOT NULL,
    gcal_id TEXT,
    cancelled INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_events_room ON events(source, room);

CREATE TABLE IF NOT EXISTS api_usage (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    model TEXT NOT NULL,
    source TEXT,
    room TEXT,
    input_tokens INTEGER NOT NULL,
    output_tokens INTEGER NOT NULL,
    cache_read_tokens INTEGER NOT NULL,
    cache_write_tokens INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_usage_ts ON api_usage(ts);
"""


@dataclass
class StoredEvent:
    id: int
    source: str
    room: str
    title: str
    start: str
    end: str | None
    all_day: bool
    location: str | None
    status: str
    gcal_id: str | None
    cancelled: bool


class Store:
    def __init__(self, path: Path | str):
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(path), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(_SCHEMA)

    # ---- messages ----
    def add_message(self, msg: ChatMessage) -> bool:
        """새 메시지면 저장하고 True, 이미 본 메시지면 False."""
        cur = self.conn.execute(
            "INSERT OR IGNORE INTO messages VALUES (?,?,?,?,?,?)",
            (msg.fingerprint, msg.source, msg.room, msg.sender, msg.text, msg.timestamp.isoformat()),
        )
        self.conn.commit()
        return cur.rowcount == 1

    def recent_messages(
        self, source: str, room: str, until: datetime, limit: int, hours: int
    ) -> list[ChatMessage]:
        since = until - timedelta(hours=hours)
        rows = self.conn.execute(
            "SELECT * FROM messages WHERE source=? AND room=? AND ts>=? AND ts<=? "
            "ORDER BY ts DESC LIMIT ?",
            (source, room, since.isoformat(), until.isoformat(), limit),
        ).fetchall()
        return [
            ChatMessage(r["source"], r["room"], r["sender"], r["text"], datetime.fromisoformat(r["ts"]))
            for r in reversed(rows)
        ]

    # ---- events ----
    def _row_to_event(self, r: sqlite3.Row) -> StoredEvent:
        return StoredEvent(
            id=r["id"], source=r["source"], room=r["room"], title=r["title"], start=r["start"],
            end=r["end"], all_day=bool(r["all_day"]), location=r["location"], status=r["status"],
            gcal_id=r["gcal_id"], cancelled=bool(r["cancelled"]),
        )

    def active_events(self, source: str, room: str) -> list[StoredEvent]:
        rows = self.conn.execute(
            "SELECT * FROM events WHERE source=? AND room=? AND cancelled=0 ORDER BY start",
            (source, room),
        ).fetchall()
        return [self._row_to_event(r) for r in rows]

    def get_event(self, event_id: int) -> StoredEvent | None:
        r = self.conn.execute("SELECT * FROM events WHERE id=?", (event_id,)).fetchone()
        return self._row_to_event(r) if r else None

    def insert_event(self, source: str, room: str, title: str, start: str, end: str | None,
                     all_day: bool, location: str | None, status: str, gcal_id: str | None) -> int:
        cur = self.conn.execute(
            "INSERT INTO events (source, room, title, start, end, all_day, location, status, gcal_id, updated_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            (source, room, title, start, end, int(all_day), location, status, gcal_id,
             datetime.now().isoformat()),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def update_event(self, event_id: int, **fields) -> None:
        if "all_day" in fields:
            fields["all_day"] = int(fields["all_day"])
        if "cancelled" in fields:
            fields["cancelled"] = int(fields["cancelled"])
        fields["updated_at"] = datetime.now().isoformat()
        cols = ", ".join(f"{k}=?" for k in fields)
        self.conn.execute(f"UPDATE events SET {cols} WHERE id=?", (*fields.values(), event_id))
        self.conn.commit()

    def find_duplicate(self, source: str, room: str, start: str) -> StoredEvent | None:
        r = self.conn.execute(
            "SELECT * FROM events WHERE source=? AND room=? AND start=? AND cancelled=0",
            (source, room, start),
        ).fetchone()
        return self._row_to_event(r) if r else None

    # ---- API usage ----
    def record_usage(self, usage: Usage, source: str | None = None, room: str | None = None) -> None:
        self.conn.execute(
            "INSERT INTO api_usage (ts, model, source, room, input_tokens, output_tokens, "
            "cache_read_tokens, cache_write_tokens) VALUES (?,?,?,?,?,?,?,?)",
            (datetime.now(timezone.utc).isoformat(), usage.model, source, room, usage.input_tokens,
             usage.output_tokens, usage.cache_read_tokens, usage.cache_write_tokens),
        )
        self.conn.commit()

    def usage_summary(self, since: datetime | None = None) -> list[Usage]:
        """since 이후(없으면 전체) 사용량을 모델별로 합산."""
        where, params = "", ()
        if since is not None:
            where, params = "WHERE ts >= ?", (since.astimezone(timezone.utc).isoformat(),)
        rows = self.conn.execute(
            "SELECT model, COUNT(*) calls, SUM(input_tokens) i, SUM(output_tokens) o, "
            f"SUM(cache_read_tokens) cr, SUM(cache_write_tokens) cw FROM api_usage {where} "
            "GROUP BY model ORDER BY model",
            params,
        ).fetchall()
        return [Usage(r["model"], r["i"], r["o"], r["cr"], r["cw"], r["calls"]) for r in rows]
