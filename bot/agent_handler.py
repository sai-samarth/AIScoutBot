import asyncio
import logging
import os
import re

from smolagents import ToolCallingAgent, OpenAIServerModel, DuckDuckGoSearchTool, VisitWebpageTool

from bot.config import config
from bot.db import lookup_sent_message
from bot.models import IncomingMessage
from bot.sender import send_text_with_tracking
from bot.tools import HFModelLookupTool

logger = logging.getLogger(__name__)

BOT_JID = os.environ.get("BOT_JID", "")
BOT_LID = ""  # auto-populated at startup from gateway /me

SYSTEM_INSTRUCTIONS = (
    "You are a helpful AI model scout assistant in a WhatsApp group. "
    "You answer questions about AI/ML models, especially those on HuggingFace. "
    "Keep answers concise. "
    "Use *bold* for emphasis and _italic_ for model names. Do NOT use markdown headers, "
    "triple backticks, or bullet points with dashes. "
    "When discussing a specific HuggingFace model, always include its URL."
)

TIMEOUT_MSG = "Sorry, I took too long thinking about that. Please try again with a simpler question."
ERROR_MSG = "Sorry, something went wrong while processing your question. Please try again later."

# Shared across requests (stateless)
_model = None
_tools = None


def _get_model_and_tools():
    global _model, _tools
    if _model is None:
        api_key = config.litellm.api_key or os.environ.get("LITELLM_API_KEY", "no-key")
        _model = OpenAIServerModel(
            model_id=config.litellm.model,
            api_base=config.litellm.base_url,
            api_key=api_key,
        )
        _tools = [HFModelLookupTool(), DuckDuckGoSearchTool(), VisitWebpageTool()]
    return _model, _tools


async def should_activate(msg: IncomingMessage) -> tuple[bool, dict | None]:
    """Check if this message should trigger the agent."""
    if msg.quotedMessageId:
        record = await lookup_sent_message(msg.quotedMessageId)
        if record is not None:
            return True, record

    if (BOT_JID and BOT_JID in msg.mentionedJids) or \
       (BOT_LID and BOT_LID in msg.mentionedJids):
        return True, None

    return False, None


def build_task_prompt(msg: IncomingMessage, sent_record: dict | None) -> str:
    """Build the prompt for the agent."""
    parts = [SYSTEM_INSTRUCTIONS, ""]

    if msg.quotedText:
        parts.append(f"The message being replied to said: {msg.quotedText[:300]}")

    if sent_record and sent_record.get("model_ids"):
        model_ids = sent_record["model_ids"]
        parts.append(
            f"Context: The user is replying to a message about these models: {', '.join(model_ids)}. "
            "Use hf_model_lookup to get details if needed."
        )

    parts.append(f"User question: {msg.text}")
    return "\n".join(parts)


def _run_agent_sync(task: str) -> str:
    """Run the agent synchronously (called via asyncio.to_thread)."""
    model, tools = _get_model_and_tools()
    agent = ToolCallingAgent(
        model=model,
        tools=tools,
        max_steps=config.agent.max_steps,
        verbosity_level=0,
    )
    result = agent.run(task)
    return str(result)


def format_for_whatsapp(text: str, max_chars: int) -> str:
    """Clean up agent output for WhatsApp."""
    # Remove markdown headers
    text = re.sub(r"^#{1,6}\s+", "", text, flags=re.MULTILINE)
    # Remove triple backtick blocks — keep inner content
    text = re.sub(r"```[\s\S]*?```", lambda m: m.group(0).strip("`").strip(), text)
    # Remove single backticks
    text = text.replace("`", "")
    # Convert markdown links to text (URL)
    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r"\1 (\2)", text)
    # Collapse multiple blank lines
    text = re.sub(r"\n{3,}", "\n\n", text)

    text = text.strip()
    if len(text) <= max_chars:
        return text

    truncated = text[:max_chars]
    last_period = truncated.rfind(".")
    if last_period > max_chars * 0.5:
        return truncated[: last_period + 1].strip()
    last_space = truncated.rfind(" ")
    if last_space > 0:
        return truncated[:last_space].strip() + "..."
    return truncated.strip() + "..."


async def handle_incoming(msg: IncomingMessage) -> dict:
    """Main entry point for processing an incoming message."""
    if not config.agent.enabled:
        return {"ok": True, "agent": "disabled"}

    activated, sent_record = await should_activate(msg)
    if not activated:
        return {"ok": True, "agent": "not_triggered"}

    logger.info(
        "Agent activated: jid=%s sender=%s trigger=%s",
        msg.jid,
        msg.sender,
        "reply" if sent_record else "mention",
    )

    task = build_task_prompt(msg, sent_record)

    try:
        raw_answer = await asyncio.wait_for(
            asyncio.to_thread(_run_agent_sync, task),
            timeout=config.agent.timeout_seconds,
        )
        reply_text = format_for_whatsapp(raw_answer, config.agent.response_max_chars)
    except asyncio.TimeoutError:
        logger.warning("Agent timed out for jid=%s sender=%s", msg.jid, msg.sender)
        reply_text = TIMEOUT_MSG
    except Exception:
        logger.exception("Agent error for jid=%s sender=%s", msg.jid, msg.sender)
        reply_text = ERROR_MSG

    reply_model_ids = sent_record.get("model_ids") if sent_record else None

    try:
        await send_text_with_tracking(msg.jid, reply_text, reply_model_ids, "agent_reply")
    except Exception:
        logger.exception("Failed to send agent reply to jid=%s", msg.jid)

    return {"ok": True, "agent": "responded"}
