#!/bin/bash
set -eu

# Write the bridge (Firefox/NemApi) config into the host grok home
# (~/.grok), NOT into a container. The CLI workspace stays on this machine.
#
# Installs:
#   ~/.grok/config.toml                     (from config.nemapi.toml)
#   ~/.grok/rules/grok-bridge-system.md     (system rules for the bridge)

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
GROK_HOME="${GROK_HOME:-$HOME/.grok}"
mkdir -p "${GROK_HOME}" "${GROK_HOME}/rules"

cp "${ROOT}/config.nemapi.toml" "${GROK_HOME}/config.toml"
echo "Wrote ${GROK_HOME}/config.toml"

cp "${ROOT}/rules/grok-bridge-system.md" "${GROK_HOME}/rules/grok-bridge-system.md"
echo "Wrote ${GROK_HOME}/rules/grok-bridge-system.md"
echo
echo "Export the single key, open the provider tab in the bridge Firefox profile,"
echo "then run:"
echo "  export NEMAPI_API_KEY=local"
echo "  xai-grok-pager --single \"bonjour\" --model deepseek-chat"
