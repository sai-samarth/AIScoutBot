from abc import ABC, abstractmethod
from datetime import datetime

from bot.models import ModelResult


class BaseSource(ABC):

    @abstractmethod
    async def scan(self, since: datetime) -> list[ModelResult]:
        """
        Fetch models created or updated after `since`.
        Must be idempotent — may return duplicates across calls;
        deduplication is handled by db.py, not here.
        """
        ...

    @property
    @abstractmethod
    def source_name(self) -> str:
        """Human-readable identifier used in log messages."""
        ...
