import asyncio
import logging
import os
from datetime import datetime, timezone

import httpx

from bot.config import HuggingFaceConfig
from bot.models import ModelResult
from bot.scanner.base import BaseSource

logger = logging.getLogger(__name__)

HF_API_BASE = "https://huggingface.co/api/models"
PAGE_SIZE = 100
MAX_PAGES = 5  # hard ceiling: 500 models max per pipeline_tag per run

# Model-name substrings that indicate quantization / derivative / merge — not original releases
DERIVATIVE_MARKERS = [
    "gguf", "awq", "gptq", "4bit", "8bit", "bnb",
    "merge", "abliterated", "uncensored", "lora",
    "exl2", "fp8", "quantized",
]

# Composite score threshold for Tier 2 alerting
TIER2_SCORE_THRESHOLD = 50

# Pipeline tags that represent LLMs, multimodal, and generation models
# Used to filter Tier 1 watched-org results to important model categories
TIER1_ALLOWED_TAGS = {
    # LLMs
    "text-generation",
    # Multimodal LLMs
    "image-text-to-text",
    "audio-text-to-text",
    "any-to-any",
    # Image generation
    "text-to-image",
    "image-to-image",
    "image-text-to-image",
    # Video generation
    "text-to-video",
    "image-to-video",
    # Audio / speech generation
    "text-to-speech",
    "text-to-audio",
    "audio-to-audio",
    # Speech recognition
    "automatic-speech-recognition",
}


