#!/usr/bin/env bash
set -euo pipefail

###############################################################################
# deploy.sh — Deploy to Azure Container Apps with managed identity
#
# Required params:
#   --resource-group       Azure resource group name
#   --name                 Container App name
#   --image                Container image (e.g. ghcr.io/org/repo:latest)
#   --speech-resource-id   Full resource ID of the Azure Speech Service
#   --foundry-resource-id  Full resource ID of the AI Foundry resource
#   --location             Azure region (e.g. swedencentral)
#   --env-name             Container Apps environment name
#
# Note: App configuration (speech region, endpoint, agent name, etc.) is now
# provided per-session by the frontend — no env vars needed for the app itself.
# The managed identity still needs RBAC roles for token-based auth.
###############################################################################

usage() {
  echo "Usage: $0 --resource-group RG --name APP --image IMG --speech-resource-id SRID --foundry-resource-id FRID --location LOC --env-name ENV"
  exit 1
}

RESOURCE_GROUP=""
APP_NAME=""
IMAGE=""
SPEECH_RESOURCE_ID=""
FOUNDRY_RESOURCE_ID=""
LOCATION=""
ENV_NAME=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --resource-group)      RESOURCE_GROUP="$2"; shift 2 ;;
    --name)                APP_NAME="$2"; shift 2 ;;
    --image)               IMAGE="$2"; shift 2 ;;
    --speech-resource-id)  SPEECH_RESOURCE_ID="$2"; shift 2 ;;
    --foundry-resource-id) FOUNDRY_RESOURCE_ID="$2"; shift 2 ;;
    --location)            LOCATION="$2"; shift 2 ;;
    --env-name)            ENV_NAME="$2"; shift 2 ;;
    *) echo "Unknown option: $1"; usage ;;
  esac
done

[[ -z "$RESOURCE_GROUP" || -z "$APP_NAME" || -z "$IMAGE" || -z "$SPEECH_RESOURCE_ID" || -z "$FOUNDRY_RESOURCE_ID" || -z "$LOCATION" || -z "$ENV_NAME" ]] && usage

echo "==> Creating resource group: $RESOURCE_GROUP in $LOCATION"
az group create \
  --name "$RESOURCE_GROUP" \
  --location "$LOCATION" \
  --output none

echo "==> Creating Container Apps environment: $ENV_NAME"
az containerapp env create \
  --name "$ENV_NAME" \
  --resource-group "$RESOURCE_GROUP" \
  --location "$LOCATION" \
  --output none

echo "==> Creating Container App: $APP_NAME"
az containerapp create \
  --name "$APP_NAME" \
  --resource-group "$RESOURCE_GROUP" \
  --environment "$ENV_NAME" \
  --image "$IMAGE" \
  --target-port 8000 \
  --ingress external \
  --system-assigned \
  --output none

echo "==> Retrieving managed identity principal ID"
PRINCIPAL_ID=$(az containerapp show \
  --name "$APP_NAME" \
  --resource-group "$RESOURCE_GROUP" \
  --query "identity.principalId" \
  --output tsv)

echo "    Principal ID: $PRINCIPAL_ID"

echo "==> Assigning 'Cognitive Services Speech User' role on Speech Service"
az role assignment create \
  --assignee-object-id "$PRINCIPAL_ID" \
  --assignee-principal-type ServicePrincipal \
  --role "Cognitive Services Speech User" \
  --scope "$SPEECH_RESOURCE_ID" \
  --output none

echo "==> Assigning 'Azure AI User' role on Foundry resource"
az role assignment create \
  --assignee-object-id "$PRINCIPAL_ID" \
  --assignee-principal-type ServicePrincipal \
  --role "Azure AI User" \
  --scope "$FOUNDRY_RESOURCE_ID" \
  --output none

APP_URL=$(az containerapp show \
  --name "$APP_NAME" \
  --resource-group "$RESOURCE_GROUP" \
  --query "properties.configuration.ingress.fqdn" \
  --output tsv)

echo ""
echo "==> Deployment complete!"
echo "    App URL: https://$APP_URL"
