from bot.models import ModelResult

MAX_MODELS_PER_ALERT = 20


def format_model(model: ModelResult) -> str:
    lines = [f"*{model.model_id}*", model.url]
    if model.description:
        lines.append(f"_{model.description[:120]}_")
    return "\n".join(lines)
