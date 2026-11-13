#!/bin/bash
set -eu

# Bootstrap grok-build on HP Pavilion dv1000
# Debian 12 i386, 2 GiB RAM, ~149 GiB disk.

echo "=== grok-build bootstrap (i686 / 2 GiB) ==="

if [ "$(id -u)" -eq 0 ]; then
    SUDO=""
else
    SUDO="sudo"
fi

ARCH="$(uname -m)"
case "${ARCH}" in
    i386|i686|x86)
        ;;
    *)
        echo "This bootstrap is for Debian 12 32-bit (i686)."
        echo "Current uname -m: ${ARCH}"
        echo "Continue only if you are cross-preparing an i686 tree."
        ;;
esac

export DEBIAN_FRONTEND=noninteractive

${SUDO} apt-get update
${SUDO} apt-get install -y \
    build-essential \
    pkg-config \
    libssl-dev \
    zlib1g-dev \
    ca-certificates \
    curl \
    unzip \
    git \
    cmake \
    python3

MEM_KIB="$(awk '/MemTotal/ {print $2}' /proc/meminfo)"
if [ "${MEM_KIB}" -lt 3000000 ]; then
    SWAPFILE="/swapfile-grok"
    if [ ! -f "${SWAPFILE}" ]; then
        echo "RAM is under 3 GiB. Creating 3 GiB swap at ${SWAPFILE}"
        ${SUDO} fallocate -l 3G "${SWAPFILE}" || ${SUDO} dd if=/dev/zero of="${SWAPFILE}" bs=1M count=3072
        ${SUDO} chmod 600 "${SWAPFILE}"
        ${SUDO} mkswap "${SWAPFILE}"
        ${SUDO} swapon "${SWAPFILE}"
        if ! grep -q "${SWAPFILE}" /etc/fstab; then
            echo "${SWAPFILE} none swap sw 0 0" | ${SUDO} tee -a /etc/fstab >/dev/null
        fi
    else
        ${SUDO} swapon "${SWAPFILE}" 2>/dev/null || true
    fi
fi

PROTOC_VER="29.3"
if ! command -v protoc >/dev/null 2>&1; then
    TMPDIR="$(mktemp -d)"
    curl -fsSL -o "${TMPDIR}/protoc.zip" \
        "https://github.com/protocolbuffers/protobuf/releases/download/v${PROTOC_VER}/protoc-${PROTOC_VER}-linux-x86_32.zip"
    unzip -q -o "${TMPDIR}/protoc.zip" -d "${TMPDIR}"
    ${SUDO} install -m 0755 "${TMPDIR}/bin/protoc" /usr/local/bin/protoc
    ${SUDO} mkdir -p /usr/local/include
    ${SUDO} cp -a "${TMPDIR}/include/." /usr/local/include/
fi
protoc --version

if [ ! -x "${HOME}/.cargo/bin/rustup" ]; then
    curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y \
        --default-host i686-unknown-linux-gnu \
        --default-toolchain 1.94.0 \
        --profile minimal \
        --component rustfmt,clippy
fi

# shellcheck disable=SC1091
. "${HOME}/.cargo/env"
rustup toolchain install 1.94.0-i686-unknown-linux-gnu
rustup default 1.94.0-i686-unknown-linux-gnu
rustc --version
cargo --version

echo "=== bootstrap done ==="
echo "Next:"
echo "  . \"\$HOME/.cargo/env\""
echo "  ./scripts/build-dv1000.sh"
