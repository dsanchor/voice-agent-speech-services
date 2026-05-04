# Squad Decisions

## Active Decisions

### Multi-stage Dockerfile + dual-role managed identity deploy

**Date:** 2026-05-04T16:51:23+02:00  
**Author:** Ash (DevOps)  
**Status:** Accepted

Uses multi-stage Dockerfile with lean production image (libssl3, libasound2, ca-certificates). Dual RBAC roles: "Cognitive Services Speech User" for Speech STT/TTS, "Azure AI User" for Responses API. All SDKs use `DefaultAzureCredential` (no secrets). Config via env vars: `AZURE_SPEECH_REGION`, `AZURE_SPEECH_RESOURCE_ID`, `FOUNDRY_ENDPOINT`, `FOUNDRY_AGENT_NAME`.

### Token-based Auth & WAV Transport for Speech SDK

**Date:** 2026-05-04T16:51:23+02:00  
**Author:** Dallas (Backend Dev)  
**Status:** Accepted

`TokenManager` acquires/caches tokens from `DefaultAzureCredential` with 2-min pre-expiry margin. Browser captures 16 kHz 16-bit mono PCM, wraps in WAV header, base64-encodes inside JSON. TTS returns MP3 (16 kHz 32 kbps mono). Responses API context via `previous_response_id` threading. SDK blocking calls run on thread pool via `asyncio.to_thread()`.

### Split FOUNDRY_PROJECT from FOUNDRY_ENDPOINT

**Date:** 2026-05-04T21:29:31+02:00  
**Author:** Dallas (Backend Dev)  
**Status:** Accepted

The Responses API URL is now composed from two env vars instead of one: `FOUNDRY_ENDPOINT` (base URL up to `/api/projects`) and `FOUNDRY_PROJECT` (project name). Resulting URL: `{FOUNDRY_ENDPOINT}/{FOUNDRY_PROJECT}/openai/responses?api-version={FOUNDRY_API_VERSION}`. Separating the project allows reuse of the same endpoint across multiple projects and makes config more explicit. All deployments must now set `FOUNDRY_PROJECT` in addition to `FOUNDRY_ENDPOINT`. Deploy script and `.env.example` updated accordingly.

## Governance

- All meaningful changes require team consensus
- Document architectural decisions here
- Keep history focused on work, decisions focused on direction
