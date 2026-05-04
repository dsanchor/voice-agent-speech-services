# Decision: Multi-stage Dockerfile + dual-role managed identity deploy

**Date:** 2026-05-04T16:51:23+02:00
**Author:** Ash (DevOps)
**Status:** Accepted

## Context

This project uses `azure-cognitiveservices-speech` which pulls in native C++ libs requiring `libssl3` and `libasound2` at runtime. The app also needs managed identity access to two separate Azure services (Speech and AI Foundry).

## Decision

1. **Multi-stage Dockerfile** — builder stage installs pip deps with `--prefix=/install`, production stage copies only the installed packages plus runtime system libs (`libssl3`, `libasound2`, `ca-certificates`). This keeps the final image lean by excluding build tools and pip cache.

2. **Dual role assignment in deploy.sh** — the Container App's system-assigned managed identity gets:
   - "Cognitive Services Speech User" scoped to the Speech resource (for STT/TTS token acquisition)
   - "Azure AI User" scoped to the Foundry resource (for Responses API with `https://ai.azure.com` audience)

   No secrets stored anywhere. Both SDKs use `DefaultAzureCredential` which picks up the managed identity automatically.

3. **Environment variables over secrets** — `AZURE_SPEECH_REGION`, `AZURE_SPEECH_RESOURCE_ID`, `FOUNDRY_ENDPOINT`, and `FOUNDRY_AGENT_NAME` are non-sensitive configuration values passed as plain env vars to the Container App. No Key Vault needed for these.

## Alternatives Considered

- Single-stage Dockerfile: simpler but bloats the image with build deps.
- User-assigned managed identity: more flexible for multi-app scenarios but unnecessary complexity for a single app.
- Storing Speech keys in Key Vault: rejected — managed identity with RBAC is strictly better.
