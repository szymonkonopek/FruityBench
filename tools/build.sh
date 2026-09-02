#!/bin/sh
# Build FruitBench for the watch.
#
# Same three-step wrap PEEK and UOOM use: the ST toolchain from STM32CubeCLT,
# UNA_SDK pointing at a una-sdk checkout, and a project-local venv with
# pyelftools+pillow for the SDK's packer.
#
#   tools/build.sh          build
#   tools/build.sh clean    wipe the build dir first
#   UNA_SDK=... CLT=... tools/build.sh
set -e
cd "$(dirname "$0")/.."
ROOT=$(pwd)

# ---------------------------------------------------------------- toolchain
CLT=${CLT:-$(ls -d /opt/ST/STM32CubeCLT_* 2>/dev/null | sort -V | tail -1)}
if [ -z "$CLT" ] || [ ! -d "$CLT/GNU-tools-for-STM32/bin" ]; then
    echo "STM32CubeCLT not found. Install it, or set CLT=/path/to/STM32CubeCLT_x.y.z" >&2
    exit 1
fi
PATH="$CLT/GNU-tools-for-STM32/bin:$CLT/CMake/bin:$CLT/Make/bin:$CLT/Ninja/bin:$PATH"
export PATH

# ------------------------------------------------------------------ the SDK
UNA_SDK=${UNA_SDK:-$ROOT/../una-sdk}
if [ ! -f "$UNA_SDK/cmake/una-app.cmake" ]; then
    echo "UNA_SDK does not look like a una-sdk checkout: $UNA_SDK" >&2
    exit 1
fi
UNA_SDK=$(cd "$UNA_SDK" && pwd)
export UNA_SDK

# ------------------------------------------------------- the SDK's python deps
VENV=$ROOT/.venv
if [ ! -x "$VENV/bin/python" ]; then
    echo "creating $VENV for the SDK's packaging scripts"
    python3 -m venv "$VENV"
fi
"$VENV/bin/python" -c "import elftools, PIL" 2>/dev/null || {
    echo "installing pyelftools and pillow into $VENV"
    "$VENV/bin/pip" install --quiet pyelftools pillow
}

# -------------------------------------------- the generated catalogue + icons
#
# The manifest, the on-watch measure table and the icons all come out of
# tools/gen_measures.py and tools/gen_icons.py. Regenerating before every
# build is cheap and removes the whole class of bug where the table the watch
# writes and the manifest the phone reads disagree.
"$VENV/bin/python" tools/gen_measures.py
if [ ! -f Resources/icon_60x60.png ] || [ ! -f Resources/measures/banana_flex.png ]; then
    "$VENV/bin/python" tools/gen_icons.py
fi

# ----------------------------------------------------------------- build
BUILD=$ROOT/build
for a in "$@"; do
    [ "$a" = "clean" ] && rm -rf "$BUILD"
done

echo "UNA_SDK   = $UNA_SDK"
echo "toolchain = $(command -v arm-none-eabi-gcc)"

# The linker writes its .map into Output/ and the packer writes the .uapp
# there, so it has to exist first.
mkdir -p "$ROOT/Output"

cmake -G "Unix Makefiles" \
      -DUNA_PYTHON_EXECUTABLE="$VENV/bin/python" \
      -S . -B "$BUILD" >/dev/null

cmake --build "$BUILD" -j"$(getconf _NPROCESSORS_ONLN 2>/dev/null || echo 4)" 2>&1 \
  | grep -vE "Forcing branch to absolute symbol"

echo
echo "=== footprint (all RAM: the app linker script has no flash region) ==="
arm-none-eabi-size -A "$BUILD/FRUITBENCHService.elf" 2>/dev/null | head -12
arm-none-eabi-size -A "$BUILD/FRUITBENCHGUI.elf" 2>/dev/null | head -12

echo
ls -la Output/*.uapp 2>/dev/null
