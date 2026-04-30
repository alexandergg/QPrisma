#!/usr/bin/env sh
set -eu

SERVICE_NAME="${AZD_SERVICE_NAME:-qprisma-video-agent}"
REQUIRE_IDENTITY="$(printf '%s' "${REQUIRE_AGENT_IDENTITY_RBAC:-false}" | tr '[:upper:]' '[:lower:]')"

echo "Running postdeploy hook for ${SERVICE_NAME}..."

extract_agent_principal_id() {
  if command -v jq >/dev/null 2>&1; then
    jq -r '.instance_identity.principal_id // empty'
  elif command -v python3 >/dev/null 2>&1; then
    python3 -c 'import json,sys; data=json.load(sys.stdin); print(((data.get("instance_identity") or {}).get("principal_id")) or "")'
  elif command -v python >/dev/null 2>&1; then
    python -c 'import json,sys; data=json.load(sys.stdin); print(((data.get("instance_identity") or {}).get("principal_id")) or "")'
  else
    cat >/dev/null
  fi
}

AGENT_JSON="$(azd ai agent show "${SERVICE_NAME}" 2>/dev/null || true)"
AGENT_PRINCIPAL_ID="$(printf '%s' "${AGENT_JSON}" | extract_agent_principal_id 2>/dev/null || true)"

if [ -z "${AGENT_PRINCIPAL_ID}" ]; then
  MESSAGE="Hosted agent runtime identity is not available yet; skipping downstream RBAC assignment."
  case "${REQUIRE_IDENTITY}" in
    1|true|yes|on)
      echo "ERROR: ${MESSAGE}" >&2
      exit 1
      ;;
    *)
      echo "WARNING: ${MESSAGE}"
      exit 0
      ;;
  esac
fi

echo "Hosted agent runtime identity detected: $(printf '%s' "${AGENT_PRINCIPAL_ID}" | cut -c1-8)..."

if [ -n "${AZURE_SUBSCRIPTION_ID:-}" ] && [ -n "${AZURE_RESOURCE_GROUP:-}" ] && [ -n "${AZURE_STORAGE_ACCOUNT_NAME:-}" ]; then
  STORAGE_SCOPE="/subscriptions/${AZURE_SUBSCRIPTION_ID}/resourceGroups/${AZURE_RESOURCE_GROUP}/providers/Microsoft.Storage/storageAccounts/${AZURE_STORAGE_ACCOUNT_NAME}"
  echo "Assigning Storage Blob Data Contributor to hosted agent identity..."
  if ! az role assignment create \
    --assignee-object-id "${AGENT_PRINCIPAL_ID}" \
    --assignee-principal-type ServicePrincipal \
    --role "ba92f5b4-2d11-453d-a403-e96b0029c9fe" \
    --scope "${STORAGE_SCOPE}" \
    --only-show-errors \
    --output none 2>/dev/null; then
    echo "Storage role assignment may already exist for ${SERVICE_NAME}."
  fi
else
  echo "Storage account metadata is incomplete; skipping Storage Blob Data Contributor assignment."
fi

echo "Postdeploy hook complete."
