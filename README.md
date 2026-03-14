# AIScoutBot

A self-hosted WhatsApp bot that monitors HuggingFace for important AI model releases and sends immediate alerts to your WhatsApp groups.

## How it works

The bot uses a two-tier detection system that runs every 15 minutes:

- **Tier 1 — Watched orgs**: Scans a curated list of major AI labs (Meta, Google, Mistral, Qwen, DeepSeek, NVIDIA, etc.) for any new model uploads. Filtered to LLMs, multimodal, image/video/audio generation, and speech models.
- **Tier 2 — Trending**: Fetches HuggingFace's top trending models, filtered to those created in the last 7 days and excluding derivatives (quantizations, merges, LoRAs). Catches important releases from new or unlisted labs.

Models are deduplicated via SQLite — each model is only alerted once.

## Architecture

Two services communicate over local HTTP:

- **`gateway/`** — Node.js service using [Baileys](https://github.com/whiskeysockets/baileys) to maintain a WhatsApp Web session. Exposes `POST /send` and `GET /groups`.
- **`bot/`** — Python/FastAPI service that runs the scheduler, scans HuggingFace, deduplicates via SQLite, formats alerts, and delivers them via the gateway.

## Requirements

- Docker + Docker Compose
- A spare WhatsApp account/number for the bot

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

Edit `.env` and add your HuggingFace token (optional but recommended — raises rate limit from 100 to 5000 req/hr):

```
HF_TOKEN=hf_your_token_here
```

Get a free read-only token at https://huggingface.co/settings/tokens.

Edit `config.yaml` to set your target WhatsApp group and watched orgs:

```yaml
sources:
  huggingface:
    watched_orgs:
      - meta-llama
      - google
      - mistralai
      # ... add or remove orgs as needed
    scan_interval_minutes: 15    # how often to scan
    trending_lookback_hours: 24  # Tier 1 lookback (Tier 2 uses 7 days)

whatsapp:
  target_groups:
    - "Your Group Name"          # substring match, case-insensitive
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
curl -X POST http://localhost:8000/trigger/alert

# Fresh — re-posts already-seen models without updating the DB (for testing)
curl -X POST "http://localhost:8000/trigger/alert?fresh=true"
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
| `sources.huggingface.trending_lookback_hours` | Tier 1 lookback window in hours (default `24`). Tier 2 always uses 7 days |
| `sources.huggingface.pipeline_tags` | Pipeline tags used by the manual `/trigger` endpoint |
| `sources.huggingface.min_likes` | Minimum likes for the manual `/trigger` endpoint |
| `whatsapp.target_groups` | Group name substrings to send alerts to |
| `gateway.port` | Port for the gateway HTTP API (default `3001`) |
| `bot.port` | Port for the bot HTTP API (default `8000`) |
