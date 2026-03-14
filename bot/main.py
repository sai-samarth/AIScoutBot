import asyncio
import logging
import os
import re
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, Query

import bot.agent_handler as agent_handler
from bot.db import init_db
from bot.models import IncomingMessage
from bot.scheduler import build_scheduler, alert_scan
from bot.agent_handler import handle_incoming
from bot.sender import GATEWAY_URL

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%SZ",
)
logger = logging.getLogger(__name__)


async def _discover_bot_jid() -> None:
    """Auto-discover bot's WhatsApp JID from the gateway. Falls back to BOT_JID env var."""
    jid = os.environ.get("BOT_JID", "")
    if jid:
        agent_handler.BOT_JID = jid
        logger.info("BOT_JID from env: %s", jid)
        return

    for attempt in range(5):
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"{GATEWAY_URL}/me")
                if resp.status_code == 200:
                    data = resp.json()
                    raw_jid = data.get("jid", "")
                    # Strip device suffix: "1234567890:23@s.whatsapp.net" → "1234567890@s.whatsapp.net"
                    agent_handler.BOT_JID = re.sub(r":\d+@", "@", raw_jid)
                    # LID used by newer WhatsApp clients for @mentions — strip device suffix too
                    raw_lid = data.get("lid") or ""
                    agent_handler.BOT_LID = re.sub(r":\d+@", "@", raw_lid)
                    logger.info("Auto-discovered BOT_JID=%s BOT_LID=%s", agent_handler.BOT_JID, agent_handler.BOT_LID)
                    return
        except Exception:
            pass
        await asyncio.sleep(3)

    logger.warning("Could not discover BOT_JID — @mention detection will not work")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting bot service")
    await init_db()
    scheduler = build_scheduler()
    scheduler.start()
    logger.info("Scheduler started")
    await _discover_bot_jid()
    yield
    scheduler.shutdown()
    logger.info("Scheduler stopped")


app = FastAPI(title="AI Model Scout Bot", lifespan=lifespan)


@app.post("/trigger")
async def trigger(fresh: bool = Query(default=False, description="Skip seen-models check; re-post already-seen models without updating the DB")):
    """Manually trigger a Tier 1+2 alert scan. Use ?fresh=true to bypass deduplication."""
    logger.info("Manual trigger: fresh=%s", fresh)
    result = await alert_scan(fresh=fresh)
    return result


@app.post("/incoming")
async def incoming(msg: IncomingMessage):
    """
    Receives forwarded WhatsApp messages from the gateway.
    Checks triggers and optionally invokes the Q&A agent.
    """
    logger.info(
        "Incoming message: jid=%s sender=%s text=%r quoted_id=%s",
        msg.jid,
        msg.sender,
        msg.text[:80],
        msg.quotedMessageId,
    )
    return await handle_incoming(msg)
