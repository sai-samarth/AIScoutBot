import logging
import os

import httpx

from bot.config import config

logger = logging.getLogger(__name__)

GATEWAY_URL = os.environ.get("GATEWAY_URL", f"http://localhost:{config.gateway.port}")
SEND_TIMEOUT = 10.0


async def get_groups() -> list[dict]:
    """
    Call GET /groups on the gateway.
    Returns list of {id, subject, participantCount}.
    Raises httpx.HTTPError on failure.
    """
    async with httpx.AsyncClient(timeout=SEND_TIMEOUT) as client:
        resp = await client.get(f"{GATEWAY_URL}/groups")
        resp.raise_for_status()
        return resp.json()["groups"]


async def resolve_group_jids(target_names: list[str]) -> list[str]:
    """
    Resolve group name substrings to JIDs.
    Case-insensitive substring match against group subject.
    Logs a warning for any target_name that matches zero groups.
    """
    try:
        groups = await get_groups()
    except Exception as exc:
        logger.warning("Could not fetch groups from gateway: %s", exc)
        return []

    jids: list[str] = []
    for name in target_names:
        name_lower = name.lower()
        matched = [g for g in groups if name_lower in g["subject"].lower()]
        if not matched:
            logger.warning("No group matched target_name=%r — check config.yaml or group membership", name)
        for g in matched:
            logger.info("Resolved group target=%r → jid=%s subject=%r", name, g["id"], g["subject"])
            if g["id"] not in jids:
                jids.append(g["id"])

    return jids


async def send_text(jid: str, text: str) -> None:
    """POST /send to the gateway. Raises on non-2xx."""
    async with httpx.AsyncClient(timeout=SEND_TIMEOUT) as client:
        resp = await client.post(f"{GATEWAY_URL}/send", json={"jid": jid, "text": text})
        resp.raise_for_status()


async def deliver_models(texts: list[str], target_groups: list[str]) -> bool:
    """
    Resolve groups, send each text as a separate message to each group.
    Returns True if at least one send succeeded.
    Per-message failures are logged but do not abort remaining sends.
    """
    jids = await resolve_group_jids(target_groups)
    if not jids:
        logger.warning("No target JIDs resolved — messages not sent")
        return False

    any_success = False
    for jid in jids:
        for text in texts:
            try:
                await send_text(jid, text)
                any_success = True
            except Exception as exc:
                logger.error("Failed to deliver message to jid=%s: %s", jid, exc)

    if any_success:
        logger.info("Delivered %d messages to %d JIDs", len(texts), len(jids))
    return any_success
