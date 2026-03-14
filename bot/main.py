import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Query

from bot.db import init_db
from bot.models import IncomingMessage
from bot.scheduler import build_scheduler, scan_and_send, alert_scan

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%SZ",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting bot service")
    await init_db()
    scheduler = build_scheduler()
    scheduler.start()
    logger.info("Scheduler started")
    yield
    scheduler.shutdown()
    logger.info("Scheduler stopped")


app = FastAPI(title="AI Model Scout Bot", lifespan=lifespan)


@app.post("/trigger")
async def trigger(fresh: bool = Query(default=False, description="Skip seen-models check; re-post already-seen models without updating the DB")):
    """Manually trigger a scan-and-send cycle. Use ?fresh=true to re-post already-seen models (for testing)."""
    logger.info("Manual trigger: fresh=%s", fresh)
    result = await scan_and_send(fresh=fresh)
    return result


@app.post("/trigger/alert")
async def trigger_alert():
    """Manually trigger a Tier 1+2 alert scan (watched orgs + trending). Useful for testing."""
    logger.info("Manual alert scan triggered")
    result = await alert_scan()
    return result


@app.post("/incoming")
async def incoming(msg: IncomingMessage):
    """
    Phase 1 stub: receives forwarded WhatsApp messages from the gateway.
    Logs payload and returns 200.
    Phase 2 will implement reply-based Q&A and command handling here.
    """
    logger.info(
        "Incoming message: jid=%s sender=%s text=%r quoted_id=%s",
        msg.jid,
        msg.sender,
        msg.text[:80],
        msg.quotedMessageId,
    )
    return {"ok": True}
