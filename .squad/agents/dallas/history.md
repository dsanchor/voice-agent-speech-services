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

