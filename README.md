# AIScoutBot

A self-hosted WhatsApp bot that monitors HuggingFace for important AI model releases and sends immediate alerts to your WhatsApp groups. Reply to any alert or @mention the bot to ask questions about models.

## How it works

The bot uses a two-tier detection system that runs every 15 minutes:

- **Tier 1 — Watched orgs**: Scans a curated list of major AI labs (Meta, Google, Mistral, Qwen, DeepSeek, NVIDIA, etc.) for any new model uploads. Filtered to LLMs, multimodal, image/video/audio generation, and speech models.
- **Tier 2 — Trending**: Fetches HuggingFace's top trending models, filtered to those created within `trending_creation_days` (default 3) and excluding derivatives (quantizations, merges, LoRAs). Catches important releases from new or unlisted labs.

Models are deduplicated via SQLite — each model is only alerted once.

Each model is sent as a separate WhatsApp message for easy replying.

## Q&A Agent

Reply to any bot message or @mention the bot to ask questions about AI models. The agent has three tools:

- **HuggingFace model lookup** — fetches full metadata (parameters, architecture, license, tags)
- **Web search** — DuckDuckGo search for benchmarks, comparisons, and news
- **Webpage fetch** — reads model cards, arXiv abstracts, and linked pages

The agent's WhatsApp JID is auto-discovered at startup — no manual configuration needed.

## Architecture

Two services communicate over local HTTP:

- **`gateway/`** — Node.js service using [Baileys](https://github.com/whiskeysockets/baileys) to maintain a WhatsApp Web session. Exposes `POST /send`, `GET /groups`, `GET /me`, `GET /healthz`.
- **`bot/`** — Python/FastAPI service that runs the scheduler, scans HuggingFace, deduplicates via SQLite, formats alerts, delivers them via the gateway, and handles the Q&A agent.

## Requirements

- Docker + Docker Compose
- A spare WhatsApp account/number for the bot
- An OpenAI-compatible LLM endpoint (for the Q&A agent)

## Setup

### 1. Clone the repo

```bash
git clone https://github.com/sai-samarth/AIScoutBot.git
cd AIScoutBot
```

### 2. Configure

```bash
cp .env.example .env
```

Edit `.env`:

```
# Optional — raises HuggingFace rate limit from 100 to 5000 req/hr
HF_TOKEN=hf_your_token_here

# API key for your LLM endpoint (if required)
LITELLM_API_KEY=your_key_here
```

Edit `config.yaml`:

```yaml
sources:
  huggingface:
    watched_orgs:
      - meta-llama
      - google
      - mistralai
      # ... add or remove orgs as needed
    scan_interval_minutes: 15     # how often to scan
    trending_creation_days: 3     # Tier 2 creation window in days

whatsapp:
  target_groups:
    - "Your Group Name"           # substring match, case-insensitive

agent:
  enabled: true
  max_steps: 5
  timeout_seconds: 30
  response_max_chars: 900

litellm:
  base_url: "https://api.openai.com/v1"   # any OpenAI-compatible endpoint
  model: "gpt-4o"
```

### 3. Start

```bash
./start.sh
```

### 4. Link WhatsApp

On first run the gateway needs to be linked to your WhatsApp account:

```bash
docker logs aiscoutbot-gateway-1 -f
```

A QR code will appear in the terminal. Open WhatsApp on your phone → **Linked Devices** → **Link a Device** → scan the QR.

Once linked you'll see `WhatsApp connected` in the logs. The session is persisted in a Docker volume — you won't need to scan again unless you explicitly log out.

## Usage

### Start / Stop

```bash
./start.sh             # start containers
./start.sh --rebuild   # rebuild images then start (after code changes)
./stop.sh              # stop and remove containers
```

### Manually trigger an alert scan

```bash
# Normal — only posts models not yet seen
curl -X POST http://localhost:8000/trigger

# Fresh — re-posts already-seen models without updating the DB (for testing)
curl -X POST "http://localhost:8000/trigger?fresh=true"
```

### Check which groups the bot can see

```bash
curl http://localhost:3001/groups
```

Use the `subject` field to set `target_groups` in `config.yaml`.

### Check gateway connection status

```bash
curl http://localhost:3001/healthz
```

### API docs (bot service)

```
http://localhost:8000/docs
```

## Configuration reference (`config.yaml`)

| Key | Description |
|-----|-------------|
| `sources.huggingface.watched_orgs` | HuggingFace org IDs to monitor (Tier 1) |
| `sources.huggingface.scan_interval_minutes` | How often to run the alert scan (default `15`) |
| `sources.huggingface.trending_lookback_hours` | Tier 1 lookback window in hours (default `24`) |
| `sources.huggingface.trending_creation_days` | Tier 2 creation window in days (default `3`) |
| `whatsapp.target_groups` | Group name substrings to send alerts to |
| `agent.enabled` | Enable/disable the Q&A agent (default `true`) |
| `agent.max_steps` | Max tool-call iterations per agent request (default `5`) |
| `agent.timeout_seconds` | Agent timeout in seconds (default `30`) |
| `agent.response_max_chars` | Max response length in characters (default `900`) |
| `litellm.base_url` | OpenAI-compatible LLM endpoint URL |
| `litellm.model` | Model ID to use for the agent |
| `gateway.port` | Port for the gateway HTTP API (default `3001`) |
| `bot.port` | Port for the bot HTTP API (default `8000`) |
