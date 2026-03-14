# AIScoutBot

A self-hosted WhatsApp bot that periodically scans HuggingFace for newly released AI models (LLMs, vision, multimodal, audio/TTS) and posts a formatted digest to your WhatsApp groups.

## Architecture

Two services communicate over local HTTP:

- **`gateway/`** — Node.js service using [Baileys](https://github.com/whiskeysockets/baileys) to maintain a WhatsApp Web session. Exposes `POST /send` and `GET /groups`.
- **`bot/`** — Python/FastAPI service that runs the scheduler, scans HuggingFace, deduplicates via SQLite, formats the digest, and delivers it via the gateway.

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

Edit `config.yaml` to set your target WhatsApp group name and schedule:

```yaml
schedule:
  times: ["08:00", "20:00"]   # 24h times, sent daily
  timezone: "Europe/London"
  scan_lookback_hours: 12

whatsapp:
  target_groups:
    - "Your Group Name"       # substring match, case-insensitive
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

### Manually trigger a scan

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
| `schedule.times` | List of `HH:MM` times to run the digest daily |
| `schedule.timezone` | Timezone for the schedule (e.g. `Europe/London`) |
| `schedule.scan_lookback_hours` | How far back each scan looks |
| `sources.huggingface.pipeline_tags` | HuggingFace pipeline tags to scan |
| `sources.huggingface.min_likes` | Minimum likes to include a model |
| `whatsapp.target_groups` | Group name substrings to send the digest to |
| `gateway.port` | Port for the gateway HTTP API (default `3001`) |
| `bot.port` | Port for the bot HTTP API (default `8000`) |

