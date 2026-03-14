from datetime import datetime
from bot.models import ModelResult

MAX_MODELS_PER_DIGEST = 20

# Map pipeline_tag → display label and emoji
_CATEGORY_MAP = {
    "text-generation": ("📝 *Text Generation*", 0),
    "image-text-to-text": ("👁️ *Vision / Multimodal*", 1),
    "text-to-image": ("🎨 *Text to Image*", 2),
    "automatic-speech-recognition": ("🎤 *Speech Recognition*", 3),
    "text-to-speech": ("🔊 *Text to Speech*", 4),
}
_DEFAULT_CATEGORY = ("🤖 *Other*", 99)


def format_digest(
    models: list[ModelResult],
    scan_time: datetime,
    lookback_hours: int,
) -> str:
    """
    Returns a WhatsApp-formatted digest string, or empty string if models is empty.
    Uses *bold* and _italic_ which WhatsApp renders natively.
    Caps output at MAX_MODELS_PER_DIGEST models total.
    """
    if not models:
        return ""

    # Cap total models
    truncated = len(models) > MAX_MODELS_PER_DIGEST
    models = models[:MAX_MODELS_PER_DIGEST]

    # Group by pipeline_tag, preserving category display order
    categories: dict[str, list[ModelResult]] = {}
    for m in models:
        categories.setdefault(m.pipeline_tag, []).append(m)

    date_str = scan_time.strftime("%-d %b %Y, %H:%M UTC")
    total = len(models)
    suffix = "+" if truncated else ""

    lines = [
        f"*AI Model Scout* — {date_str}",
        f"_Last {lookback_hours}h | {total}{suffix} new models_",
        "",
    ]

    # Sort categories by their defined display order
    def sort_key(tag: str) -> int:
        return _CATEGORY_MAP.get(tag, _DEFAULT_CATEGORY)[1]

    for tag in sorted(categories.keys(), key=sort_key):
        label, _ = _CATEGORY_MAP.get(tag, _DEFAULT_CATEGORY)
        tag_models = categories[tag]
        lines.append(f"{label} ({len(tag_models)})")

        for m in tag_models:
            lines.append(f"• {m.model_id} — ❤️ {m.likes:,}")
            lines.append(f"  {m.url}")
            if m.description:
                lines.append(f"  _{m.description[:120]}_")

        lines.append("")

    if truncated:
        lines.append(f"_...and more. Visit https://huggingface.co/models for the full list._")
        lines.append("")

    lines.append("_Reply to any model name for details_")

    return "\n".join(lines)


def format_alert(
    models: list[ModelResult],
    now: datetime,
    tier_labels: dict[str, str],
) -> str:
    """
    Compact immediate-alert format for Tier 1/2 models.
    tier_labels maps model_id -> human label e.g. "Watched: meta-llama" or "Trending".
    """
    if not models:
        return ""

    date_str = now.strftime("%-d %b %Y, %H:%M UTC")
    lines = [
        f"*New AI Model Alert* — {date_str}",
        "",
    ]

    for m in models:
        label = tier_labels.get(m.model_id, "")
        tier_note = f" | _{label}_" if label else ""
        lines.append(f"• *{m.model_id}*{tier_note}")
        lines.append(f"  ❤️ {m.likes:,}  {m.pipeline_tag}")
        lines.append(f"  {m.url}")
        if m.description:
            lines.append(f"  _{m.description[:120]}_")
        lines.append("")

    return "\n".join(lines).rstrip()
