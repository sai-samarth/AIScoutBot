import logging
from datetime import datetime, timezone, timedelta

import pytz
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from bot.config import config
from bot.db import check_seen, mark_seen_batch
from bot.formatter import format_digest
from bot.scanner import get_all_sources
from bot.sender import deliver_digest

logger = logging.getLogger(__name__)


def build_scheduler() -> AsyncIOScheduler:
    """
    Parse config.schedule.times into APScheduler CronTriggers and register scan_and_send.
    Returns a configured (not yet started) AsyncIOScheduler.
    """
    tz = pytz.timezone(config.schedule.timezone)
    scheduler = AsyncIOScheduler(timezone=tz)

    for time_str in config.schedule.times:
        hour, minute = time_str.split(":")
        trigger = CronTrigger(hour=int(hour), minute=int(minute), timezone=tz)
        scheduler.add_job(scan_and_send, trigger=trigger, id=f"scan_{time_str}", replace_existing=True)
        logger.info("Scheduled scan_and_send at %s %s", time_str, config.schedule.timezone)

    return scheduler


async def scan_and_send(fresh: bool = False) -> dict:
    """
    Main job: scan → deduplicate → format → send → mark_seen.
    mark_seen is only called after at least one successful delivery.

    fresh=True skips the seen-models check so already-seen models are re-posted.
    Useful for testing. Does NOT modify the DB — seen records are preserved.
    """
    now = datetime.now(timezone.utc)
    since = now - timedelta(hours=config.schedule.scan_lookback_hours)
    logger.info("Starting scan: since=%s fresh=%s", since.isoformat(), fresh)

    # 1. Collect results from all enabled sources
    sources = get_all_sources(config)
    all_results = []
    for source in sources:
        try:
            results = await source.scan(since)
            logger.info("Source %s returned %d models", source.source_name, len(results))
            all_results.extend(results)
        except Exception as exc:
            logger.error("Source %s scan failed: %s", source.source_name, exc)

    if not all_results:
        logger.info("No models returned from any source")
        return {"status": "no_models"}

    # 2. Deduplicate (skipped when fresh=True)
    if fresh:
        new_models = all_results
        logger.info("fresh=True — skipping deduplication, using all %d models", len(new_models))
    else:
        new_models = []
        for model in all_results:
            if not await check_seen(model.model_id):
                new_models.append(model)

    if not new_models:
        logger.info("No new models after deduplication")
        return {"status": "no_new_models"}

    logger.info("Found %d new models to post", len(new_models))

    # 3. Format digest
    text = format_digest(new_models, now, config.schedule.scan_lookback_hours)
    if not text:
        logger.info("Formatter returned empty string — skipping send")
        return {"status": "empty_digest"}

    # 4. Deliver to all target groups
    success = await deliver_digest(text, config.whatsapp.target_groups)

    # 5. Mark seen only after successful delivery (only when not in fresh/test mode)
    if success and not fresh:
        await mark_seen_batch([m.model_id for m in new_models])
        logger.info("Marked %d models as seen", len(new_models))
    elif success and fresh:
        logger.info("fresh=True — skipping mark_seen, DB unchanged")
    else:
        logger.warning("Delivery failed — models NOT marked as seen; will retry next run")

    return {"status": "sent", "count": len(new_models)}