class HuggingFaceSource(BaseSource):

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
    # Daily digest scan (Tier 3 — pipeline_tags, broader)
    # -------------------------------------------------------------------------

    async def scan(self, since: datetime) -> list[ModelResult]:
        results: list[ModelResult] = []

        async with httpx.AsyncClient(headers=self._make_headers(), timeout=30.0) as client:
            for tag in self._cfg.pipeline_tags:
                try:
                    tag_results = await self._fetch_tag(tag, since, client)
                    results.extend(tag_results)
                    logger.info("HuggingFace tag=%s found=%d new models", tag, len(tag_results))
                except Exception as exc:
                    logger.warning("HuggingFace scan failed for tag=%s: %s", tag, exc)

        return results

    async def _fetch_tag(
        self,
        tag: str,
        since: datetime,
        client: httpx.AsyncClient,
    ) -> list[ModelResult]:
        results: list[ModelResult] = []

        for page in range(MAX_PAGES):
            params = {
                "filter": tag,
                "sort": "lastModified",
                "direction": -1,
                "limit": PAGE_SIZE,
                "skip": page * PAGE_SIZE,
                "full": "true",
            }

            try:
                resp = await client.get(HF_API_BASE, params=params)
            except httpx.RequestError as exc:
                logger.warning("HuggingFace request error page=%d tag=%s: %s", page, tag, exc)
                break

            if resp.status_code == 429:
                logger.warning("HuggingFace rate limited (429) on tag=%s page=%d — stopping", tag, page)
                break

            resp.raise_for_status()
            items: list[dict] = resp.json()

            if not items:
                break

            stop_early = False
            for raw in items:
                last_modified_str = raw.get("lastModified") or raw.get("updatedAt")
                if not last_modified_str:
                    continue

                last_modified = datetime.fromisoformat(
                    last_modified_str.replace("Z", "+00:00")
                )

                if last_modified < since:
                    stop_early = True
                    break

                model = self._parse_model(raw, self._cfg.min_likes)
                if model is not None:
                    results.append(model)

            if stop_early or len(items) < PAGE_SIZE:
                break

            await asyncio.sleep(0.5)

        return results

    # -------------------------------------------------------------------------
    # Alert scan (Tier 1 — watched orgs, Tier 2 — trending with scoring)
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
            # Tier 1: one request per watched org
            for org in self._cfg.watched_orgs:
                try:
                    org_results = await self._scan_org(org, since, client)
                    if org_results:
                        logger.info("Tier1 org=%s found=%d models", org, len(org_results))
                    tier1.extend(org_results)
                except Exception as exc:
                    logger.warning("Tier1 scan failed for org=%s: %s", org, exc)
                await asyncio.sleep(0.2)

            # Tier 2: trending models from non-watched orgs, composite scored
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
        """Fetch recent models from a specific org (no min_likes filter)."""
        params = {
            "author": org,
            "sort": "lastModified",
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
            last_modified_str = raw.get("lastModified") or raw.get("updatedAt")
            if not last_modified_str:
                continue
            last_modified = datetime.fromisoformat(last_modified_str.replace("Z", "+00:00"))
            if last_modified < since:
                break
            # Only include models in allowed pipeline categories (LLMs, multimodal, gen)
            tag = raw.get("pipeline_tag") or "unknown"
            if tag not in TIER1_ALLOWED_TAGS:
                continue
            model = self._parse_model(raw, min_likes=0)
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
        Fetch trending models, filter to recent ones from non-watched orgs,
        apply composite scoring (arxiv, likes, org account, downloads).
        Only models scoring >= TIER2_SCORE_THRESHOLD are returned.
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
        results = []
        for raw in items:
            # Must have been modified recently
            last_modified_str = raw.get("lastModified") or raw.get("updatedAt")
            if not last_modified_str:
                continue
            last_modified = datetime.fromisoformat(last_modified_str.replace("Z", "+00:00"))
            if last_modified < since:
                continue  # don't break — trending sort is not time-ordered

            # Skip watched orgs (already covered by Tier 1)
            author = (raw.get("author") or "").lower()
            if author in watched_lower:
                continue

            # Skip derivative models (quantizations, merges, LoRAs)
            model_id = raw.get("modelId") or raw.get("id", "")
            if self._is_derivative(model_id):
                continue

            # Composite scoring
            score = self._compute_score(raw)
            if score < TIER2_SCORE_THRESHOLD:
                continue

            likes = raw.get("likes", 0)
            logger.debug(
                "Tier2 candidate: %s score=%d likes=%d",
                model_id, score, likes,
            )

            model = self._parse_model(raw, min_likes=0)
            if model is not None:
                results.append(model)
        return results

    # -------------------------------------------------------------------------
    # Scoring helpers
    # -------------------------------------------------------------------------

    @staticmethod
    def _is_derivative(model_id: str) -> bool:
        """Return True if model name looks like a quantization/merge/finetune."""
        name_lower = model_id.lower()
        return any(marker in name_lower for marker in DERIVATIVE_MARKERS)

    @staticmethod
    def _compute_score(raw: dict) -> int:
        """
        Composite importance score for Tier 2 models.
        Weights:
          +40  has arxiv paper reference
          +30  likes >= 50
          +15  likes >= 15  (exclusive with the +30 above)
          +10  org account (author/model format)
          +10  downloads >= 10 000 in last 30 days
        Threshold for alert: 50
        """
        score = 0

        # ArXiv paper presence — strongest signal
        card_data = raw.get("cardData") or {}
        tags = raw.get("tags") or []
        has_arxiv = (
            any("arxiv" in str(v).lower() for v in card_data.values() if v)
            or any("arxiv" in t.lower() for t in tags)
        )
        if has_arxiv:
            score += 40

        # Likes
        likes = raw.get("likes", 0)
        if likes >= 50:
            score += 30
        elif likes >= 15:
            score += 15

        # Organization account (slash in modelId)
        model_id = raw.get("modelId") or raw.get("id", "")
        if "/" in model_id:
            score += 10

        # Downloads (30-day)
        downloads = raw.get("downloads", 0)
        if downloads >= 10_000:
            score += 10

        return score

    # -------------------------------------------------------------------------
    # Shared parser
    # -------------------------------------------------------------------------

    def _parse_model(self, raw: dict, min_likes: int) -> ModelResult | None:
        try:
            model_id = raw.get("modelId") or raw.get("id", "")
            if not model_id:
                return None

            likes = raw.get("likes", 0)
            if likes < min_likes:
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
                likes=likes,
                downloads=raw.get("downloads", 0),
                created_at=created_at,
                url=url,
                author=author,
                description=description,
            )
        except Exception as exc:
            logger.debug("Failed to parse HF model %s: %s", raw.get("modelId", "?"), exc)
            return None
