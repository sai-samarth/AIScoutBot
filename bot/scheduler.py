import logging
from datetime import datetime, timezone, timedelta

import pytz
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from bot.config import config
from bot.db import check_seen, mark_seen_batch, prune_sent_messages
from bot.formatter import format_model, MAX_MODELS_PER_ALERT
from bot.sender import deliver_models

logger = logging.getLogger(__name__)


def build_scheduler() -> AsyncIOScheduler:
    """
    Build and return a configured (not yet started) AsyncIOScheduler with:
    - Frequent alert scan job for Tier 1 (watched orgs) + Tier 2 (trending)
    """
    tz = pytz.timezone(config.schedule.timezone)
    scheduler = AsyncIOScheduler(timezone=tz)

    hf_cfg = config.sources.huggingface
    if hf_cfg.enabled and hf_cfg.watched_orgs:
        interval = hf_cfg.scan_interval_minutes
        scheduler.add_job(
            alert_scan,
            IntervalTrigger(minutes=interval),
            id="alert_scan",
            replace_existing=True,
        )
        logger.info(
            "Scheduled alert_scan every %d minutes (%d watched orgs)",
            interval,
            len(hf_cfg.watched_orgs),
        )

    scheduler.add_job(
        _prune_sent_messages,
        IntervalTrigger(hours=24),
        id="prune_sent_messages",
        replace_existing=True,
    )

    return scheduler


async def _prune_sent_messages() -> None:
    """Delete sent_messages older than 7 days."""
    await prune_sent_messages(days=7)
    logger.info("Pruned sent_messages older than 7 days")


async def alert_scan(fresh: bool = False) -> dict:
    """
    Scan for Tier 1 (watched orgs) and Tier 2 (trending models).
    Sends a WhatsApp alert for any new unseen models.

    fresh=True skips deduplication and does not update the DB.
    """
    hf_cfg = config.sources.huggingface
    now = datetime.now(timezone.utc)
    since = now - timedelta(hours=hf_cfg.trending_lookback_hours)
    logger.info("Starting alert scan: since=%s fresh=%s", since.isoformat(), fresh)

    from bot.scanner.huggingface import HuggingFaceSource
    source = HuggingFaceSource(hf_cfg)

    try:
        tier1, tier2 = await source.scan_alert(since)
    except Exception as exc:
        logger.error("Alert scan failed: %s", exc)
        return {"status": "error", "error": str(exc)}

    if not tier1 and not tier2:
        logger.debug("Alert scan: no models found")
        return {"status": "no_models"}

    all_models = tier1 + tier2

    if fresh:
        new_models = all_models
        logger.info("fresh=True — skipping deduplication, using all %d models", len(new_models))
    else:
        new_models = []
        for m in all_models:
            if not await check_seen(m.model_id):
                new_models.append(m)

    if not new_models:
        logger.debug("Alert scan: no new models after deduplication")
        return {"status": "no_new_models"}

    models_to_send = new_models[:MAX_MODELS_PER_ALERT]
    logger.info("Alert scan: %d new models to alert on", len(models_to_send))

    texts = [format_model(m) for m in models_to_send]
    model_ids_per_text = [[m.model_id] for m in models_to_send]

    success = await deliver_models(texts, config.whatsapp.target_groups, model_ids_per_text)

    if success and not fresh:
        await mark_seen_batch([m.model_id for m in new_models])
        logger.info("Alert sent — %d models marked as seen", len(new_models))
    elif success and fresh:
        logger.info("fresh=True — skipping mark_seen, DB unchanged")
    else:
        logger.warning("Alert delivery failed — models NOT marked as seen, will retry")

    return {"status": "alerted", "count": len(new_models)}
