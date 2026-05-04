## Project Context

- **Project:** voice-agent-speech-services
- **User:** dsanchor
- **Stack:** Python, Azure Speech SDK (cognitive-services-speech-sdk), Azure Container Apps, Managed Identities, GitHub Actions
- **Description:** Voice-enabled web app giving voice to a Foundry agent using Azure Speech Services STT/TTS, calling agent via Responses API. Dockerized, deployed to Azure Container Apps with managed identities.

## Session Work (2026-05-04)

**Outcome:** Production infrastructure for voice app MVP.

- Built multi-stage Dockerfile with lean production image (libssl3, libasound2, ca-certificates)
- Configured dual-role managed identity RBAC:
  - "Cognitive Services Speech User" for STT/TTS (Speech resource)
  - "Azure AI User" for Responses API (Foundry resource)
- Implemented `infra/deploy.sh` for Container App provisioning
- Set up GitHub Actions CI/CD workflow (build-and-push)
- Configured environment variables for Azure service endpoints
- **3 files created**

**Team Collaboration:** Worked with Dallas on auth architecture; coordinated managed identity roles to match SDK token scopes.

## Learnings

- Multi-stage Docker build critical for cognitive services SDKs (excludes build deps, pip cache)
- Managed identity + RBAC eliminates secret storage/rotation burden
- Dual-role setup (one per service) enables fine-grained access control
- `DefaultAzureCredential` transparent auth requires proper RBAC scoping

