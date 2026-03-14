import aiosqlite
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = Path(__file__).parent / "data" / "seen_models.db"

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS seen_models (
    model_id TEXT PRIMARY KEY,
    first_seen_at TEXT NOT NULL
);
"""


async def init_db() -> None:
    """Create seen_models table if it doesn't exist. Call once at startup."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(_CREATE_TABLE)
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
