from pydantic import BaseModel, field_validator
import yaml
from pathlib import Path
import zoneinfo


class ScheduleConfig(BaseModel):
    times: list[str]
    timezone: str
    scan_lookback_hours: int

    @field_validator("times")
    @classmethod
    def validate_times(cls, v: list[str]) -> list[str]:
        for t in v:
            parts = t.split(":")
            if len(parts) != 2 or not parts[0].isdigit() or not parts[1].isdigit():
                raise ValueError(f"Invalid time format: {t!r} — expected HH:MM")
        return v

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, v: str) -> str:
        try:
            zoneinfo.ZoneInfo(v)
        except zoneinfo.ZoneInfoNotFoundError:
            raise ValueError(f"Unknown timezone: {v!r}")
        return v


class HuggingFaceConfig(BaseModel):
    enabled: bool
    pipeline_tags: list[str]
    min_likes: int
    watched_orgs: list[str] = []
    trending_lookback_hours: int = 24
    trending_creation_days: int = 7
    scan_interval_minutes: int = 15


class SourcesConfig(BaseModel):
    huggingface: HuggingFaceConfig


class WhatsAppConfig(BaseModel):
    target_groups: list[str]


class GatewayConfig(BaseModel):
    port: int
    bot_incoming_url: str


class BotConfig(BaseModel):
    port: int


class AgentConfig(BaseModel):
    enabled: bool = False
    max_steps: int = 5
    timeout_seconds: int = 30
    response_max_chars: int = 900


class LiteLLMConfig(BaseModel):
    base_url: str
    model: str
    api_key: str | None = None


class AppConfig(BaseModel):
    schedule: ScheduleConfig
    sources: SourcesConfig
    whatsapp: WhatsAppConfig
    gateway: GatewayConfig
    bot: BotConfig
    litellm: LiteLLMConfig
    agent: AgentConfig = AgentConfig()


def load_config(path: str = None) -> AppConfig:
    if path is None:
        # Walk up from this file to find config.yaml at repo root
        here = Path(__file__).parent
        candidates = [here.parent / "config.yaml", here / "config.yaml", Path("config.yaml")]
        for p in candidates:
            if p.exists():
                path = str(p)
                break
        else:
            raise FileNotFoundError("config.yaml not found")
    raw = yaml.safe_load(Path(path).read_text())
    return AppConfig(**raw)


config: AppConfig = load_config()
