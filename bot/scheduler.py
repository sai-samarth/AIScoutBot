import logging
from datetime import datetime, timezone, timedelta

import pytz
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from bot.config import config
from bot.db import check_seen, mark_seen_batch
from bot.formatter import format_digest, format_alert
from bot.scanner import get_all_sources
from bot.sender import deliver_digest

logger = logging.getLogger(__name__)


def build_scheduler() -> AsyncIOScheduler:
    """
    Build and return a configured (not yet started) AsyncIOScheduler with:
    - Frequent alert scan job for Tier 1 (watched orgs) + Tier 2 (trending)
    """
    tz = pytz.timezone(config.schedule.timezone)
    scheduler = AsyncIOScheduler(timezone=tz)

    # Frequent alert scan for Tier 1+2
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

    return scheduler


async def alert_scan() -> dict:
    """
    Frequent scan for Tier 1 (watched orgs) and Tier 2 (trending models).
    Sends an immediate WhatsApp alert for any new unseen models.
    """
    hf_cfg = config.sources.huggingface
    now = datetime.now(timezone.utc)
    since = now - timedelta(hours=hf_cfg.trending_lookback_hours)
    logger.info("Starting alert scan: since=%s", since.isoformat())

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

    # Deduplicate — check DB for models we've already alerted on
    new_models: list = []
    tier_labels: dict[str, str] = {}

    for m in tier1:
        if not await check_seen(m.model_id):
            new_models.append(m)
            tier_labels[m.model_id] = f"Watched: {m.author}"

    for m in tier2:
        if not await check_seen(m.model_id):
            new_models.append(m)
            tier_labels[m.model_id] = f"Trending — {m.likes:,} likes"

    if not new_models:
        logger.debug("Alert scan: no new models after deduplication")
        return {"status": "no_new_models"}

    logger.info("Alert scan: %d new models to alert on", len(new_models))

    text = format_alert(new_models, now, tier_labels)
    if not text:
        return {"status": "empty_alert"}

    success = await deliver_digest(text, config.whatsapp.target_groups)

    if success:
        await mark_seen_batch([m.model_id for m in new_models])
        logger.info("Alert sent — %d models marked as seen", len(new_models))
        return {"status": "alerted", "count": len(new_models)}
    else:
        logger.warning("Alert delivery failed — models NOT marked as seen, will retry")
        return {"status": "delivery_failed"}


async def scan_and_send(fresh: bool = False) -> dict:
    """
    Daily digest job: scan pipeline_tags → deduplicate → format → send → mark_seen.
    mark_seen is only called after at least one successful delivery.

    fresh=True skips the seen-models check so already-seen models are re-posted.
    Useful for testing. Does NOT modify the DB — seen records are preserved.
    """
    now = datetime.now(timezone.utc)
    since = now - timedelta(hours=config.schedule.scan_lookback_hours)
    logger.info("Starting digest scan: since=%s fresh=%s", since.isoformat(), fresh)

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

    text = format_digest(new_models, now, config.schedule.scan_lookback_hours)
    if not text:
        logger.info("Formatter returned empty string — skipping send")
        return {"status": "empty_digest"}

    success = await deliver_digest(text, config.whatsapp.target_groups)

    if success and not fresh:
        await mark_seen_batch([m.model_id for m in new_models])
        logger.info("Marked %d models as seen", len(new_models))
    elif success and fresh:
        logger.info("fresh=True — skipping mark_seen, DB unchanged")
    else:
        logger.warning("Delivery failed — models NOT marked as seen; will retry next run")

    return {"status": "sent", "count": len(new_models)}
