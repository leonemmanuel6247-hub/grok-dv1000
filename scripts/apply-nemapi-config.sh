#!/bin/bash
set -eu

# Write the NemApi config into the host grok home (~/.grok), NOT into a container.
# The CLI workspace stays on this machine.

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
GROK_HOME="${GROK_HOME:-$HOME/.grok}"
mkdir -p "${GROK_HOME}"

cp "${ROOT}/config.nemapi.toml" "${GROK_HOME}/config.toml"
echo "Wrote ${GROK_HOME}/config.toml"
echo
echo "Start NemApi on 127.0.0.1:8090, then run:"
echo "  ${ROOT}/scripts/build-dv1000.sh release"
