# Voice Agent — Azure Speech Services + Foundry Responses API

A voice-enabled web application that lets users speak to an AI agent. The browser captures audio, a FastAPI backend transcribes it with **Azure Speech Services (STT)**, sends the text to an **Azure AI Foundry agent via the Responses API**, then synthesises the reply back to speech **(TTS)** and streams it to the browser. Deployed to Azure Container Apps with managed identity — no API keys in config.

## Architecture

```
┌─────────────┐         ┌──────────────────────┐         ┌───────────────────────┐
│   Browser   │◄───────►│  Azure Container Apps │◄───────►│  Azure Speech Service │
│  (HTML/JS)  │  HTTP   │  FastAPI (uvicorn)    │  SDK    │  STT & TTS            │
│  Mic + WAV  │  + WS   │  Managed Identity     │         │                       │
└─────────────┘         └──────────┬───────────┘         └───────────────────────┘
                                   │
                                   │ HTTPS (Bearer token)
                                   ▼
                        ┌───────────────────────┐
                        │  Azure AI Foundry     │
                        │  Responses API        │
                        │  (Agent)              │
                        └───────────────────────┘
```

- **Frontend** — Static HTML/JS served by FastAPI. Captures 16 kHz mono PCM from the microphone, wraps it in WAV, and sends it over a WebSocket.
- **Backend** — FastAPI app orchestrates the STT → Agent → TTS pipeline over a single persistent WebSocket connection per client.
- **Identity** — System-assigned managed identity with least-privilege roles: `Cognitive Services Speech User` on the Speech resource and `Azure AI User` on the Foundry resource.
- **CI/CD** — GitHub Actions builds and pushes container images to GitHub Packages (GHCR) on every push to `main`.

## How It Works

1. User taps the record button; the browser captures audio at 16 kHz 16-bit mono PCM.
2. On stop, the JS client wraps the PCM in a WAV header, base64-encodes it, and sends a JSON message over the WebSocket.
3. The backend sends the audio to **Azure Speech STT** (via the Speech SDK with managed-identity token auth).
4. The transcribed text is forwarded to the **Foundry agent** using the Responses API. Conversation context is maintained via `previous_response_id`.
5. The agent's reply text is synthesised to MP3 using **Azure Speech TTS**.
6. The MP3 bytes are base64-encoded and returned to the browser, which decodes and plays them.

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

## Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `AZURE_SPEECH_REGION` | ✅ | — | Azure region of the Speech Service (e.g. `swedencentral`) |
| `AZURE_SPEECH_RESOURCE_ID` | ✅ | — | Full ARM resource ID of the Speech Service |
| `FOUNDRY_ENDPOINT` | ✅ | — | Foundry project endpoint (e.g. `https://<project>.services.ai.azure.com`) |
| `FOUNDRY_AGENT_NAME` | ✅ | — | Name of the Foundry agent to invoke |
| `STT_LANGUAGE` | ❌ | `en-US` | Speech recognition language/locale |
| `TTS_OUTPUT_FORMAT` | ❌ | `audio-16khz-32kbitrate-mono-mp3` | TTS audio output format |

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
export FOUNDRY_ENDPOINT="https://my-project.services.ai.azure.com"
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
│   ├── main.py                   # FastAPI app, WebSocket endpoint, lifespan
│   ├── speech_service.py         # Azure Speech SDK wrapper (STT + TTS)
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
