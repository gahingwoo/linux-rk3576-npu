#!/usr/bin/env bash
# Build Mesa with Rocket Gallium driver + Teflon TFLite delegate.
# Produces: mesa/out/usr/lib/libteflon.so
#
# Host is aarch64 (Parallels on Apple Silicon) = same as target, so default is --native.
# Cross-compile only needed if building on x86_64.
#
# Usage:
#   bash mesa/build-mesa.sh           # native (default on aarch64 host)
#   bash mesa/build-mesa.sh --cross   # force cross-compile from x86_64
#
# Update MESA_TAG to latest mesa-2x.x tag before first run.
# Check: https://gitlab.freedesktop.org/mesa/mesa/-/tags?search=mesa-2
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
OUT="$SCRIPT_DIR/out"
BUILD="$SCRIPT_DIR/build"
SRC="$SCRIPT_DIR/mesa-src"

MESA_REPO="https://gitlab.freedesktop.org/mesa/mesa.git"
MESA_TAG="mesa-25.3.0"   # requires rocket + teflon; update to latest 26.x tag

CROSS=0
[[ "${1:-}" == "--cross" ]] && CROSS=1
# Auto-detect: if host is not aarch64, force cross
[[ "$(uname -m)" != "aarch64" ]] && CROSS=1
NATIVE=$(( 1 - CROSS ))

# ── Dependencies check ────────────────────────────────────────────────────────
check_dep() {
    command -v "$1" &>/dev/null || { echo "ERROR: $1 not found. Install: $2" >&2; exit 1; }
}
check_dep meson    "apt install meson"
check_dep ninja    "apt install ninja-build"
check_dep pkg-config "apt install pkg-config"
check_dep python3  "apt install python3"

if [[ "$CROSS" -eq 1 ]]; then
    check_dep aarch64-linux-gnu-gcc "apt install gcc-aarch64-linux-gnu"
fi

# ── TFLite flatbuffers headers ────────────────────────────────────────────────
# Teflon requires flatbuffers headers. Check or download.
FLATBUF_INC="$SCRIPT_DIR/flatbuffers/include"
if [[ ! -d "$FLATBUF_INC" ]]; then
    echo "==> Fetching flatbuffers headers..."
    mkdir -p "$SCRIPT_DIR/flatbuffers"
    FB_VER="23.5.26"
    FB_URL="https://github.com/google/flatbuffers/archive/refs/tags/v${FB_VER}.tar.gz"
    curl -L "$FB_URL" | tar -xz -C "$SCRIPT_DIR/flatbuffers" --strip-components=2 \
        "flatbuffers-${FB_VER}/include"
fi

# ── TFLite library (for Teflon linkage) ───────────────────────────────────────
# Mesa teflon only needs headers at build time; libtensorflowlite.so is loaded
# at runtime on the board.
TFLITE_INC="$SCRIPT_DIR/tflite/include"
if [[ ! -d "$TFLITE_INC" ]]; then
    echo "==> Fetching TFLite C API headers..."
    mkdir -p "$TFLITE_INC"
    TFLITE_VER="2.16.1"
    TFLITE_URL="https://github.com/tensorflow/tensorflow/archive/refs/tags/v${TFLITE_VER}.tar.gz"
    curl -L "$TFLITE_URL" | tar -xz -C "$SCRIPT_DIR/tflite" \
        --strip-components=1 \
        "tensorflow-${TFLITE_VER}/tensorflow/lite/c/c_api.h" \
        "tensorflow-${TFLITE_VER}/tensorflow/lite/c/c_api_types.h" \
        "tensorflow-${TFLITE_VER}/tensorflow/lite/c/common.h" 2>/dev/null || \
    echo "  TFLite header fetch failed; Teflon may not link. Install manually."
fi

# ── Mesa source ───────────────────────────────────────────────────────────────
if [[ ! -d "$SRC/.git" ]]; then
    echo "==> Cloning Mesa (tag $MESA_TAG)..."
    git clone --depth=1 --branch "$MESA_TAG" "$MESA_REPO" "$SRC"
else
    echo "==> Mesa source already present at $SRC"
    echo "    Commit: $(git -C "$SRC" rev-parse --short HEAD)"
fi

ACTUAL_COMMIT="$(git -C "$SRC" rev-parse HEAD)"
echo "==> Mesa commit: $ACTUAL_COMMIT"

# ── Meson cross-file ──────────────────────────────────────────────────────────
if [[ "$CROSS" -eq 1 ]]; then
    CROSS_FILE="$BUILD/aarch64-cross.ini"
    mkdir -p "$BUILD"
    cat > "$CROSS_FILE" <<'INI'
[binaries]
c = 'aarch64-linux-gnu-gcc'
cpp = 'aarch64-linux-gnu-g++'
ar = 'aarch64-linux-gnu-ar'
strip = 'aarch64-linux-gnu-strip'
pkg-config = 'pkg-config'

[host_machine]
system = 'linux'
cpu_family = 'aarch64'
cpu = 'cortex-a55'
endian = 'little'
INI
    CROSS_ARG="--cross-file $CROSS_FILE"
else
    CROSS_ARG=""
fi

# ── Meson configure ───────────────────────────────────────────────────────────
echo "==> Configuring Mesa build..."
mkdir -p "$BUILD"

EXTRA_CFLAGS="-I${FLATBUF_INC}"
[[ -d "$TFLITE_INC" ]] && EXTRA_CFLAGS="$EXTRA_CFLAGS -I${SCRIPT_DIR}/tflite"

# shellcheck disable=SC2086
meson setup "$BUILD" "$SRC" \
    $CROSS_ARG \
    --prefix=/usr \
    --buildtype=release \
    -Dgallium-drivers=rocket \
    -Dvulkan-drivers= \
    -Dteflon=true \
    -Dplatforms=[] \
    -Degl=disabled \
    -Dgles1=disabled \
    -Dgles2=disabled \
    -Dglx=disabled \
    -Dllvm=disabled \
    -Dshared-llvm=disabled \
    -Dc_args="$EXTRA_CFLAGS" \
    -Dcpp_args="$EXTRA_CFLAGS"

# ── Build ─────────────────────────────────────────────────────────────────────
echo "==> Building ($(nproc) jobs)..."
ninja -C "$BUILD" -j"$(nproc)"

# ── Install to out/ ───────────────────────────────────────────────────────────
echo "==> Installing to $OUT..."
DESTDIR="$OUT" ninja -C "$BUILD" install

echo ""
echo "==> Mesa build complete."
echo "    libteflon.so: $(find "$OUT" -name 'libteflon.so' 2>/dev/null | head -1)"
echo ""
echo "==> Deploy to board:"
echo "    scp $(find "$OUT" -name 'libteflon.so' 2>/dev/null | head -1) root@<board-ip>:/usr/lib/"
echo ""
echo "==> Mesa commit for Tested-by:"
echo "    $ACTUAL_COMMIT"
