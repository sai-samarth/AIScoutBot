import json
import aiosqlite
from datetime import datetime, timezone, timedelta
from pathlib import Path

DB_PATH = Path(__file__).parent / "data" / "seen_models.db"

_CREATE_SEEN_MODELS = """
CREATE TABLE IF NOT EXISTS seen_models (
    model_id TEXT PRIMARY KEY,
    first_seen_at TEXT NOT NULL
);
"""

_CREATE_SENT_MESSAGES = """
CREATE TABLE IF NOT EXISTS sent_messages (
    wa_message_id TEXT PRIMARY KEY,
    group_jid     TEXT NOT NULL,
    model_ids     TEXT,
    message_type  TEXT NOT NULL,
    sent_at       TEXT NOT NULL
);
"""

_CREATE_SENT_INDEX = """
CREATE INDEX IF NOT EXISTS idx_sent_messages_sent_at ON sent_messages(sent_at);
"""


async def init_db() -> None:
    """Create tables if they don't exist. Call once at startup."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(_CREATE_SEEN_MODELS)
        await db.execute(_CREATE_SENT_MESSAGES)
        await db.execute(_CREATE_SENT_INDEX)
        await db.commit()


async def check_seen(model_id: str) -> bool:
    """Return True if model_id is already in the database."""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT 1 FROM seen_models WHERE model_id = ?", (model_id,)
        ) as cursor:
            return await cursor.fetchone() is not None


async def mark_seen_batch(model_ids: list[str]) -> None:
    """Insert multiple model_ids in a single transaction. Call after successful send."""
    now = datetime.now(timezone.utc).isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executemany(
            "INSERT OR IGNORE INTO seen_models (model_id, first_seen_at) VALUES (?, ?)",
            [(mid, now) for mid in model_ids],
        )
        await db.commit()


async def track_sent_message(
    wa_message_id: str,
    group_jid: str,
    model_ids: list[str] | None,
    message_type: str,
) -> None:
    """Record a message sent by the bot for reply-trigger detection."""
    now = datetime.now(timezone.utc).isoformat()
    model_ids_json = json.dumps(model_ids) if model_ids else None
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR IGNORE INTO sent_messages (wa_message_id, group_jid, model_ids, message_type, sent_at) VALUES (?, ?, ?, ?, ?)",
            (wa_message_id, group_jid, model_ids_json, message_type, now),
        )
        await db.commit()


async def lookup_sent_message(wa_message_id: str) -> dict | None:
    """Look up a sent message by WhatsApp message ID. Returns dict or None."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT wa_message_id, group_jid, model_ids, message_type, sent_at FROM sent_messages WHERE wa_message_id = ?",
            (wa_message_id,),
        ) as cursor:
            row = await cursor.fetchone()
            if row is None:
                return None
            result = dict(row)
            if result["model_ids"]:
                result["model_ids"] = json.loads(result["model_ids"])
            return result


async def prune_sent_messages(days: int = 7) -> None:
    """Delete sent_messages older than N days."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM sent_messages WHERE sent_at < ?", (cutoff,))
        await db.commit()
