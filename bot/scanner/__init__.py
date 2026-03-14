from bot.config import AppConfig
from bot.scanner.base import BaseSource
from bot.scanner.huggingface import HuggingFaceSource


def get_all_sources(cfg: AppConfig) -> list[BaseSource]:
    """
    Factory: returns only enabled sources.
    Adding a new source = add one elif block here + new file in scanner/.
    """
    sources: list[BaseSource] = []
    if cfg.sources.huggingface.enabled:
        sources.append(HuggingFaceSource(cfg.sources.huggingface))
    return sources
