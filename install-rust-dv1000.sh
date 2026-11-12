#!/bin/bash
set -eu

# Install Rust 1.94.0 (i686) for the HP Pavilion dv1000 (Debian 12 32-bit).
# Requires: curl, ca-certificates, build-essential (gcc), pkg-config.
# Run as your normal user; sudo is used only for the swapfile and apt packages.

SUDO=""
if [ "$(id -u)" -ne 0 ]; then
    SUDO="sudo"
fi

echo "=== Rust install for HP Pavilion dv1000 (i686 / Debian 12) ==="

# 1. Sanity: make sure we are on 32-bit
case "$(uname -m)" in
    i386|i686|x86)
        echo "OK: architecture $(uname -m) (32-bit)"
        ;;
    *)
        echo "WARNING: uname -m = $(uname -m) (not i686)."
        echo "Rustup will still install a toolchain, but set your host explicitly:"
        echo "  export RUSTUP_DIST_SERVER=... and pass --default-host i686-unknown-linux-gnu"
        ;;
esac

# 2. Base packages (no C compiler => cargo cannot link)
export DEBIAN_FRONTEND=noninteractive
${SUDO} apt-get update
${SUDO} apt-get install -y curl ca-certificates build-essential pkg-config libssl-dev zlib1g-dev git unzip

# 3. Swapfile (2 GiB RAM is tight for a Rust build)
MEM_KIB="$(awk '/MemTotal/ {print $2}' /proc/meminfo)"
if [ "${MEM_KIB}" -lt 3000000 ]; then
    SWAPFILE="/swapfile-rust"
    if [ ! -f "${SWAPFILE}" ]; then
        echo "RAM under 3 GiB: creating 3 GiB swap at ${SWAPFILE}"
        ${SUDO} fallocate -l 3G "${SWAPFILE}" || ${SUDO} dd if=/dev/zero of="${SWAPFILE}" bs=1M count=3072
        ${SUDO} chmod 600 "${SWAPFILE}"
        ${SUDO} mkswap "${SWAPFILE}"
        ${SUDO} swapon "${SWAPFILE}"
        if ! grep -q "${SWAPFILE}" /etc/fstab 2>/dev/null; then
            echo "${SWAPFILE} none swap sw 0 0" | ${SUDO} tee -a /etc/fstab >/dev/null
        fi
    else
        ${SUDO} swapon "${SWAPFILE}" 2>/dev/null || true
    fi
fi

# 4. Install rustup + toolchain 1.94.0, host i686
if [ ! -x "${HOME}/.cargo/bin/rustup" ]; then
    echo "Installing rustup..."
    curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y \
        --default-host i686-unknown-linux-gnu \
        --default-toolchain 1.94.0 \
        --profile minimal \
        --component rustfmt,clippy
else
    echo "rustup already present"
fi

# shellcheck disable=SC1091
[ -f "${HOME}/.cargo/env" ] && . "${HOME}/.cargo/env"

# 5. Pin the i686 toolchain
if ! rustup toolchain list 2>/dev/null | grep -q "1.94.0-i686"; then
    rustup toolchain install 1.94.0-i686-unknown-linux-gnu --profile minimal --component rustfmt,clippy
fi
rustup default 1.94.0-i686-unknown-linux-gnu

# 6. protoc 29.3 (32-bit) for proto codegen
if ! command -v protoc >/dev/null 2>&1; then
    echo "Installing protoc 29.3 (linux-x86_32)..."
    TMPDIR="$(mktemp -d)"
    curl -fsSL -o "${TMPDIR}/protoc.zip" \
        "https://github.com/protocolbuffers/protobuf/releases/download/v29.3/protoc-29.3-linux-x86_32.zip"
    unzip -q -o "${TMPDIR}/protoc.zip" -d "${TMPDIR}"
    ${SUDO} install -m 0755 "${TMPDIR}/bin/protoc" /usr/local/bin/protoc
    ${SUDO} mkdir -p /usr/local/include
    ${SUDO} cp -a "${TMPDIR}/include/." /usr/local/include/
fi

# 7. Report
echo
echo "=== Done ==="
rustc --version
cargo --version
protoc --version
echo
echo "Add cargo to your PATH for every new shell:"
echo '  echo '\''export PATH="$HOME/.cargo/bin:$PATH"'\'' >> ~/.bashrc'
echo
echo "Then build grok-build:"
echo '  . "$HOME/.cargo/env"'
echo '  cd grok-build && ./scripts/build-dv1000.sh release'
