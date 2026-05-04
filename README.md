# Voice Agent — Azure Speech Services + Foundry Responses API

A real-time voice-enabled web application that lets users have continuous conversations with an AI agent. The browser streams microphone audio over a WebSocket; a FastAPI backend performs **live speech-to-text** via the Azure Speech SDK (`PushAudioInputStream` + `start_continuous_recognition`), forwards final transcripts to an **Azure AI Foundry agent**, and returns **sentence-chunked TTS** audio back to the browser — all over a single persistent connection. Deployed to Azure Container Apps with managed identity — no API keys in config.

## Architecture

```
┌──────────────────┐            WebSocket (wss://)            ┌──────────────────────────┐
│     Browser      │◄────────────────────────────────────────►│   Azure Container Apps   │
│                  │  start_mic / audio / stop_mic / ...       │   FastAPI  (uvicorn)     │
│  MediaRecorder   │  recognizing / recognized / tts_audio     │   Managed Identity       │
│  16 kHz PCM      │                                          │                          │
└──────────────────┘                                          └────────┬────────┬────────┘
                                                                       │        │
                                                            SDK        │        │  HTTPS
                                                   (PushAudioStream)   │        │  (Bearer)
                                                                       ▼        ▼
                                                  ┌────────────────────────┐  ┌────────────────────┐
                                                  │  Azure Speech Service  │  │  Azure AI Foundry  │
                                                  │  • Continuous STT      │  │  Responses API     │
                                                  │  • Sentence-chunked TTS│  │  (Agent)           │
                                                  └────────────────────────┘  └────────────────────┘
```

### Key Design Decisions

| Concern | Approach |
|---------|----------|
| **STT** | `PushAudioInputStream` fed with raw PCM chunks → `start_continuous_recognition()` for real-time partial + final results |
| **Agent** | Foundry Responses API with `previous_response_id` for multi-turn context |
| **TTS** | Sentence-split regex → synthesise each sentence independently → stream chunks to client as they complete |
| **Auth** | `DefaultAzureCredential` / system-assigned managed identity, token auto-refresh via `TokenManager` |
| **Transport** | Single WebSocket per client; JSON control messages + base64 audio payloads |

## How It Works

1. User clicks **Start Microphone** — the browser opens a `MediaRecorder` capturing 16 kHz 16-bit mono PCM and sends a `start_mic` message.
2. Audio chunks are continuously base64-encoded and streamed to the server as `audio` messages.
3. The backend writes chunks into a `PushAudioInputStream`; the Azure Speech SDK recognizer fires:
   - **`recognizing`** events → partial transcript pushed to the client in real time.
   - **`recognized`** events → final transcript triggers the agent pipeline.
4. The final transcript is sent to the **Foundry agent** (Responses API). Conversation context is maintained via `previous_response_id`.
5. The agent's reply is split into sentences and synthesised to MP3 via **Azure Speech TTS** — each sentence is sent as a `tts_audio` message as soon as it's ready (low time-to-first-audio).
6. The browser decodes and queues audio chunks for gapless playback.
7. User can click **Stop Microphone** at any time to pause recognition, or **Stop Speaking** to interrupt TTS playback mid-stream.

## UI

The single-page interface (`static/index.html`) provides:

| Element | Description |
|---------|-------------|
| **Start / Stop Microphone** | Toggle continuous mic streaming (button changes state) |
| **Stop Speaking** | Interrupts TTS playback immediately |
| **Clear Chat** | Resets conversation history and agent context |
| **Live Partial Transcript** | Shows in-progress recognition text in real time |
| **Chat History** | Scrollable log of user utterances and agent responses |
| **Connection Indicator** | Dot + label showing WebSocket connection status |

## WebSocket Protocol

All messages are JSON with a `type` field. Audio payloads are base64-encoded.

### Client → Server

| Type | Fields | Description |
|------|--------|-------------|
| `start_mic` | — | Begin continuous speech recognition |
| `audio` | `data` (base64 PCM) | Raw 16 kHz 16-bit mono audio chunk |
| `stop_mic` | — | Stop recognition, close audio stream |
| `stop_speaking` | — | Interrupt TTS playback |
| `clear_chat` | — | Reset conversation (`previous_response_id` cleared) |
| `config` | `stt_language?`, `tts_voice?` | Update per-session STT/TTS settings |

### Server → Client

| Type | Fields | Description |
|------|--------|-------------|
| `recognizing` | `text` | Partial (interim) STT transcript |
| `recognized` | `text` | Final STT transcript |
| `agent_response` | `text` | Full agent reply text |
| `tts_audio` | `data` (base64), `format` | One sentence of synthesised audio (MP3) |
| `tts_end` | — | All TTS audio for this turn has been sent |
| `status` | `message` | Informational status (e.g. "Listening…", "Thinking…") |
| `error` | `message` | Error description |

## Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `AZURE_SPEECH_REGION` | ✅ | — | Azure region of the Speech Service (e.g. `swedencentral`) |
| `AZURE_SPEECH_RESOURCE_ID` | ✅ | — | Full ARM resource ID of the Speech Service |
| `FOUNDRY_ENDPOINT` | ✅ | — | Foundry base endpoint (e.g. `https://my-foundry.services.ai.azure.com/api/projects`) |
| `FOUNDRY_PROJECT` | ✅ | — | Foundry project name (e.g. `my-project`) |
| `FOUNDRY_AGENT_NAME` | ✅ | — | Name of the Foundry agent to invoke |
| `FOUNDRY_AGENT_VERSION` | ❌ | `1` | Version of the Foundry agent |
| `FOUNDRY_API_VERSION` | ❌ | `2025-03-01-preview` | Responses API version |
| `STT_LANGUAGE` | ❌ | `en-US` | Default speech recognition language/locale |
| `STT_LOCALES` | ❌ | `en-US` | Comma-separated locales for multi-language support |
| `TTS_VOICE` | ❌ | `en-US-AvaMultilingualNeural` | Azure TTS voice name |
| `TTS_OUTPUT_FORMAT` | ❌ | `audio-16khz-32kbitrate-mono-mp3` | TTS audio output format |

## Local Development

```bash
# 1. Clone
git clone https://github.com/dsanchor/voice-agent-speech-services.git
cd voice-agent-speech-services

# 2. Create virtual environment
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate

# 3. Install dependencies
pip install -r app/requirements.txt

# 4. Configure environment
cp .env.example .env
# Edit .env with your Azure resource values

# 5. Run (requires Azure login for DefaultAzureCredential)
az login
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

Open <http://localhost:8000> in your browser.

> **Note:** Local development uses `DefaultAzureCredential`, which will pick up your `az login` session, VS Code credentials, or environment variables. Ensure your identity has the required roles on the Speech and Foundry resources.

## Deployment

### CI/CD — GitHub Actions

The workflow (`.github/workflows/build-and-push.yml`) triggers on every push to `main`:

1. Checks out the repo.
2. Logs in to GHCR (`ghcr.io`).
3. Builds the Docker image (multi-stage, Python 3.11-slim).
4. Pushes with tags `latest` and the full commit SHA.

Pull requests build the image but do **not** push.

### Infrastructure — `deploy.sh`

The script at `infra/deploy.sh` provisions and deploys the full stack in a single command:

```bash
export AZURE_SPEECH_REGION="swedencentral"
export AZURE_SPEECH_RESOURCE_ID="/subscriptions/.../Microsoft.CognitiveServices/accounts/my-speech"
export FOUNDRY_ENDPOINT="https://my-foundry.services.ai.azure.com/api/projects"
export FOUNDRY_PROJECT="my-project"
export FOUNDRY_AGENT_NAME="my-agent"

./infra/deploy.sh \
  --resource-group rg-voice-agent \
  --name voice-agent \
  --image ghcr.io/dsanchor/voice-agent-speech-services:latest \
  --speech-resource-id "$AZURE_SPEECH_RESOURCE_ID" \
  --foundry-resource-id "/subscriptions/.../Microsoft.MachineLearningServices/workspaces/my-foundry" \
  --location swedencentral \
  --env-name voice-agent-env
```

#### What it provisions

| Resource | Purpose |
|----------|---------|
| Resource Group | Logical container for all resources |
| Container Apps Environment | Hosting environment for the container |
| Container App (system-assigned MI) | Runs the application with external ingress on port 8000 |
| Role: `Cognitive Services Speech User` | Grants the MI access to the Speech Service for STT/TTS |
| Role: `Azure AI User` | Grants the MI access to the Foundry resource for the Responses API |

#### Script flags

| Flag | Description |
|------|-------------|
| `--resource-group` | Azure resource group name |
| `--name` | Container App name |
| `--image` | Container image reference (e.g. `ghcr.io/org/repo:tag`) |
| `--speech-resource-id` | Full ARM resource ID of the Speech Service |
| `--foundry-resource-id` | Full ARM resource ID of the AI Foundry resource |
| `--location` | Azure region (e.g. `swedencentral`) |
| `--env-name` | Container Apps environment name |

## Project Structure

```
voice-agent-speech-services/
├── .github/
│   └── workflows/
│       └── build-and-push.yml    # CI/CD: build & push to GHCR
├── app/
│   ├── __init__.py
│   ├── main.py                   # FastAPI app, WebSocket endpoint, streaming STT loop
│   ├── speech_service.py         # Azure Speech SDK: continuous STT + sentence-chunked TTS
│   ├── agent_client.py           # Foundry Responses API client
│   ├── token_manager.py          # Managed-identity token cache with auto-refresh
│   ├── config.py                 # Dataclass settings from env vars
│   └── requirements.txt          # Python dependencies
├── static/
│   ├── index.html                # Single-page voice UI
│   ├── css/
│   │   └── style.css             # Styles
│   └── js/
│       └── voice.js              # Mic capture, WebSocket transport, audio playback
├── infra/
│   └── deploy.sh                 # One-command Azure deployment script
├── .env.example                  # Template for local env vars
├── Dockerfile                    # Multi-stage build (Python 3.11-slim)
└── README.md
```

## License

Internal project.
