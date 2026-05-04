# Squad Team

> voice-agent-speech-services — Python web app integrating Azure Speech Services (STT/TTS) with a Foundry agent via the Responses API, deployed to Azure Container Apps with managed identities.

## Coordinator

| Name | Role | Notes |
|------|------|-------|
| Squad | Coordinator | Routes work, enforces handoffs and reviewer gates. |

## Members

| Name | Role | Charter | Status |
|------|------|---------|--------|
| Ripley | Lead | .squad/agents/ripley/charter.md | 🏗️ Active |
| Dallas | Backend Dev | .squad/agents/dallas/charter.md | 🔧 Active |
| Ash | DevOps | .squad/agents/ash/charter.md | ⚙️ Active |
| Lambert | Tester | .squad/agents/lambert/charter.md | 🧪 Active |
| Scribe | Session Logger | .squad/agents/scribe/charter.md | 📋 Active |
| Ralph | Work Monitor | — | 🔄 Monitor |

## Project Context

- **Project:** voice-agent-speech-services
- **User:** dsanchor
- **Created:** 2026-05-04
- **Stack:** Python, Azure Speech SDK (cognitive-services-speech-sdk), Azure Container Apps, Managed Identities, GitHub Actions
- **Description:** A voice-enabled web app that gives voice to a Foundry agent using Azure Speech Services for STT/TTS, calling the agent via the Responses API. Containerized with Docker, deployed to Azure Container Apps with managed identity access to Speech Service and Foundry agent.
