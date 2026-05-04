## Project Context

- **Project:** voice-agent-speech-services
- **User:** dsanchor
- **Stack:** Python, Azure Speech SDK (cognitive-services-speech-sdk), Azure Container Apps, Managed Identities, GitHub Actions
- **Description:** Voice-enabled web app giving voice to a Foundry agent using Azure Speech Services STT/TTS, calling agent via Responses API. Dockerized, deployed to Azure Container Apps with managed identities.

## Session Work (2026-05-04)

**Outcome:** Voice app MVP delivered successfully.

- Implemented token-based auth for Azure Speech SDK via `TokenManager`
- Integrated Responses API client with conversation continuity (`previous_response_id`)
- Built WAV audio transport over WebSocket (base64 JSON encoding)
- MP3 TTS output for browser compatibility
- Async blocking calls on thread pool to protect event loop
- **11 files created**

**Team Collaboration:** Worked with Ash on infrastructure; Ash's multi-stage Dockerfile and managed identity RBAC config eliminated auth complexity.

## Learnings

- Azure Speech SDK requires token-based auth for managed identity deployments (no `DefaultAzureCredential` support)
- WAV header wrapping enables direct `PushAudioInputStream` consumption without format negotiation
- MP3 output avoids browser-side PCM plumbing complexity
- Thread pool isolation critical for FastAPI + synchronous SDK calls
- Foundry Responses API URL pattern: `{FOUNDRY_ENDPOINT}/{FOUNDRY_PROJECT}/openai/responses?api-version=...` — endpoint and project are separate env vars (2026-05-04)
- `agent_client.py` delegates all URL construction to `AgentConfig.responses_url` property — no inline URL building


## Follow-Up: Config Refactoring (2026-05-04T19:29:31Z)

**Completion:** Foundry URL construction refactored.

- Separated `FOUNDRY_PROJECT` from `FOUNDRY_ENDPOINT`
- Updated `app/config.py` (responses_url property)
- Updated `.env.example` and `infra/deploy.sh`
- Decision accepted: "Split FOUNDRY_PROJECT from FOUNDRY_ENDPOINT"
- **Commit:** 2a2726c

**Impact:** All deployments now require both env vars. URL pattern remains: `{FOUNDRY_ENDPOINT}/{FOUNDRY_PROJECT}/openai/responses?api-version=...`

## Follow-Up: Eliminate Env Vars — Per-Session Config (2026-05-04T23:53:00Z)

**Completion:** All environment variables removed from app configuration.

- `app/config.py`: Removed `os.environ` / `os.getenv` / `python-dotenv`; dataclasses now require explicit constructor params
- `app/main.py`: Removed global `lifespan` services; `SpeechService` and `AgentClient` instantiated per-session from WebSocket `config` message
- `static/js/voice.js`: Config message now sends all 10 fields from localStorage
- `infra/deploy.sh`: No longer injects env vars to Container App (RBAC roles remain)
- Deleted `.env.example`; removed `python-dotenv` from requirements
- **Commit:** 2ee559a

**Learnings:**
- Per-session service instantiation means each WebSocket connection is fully independent — useful for multi-tenant or multi-config scenarios
- `DefaultAzureCredential` is a runtime concern (managed identity), not config — correctly left in place
- Frontend localStorage is now the single source of truth for all config fields

