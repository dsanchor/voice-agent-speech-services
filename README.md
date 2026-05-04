# Voice Agent — Azure Speech Services + Foundry Responses API

A real-time voice-enabled web application that lets users have continuous conversations with an AI agent. The browser provides all configuration (Azure credentials, Foundry settings, TTS/STT preferences) via a configuration page, then streams microphone audio over a WebSocket; a FastAPI backend performs **live speech-to-text** via the Azure Speech SDK (`PushAudioInputStream` + `start_continuous_recognition`), forwards final transcripts to an **Azure AI Foundry agent**, and returns **sentence-chunked TTS** audio back to the browser — all over a single persistent connection. Deployed to Azure Container Apps with managed identity — no API keys or env vars needed.

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

1. User navigates to the **configuration page** (`static/index.html`), enters or loads Azure and Foundry settings, and proceeds to the **voice session page**.
2. The browser opens a WebSocket connection and sends a `config` message with all Azure/Foundry credentials and settings.
3. The backend creates per-session `SpeechService` and `AgentClient` instances from the config.
4. **Optional:** If a proactive greeting is configured, the backend synthesizes the greeting text to TTS and streams it to the client (via `greeting` message), which plays before the user speaks.
5. User clicks **Start Microphone** — the browser opens a `MediaRecorder` capturing 16 kHz 16-bit mono PCM and sends a `start_mic` message.
6. Audio chunks are continuously base64-encoded and streamed to the server as `audio` messages.
7. The backend writes chunks into a `PushAudioInputStream`; the Azure Speech SDK recognizer fires:
   - **`recognizing`** events → partial transcript pushed to the client in real time.
   - **`recognized`** events → final transcript triggers the agent pipeline.
8. The final transcript is sent to the **Foundry agent** (Responses API). Conversation context is maintained via `previous_response_id`.
9. The agent's reply is split into sentences and synthesised to MP3 via **Azure Speech TTS** — each sentence is sent as a `tts_audio` message as soon as it's ready (low time-to-first-audio).
10. The browser decodes and queues audio chunks for gapless playback.
11. User can click **Stop Microphone** to pause recognition, or **Stop Speaking** (barge-in) to interrupt TTS playback mid-stream.

## UI

The application features a **two-page flow**:

### Configuration Page (`static/index.html`)
A settings form where users configure all connection parameters:
- **Azure Speech Region** — Region of the Speech Service (e.g. `swedencentral`)
- **Azure Speech Resource ID** — Full ARM resource ID of the Speech Service
- **Foundry Endpoint** — Foundry base endpoint (e.g. `https://my-foundry.services.ai.azure.com/api/projects`)
- **Foundry Project** — Project name in Foundry
- **Foundry Agent Name** — Name of the agent to invoke
- **Foundry API Version** — (default: `2025-03-01-preview`)
- **STT Language** — Default speech recognition language (default: `en-US`)
- **STT Locales** — Comma-separated list of supported locales
- **TTS Voice** — Azure TTS voice name (default: `en-US-AvaMultilingualNeural`)
- **TTS Output Format** — Audio format for TTS (default: `audio-16khz-32kbitrate-mono-mp3`)
- **Proactive Greeting** — Optional checkbox + text field to enable a greeting on session start
- **Load Config** — Button to load pre-built JSON from `config-samples/`

All settings are stored in browser localStorage and passed to the backend in the WebSocket `config` message.

### Voice Session Page (`static/voice.html`)
The real-time voice interaction interface:

| Element | Description |
|---------|-------------|
| **Start / Stop Microphone** | Toggle continuous mic streaming (button changes state) |
| **Stop Speaking** | Interrupts TTS playback immediately (barge-in) |
| **Clear Chat** | Resets conversation history and agent context |
| **Live Partial Transcript** | Shows in-progress recognition text in real time |
| **Chat History** | Scrollable log of user utterances and agent responses |
| **Connection Indicator** | Dot + label showing WebSocket connection status |

## WebSocket Protocol

All messages are JSON with a `type` field. Audio payloads are base64-encoded.

### Client → Server

| Type | Fields | Description |
|------|--------|-------------|
| `config` | `speech_region`, `speech_resource_id`, `foundry_endpoint`, `foundry_project`, `foundry_agent_name`, `foundry_api_version?`, `stt_language?`, `stt_locales?`, `tts_output_format?`, `tts_voice?` | Per-session configuration (sent once on connection); backend creates SpeechService and AgentClient from these values |
| `start_mic` | — | Begin continuous speech recognition |
| `audio` | `data` (base64 PCM) | Raw 16 kHz 16-bit mono audio chunk |
| `stop_mic` | — | Stop recognition, close audio stream |
| `stop_speaking` | — | Interrupt TTS playback (barge-in) |
| `greeting` | `text` | Send text for TTS synthesis without invoking the agent (for proactive greetings) |
| `clear_chat` | — | Reset conversation (`previous_response_id` cleared) |

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

# 4. Authenticate with Azure
az login

# 5. Run the backend
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

Open <http://localhost:8000> in your browser. You'll see the configuration page where you can:
- **Manually enter** your Azure and Foundry settings, or
- **Load a sample config** from `config-samples/` (e.g. `all-fields.json` or `mandatory-only.json`)

Once configured, proceed to the voice session page to start speaking.

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
./infra/deploy.sh \
  --resource-group rg-voice-agent \
  --name voice-agent \
  --image ghcr.io/dsanchor/voice-agent-speech-services:latest \
  --speech-resource-id "/subscriptions/.../Microsoft.CognitiveServices/accounts/my-speech" \
  --foundry-resource-id "/subscriptions/.../Microsoft.MachineLearningServices/workspaces/my-foundry" \
  --location swedencentral \
  --env-name voice-agent-env
```

> **Note:** The app no longer reads environment variables. All configuration (Azure credentials, Foundry settings, TTS/STT preferences) is provided by the browser via the WebSocket `config` message. The `deploy.sh` script still provisions the necessary infrastructure and role assignments so the managed identity can authenticate to Azure services.

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
│   ├── config.py                 # Dataclass settings (loads from WebSocket config message)
│   └── requirements.txt          # Python dependencies
├── static/
│   ├── index.html                # Configuration page (form + config loader)
│   ├── voice.html                # Voice session page (mic, transcript, chat history)
│   ├── css/
│   │   └── style.css             # Dark theme styles
│   └── js/
│       ├── config.js             # Config page logic + localStorage persistence
│       ├── voice.js              # WebSocket, mic capture, audio playback, barge-in
│       └── audio.js              # MicCapture (16kHz PCM) + AudioPlayer (MP3 decode)
├── config-samples/
│   ├── all-fields.json           # Example with all optional fields
│   ├── mandatory-only.json       # Example with only required fields
│   ├── quick-demo.json           # Quick-start configuration
│   └── hosted-demo.json          # Demo configuration for hosted deployments
├── infra/
│   └── deploy.sh                 # One-command Azure deployment script
├── Dockerfile                    # Multi-stage build (Python 3.11-slim)
└── README.md
```

## License

Internal project.
