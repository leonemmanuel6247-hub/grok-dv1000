#!/bin/bash
set -eu

# Low-RAM build for HP Pavilion dv1000 (Debian 12 i686, 2 GiB).
# One rustc job, no jemalloc, system protoc, CARGO_INCREMENTAL off.

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "${ROOT}"

if [ -f "${HOME}/.cargo/env" ]; then
    # shellcheck disable=SC1091
    . "${HOME}/.cargo/env"
fi

if ! command -v cargo >/dev/null 2>&1; then
    echo "cargo not found. Run scripts/bootstrap-dv1000.sh first."
    exit 1
fi

if ! command -v protoc >/dev/null 2>&1; then
    echo "protoc not found. Run scripts/bootstrap-dv1000.sh first."
    exit 1
fi

export CARGO_BUILD_JOBS=1
export CARGO_INCREMENTAL=0
export RUSTFLAGS="${RUSTFLAGS:-} -C codegen-units=1"
export PROTOC="$(command -v protoc)"
export CARGO_TERM_COLOR=always

# ripgrep/fd auto-download has no i686 musl assets; skip bundling unless a local binary is provided.
# Runtime falls back to rg/fd on PATH.

MODE="${1:-release}"
case "${MODE}" in
    check)
        echo "cargo check -p xai-grok-pager-bin (i686, 1 job, no jemalloc)"
        cargo check -p xai-grok-pager-bin --no-default-features --features stock,sandbox-enforce
        ;;
    dev)
        echo "cargo build -p xai-grok-pager-bin (dev, i686, 1 job, no jemalloc)"
        cargo build -p xai-grok-pager-bin --no-default-features --features stock,sandbox-enforce
        echo "binary: ${ROOT}/target/i686-unknown-linux-gnu/debug/xai-grok-pager"
        ;;
    release)
        echo "cargo build -p xai-grok-pager-bin --release (i686, 1 job, no jemalloc)"
        cargo build -p xai-grok-pager-bin --release --no-default-features --features stock,sandbox-enforce
        echo "binary: ${ROOT}/target/i686-unknown-linux-gnu/release/xai-grok-pager"
        echo "install: ln -sf ${ROOT}/target/i686-unknown-linux-gnu/release/xai-grok-pager ${HOME}/.local/bin/grok"
        ;;
    *)
        echo "usage: $0 [check|dev|release]"
        exit 1
        ;;
esac
