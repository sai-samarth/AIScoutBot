import asyncio
import logging
import os
from datetime import datetime, timedelta, timezone

import httpx

from bot.config import HuggingFaceConfig
from bot.models import ModelResult

logger = logging.getLogger(__name__)

HF_API_BASE = "https://huggingface.co/api/models"

# Model-name substrings that indicate quantization / derivative / merge
DERIVATIVE_MARKERS = [
    "gguf", "awq", "gptq", "4bit", "8bit", "bnb",
    "merge", "abliterated", "uncensored", "lora",
    "exl2", "fp8", "quantized",
]

# Pipeline tags for LLMs, multimodal, and generation models
# Used to filter Tier 1 watched-org results
TIER1_ALLOWED_TAGS = {
    "text-generation",
    "image-text-to-text",
    "audio-text-to-text",
    "any-to-any",
    "text-to-image",
    "image-to-image",
    "image-text-to-image",
    "text-to-video",
    "image-to-video",
    "text-to-speech",
    "text-to-audio",
    "audio-to-audio",
    "automatic-speech-recognition",
}


class HuggingFaceSource:

    def __init__(self, cfg: HuggingFaceConfig) -> None:
        self._cfg = cfg
        self._token = os.environ.get("HF_TOKEN")

    @property
    def source_name(self) -> str:
        return "HuggingFace"

    def _make_headers(self) -> dict:
        headers = {}
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        return headers

    # -------------------------------------------------------------------------
    # Alert scan (Tier 1 — watched orgs, Tier 2 — trending)
    # -------------------------------------------------------------------------

    async def scan_alert(self, since: datetime) -> tuple[list[ModelResult], list[ModelResult]]:
        """
        Scan for Tier 1 (watched orgs) and Tier 2 (trending) models.
        Returns (tier1_models, tier2_models).
        """
        tier1: list[ModelResult] = []
        tier2: list[ModelResult] = []
        watched_lower = {org.lower() for org in self._cfg.watched_orgs}

        async with httpx.AsyncClient(headers=self._make_headers(), timeout=30.0) as client:
            for org in self._cfg.watched_orgs:
                try:
                    org_results = await self._scan_org(org, since, client)
                    if org_results:
                        logger.info("Tier1 org=%s found=%d models", org, len(org_results))
                    tier1.extend(org_results)
                except Exception as exc:
                    logger.warning("Tier1 scan failed for org=%s: %s", org, exc)
                await asyncio.sleep(0.2)

            try:
                t2 = await self._scan_trending(since, watched_lower, client)
                if t2:
                    logger.info("Tier2 trending found=%d models", len(t2))
                tier2.extend(t2)
            except Exception as exc:
                logger.warning("Tier2 trending scan failed: %s", exc)

        return tier1, tier2

    async def _scan_org(
        self, org: str, since: datetime, client: httpx.AsyncClient
    ) -> list[ModelResult]:
        """Fetch recently created models from a watched org, filtered to allowed pipeline tags."""
        params = {
            "author": org,
            "sort": "createdAt",
            "direction": -1,
            "limit": 50,
            "full": "true",
        }
        try:
            resp = await client.get(HF_API_BASE, params=params)
        except httpx.RequestError as exc:
            logger.warning("HF request error for org=%s: %s", org, exc)
            return []

        if resp.status_code == 429:
            logger.warning("HF rate limited for org=%s", org)
            return []
        if resp.status_code != 200:
            logger.warning("HF returned %d for org=%s", resp.status_code, org)
            return []

        items: list[dict] = resp.json()
        results = []
        for raw in items:
            created_str = raw.get("createdAt")
            if not created_str:
                continue
            created = datetime.fromisoformat(created_str.replace("Z", "+00:00"))
            if created < since:
                break  # sorted newest-first, safe to stop
            tag = raw.get("pipeline_tag") or "unknown"
            if tag not in TIER1_ALLOWED_TAGS:
                continue
            model = self._parse_model(raw)
            if model is not None:
                results.append(model)
        return results

    async def _scan_trending(
        self,
        since: datetime,
        watched_lower: set[str],
        client: httpx.AsyncClient,
    ) -> list[ModelResult]:
        """
        Fetch trending models from HuggingFace (sorted by their trending score),
        filtered to models created within last 7 days, not from watched orgs,
        and not derivative (quantizations, merges, LoRAs).
        """
        params = {
            "sort": "trendingScore",
            "direction": -1,
            "limit": 100,
            "full": "true",
        }
        try:
            resp = await client.get(HF_API_BASE, params=params)
        except httpx.RequestError as exc:
            logger.warning("HF trending request error: %s", exc)
            return []

        if resp.status_code == 429:
            logger.warning("HF rate limited for trending scan")
            return []
        if resp.status_code != 200:
            logger.warning("HF trending returned status %d", resp.status_code)
            return []

        items: list[dict] = resp.json()
        # Creation window: extend back from since by (trending_creation_days - trending_lookback_hours/24) days
        tier2_since = since - timedelta(days=self._cfg.trending_creation_days - 1)

        results = []
        for raw in items:
            created_str = raw.get("createdAt")
            if not created_str:
                continue
            created = datetime.fromisoformat(created_str.replace("Z", "+00:00"))
            if created < tier2_since:
                continue  # don't break — trending sort is not time-ordered

            author = (raw.get("author") or "").lower()
            if author in watched_lower:
                continue

            model_id = raw.get("modelId") or raw.get("id", "")
            if self._is_derivative(model_id):
                continue

            model = self._parse_model(raw)
            if model is not None:
                results.append(model)
        return results

    # -------------------------------------------------------------------------
    # Helpers
    # -------------------------------------------------------------------------

    @staticmethod
    def _is_derivative(model_id: str) -> bool:
        """Return True if model name looks like a quantization/merge/finetune."""
        name_lower = model_id.lower()
        return any(marker in name_lower for marker in DERIVATIVE_MARKERS)

    def _parse_model(self, raw: dict) -> ModelResult | None:
        try:
            model_id = raw.get("modelId") or raw.get("id", "")
            if not model_id:
                return None

            last_modified_str = raw.get("lastModified") or raw.get("updatedAt", "")
            created_at = datetime.fromisoformat(
                last_modified_str.replace("Z", "+00:00")
            ) if last_modified_str else datetime.now(timezone.utc)

            author = raw.get("author") or model_id.split("/")[0]
            pipeline_tag = raw.get("pipeline_tag") or "unknown"
            url = f"https://huggingface.co/{model_id}"

            description: str | None = None
            card_data = raw.get("cardData") or {}
            if isinstance(card_data, dict):
                description = card_data.get("description") or None
            if description:
                description = description[:200].strip()

            return ModelResult(
                model_id=model_id,
                pipeline_tag=pipeline_tag,
                likes=raw.get("likes", 0),
                downloads=raw.get("downloads", 0),
                created_at=created_at,
                url=url,
                author=author,
                description=description,
            )
        except Exception as exc:
            logger.debug("Failed to parse HF model %s: %s", raw.get("modelId", "?"), exc)
            return None
