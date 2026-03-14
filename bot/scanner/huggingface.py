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


class HuggingFaceSource(BaseSource):

    def __init__(self, cfg: HuggingFaceConfig) -> None:
        self._cfg = cfg
        self._token = os.environ.get("HF_TOKEN")

    @property
    def source_name(self) -> str:
        return "HuggingFace"

    async def scan(self, since: datetime) -> list[ModelResult]:
        results: list[ModelResult] = []
        headers = {}
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"

        async with httpx.AsyncClient(headers=headers, timeout=30.0) as client:
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

                # Results are sorted newest-first; once we're past `since`, stop
                if last_modified < since:
                    stop_early = True
                    break

                model = self._parse_model(raw)
                if model is not None:
                    results.append(model)

            if stop_early or len(items) < PAGE_SIZE:
                break

            # Polite delay between pages to avoid hammering the API
            await asyncio.sleep(0.5)

        return results

    def _parse_model(self, raw: dict) -> ModelResult | None:
        try:
            model_id = raw["modelId"] or raw.get("id", "")
            if not model_id:
                return None

            last_modified_str = raw.get("lastModified") or raw.get("updatedAt", "")
            created_at = datetime.fromisoformat(
                last_modified_str.replace("Z", "+00:00")
            ) if last_modified_str else datetime.now(timezone.utc)

            likes = raw.get("likes", 0)
            if likes < self._cfg.min_likes:
                return None

            author = raw.get("author") or model_id.split("/")[0]
            pipeline_tag = raw.get("pipeline_tag") or "unknown"
            url = f"https://huggingface.co/{model_id}"

            # Use first 200 chars of model card excerpt if available
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
