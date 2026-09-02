#!/bin/sh
# Record a session on this machine and check the file it produced.
#
# The point: the 32 developer fields are the whole app, and they can be
# verified without a watch. This compiles the real recorder (fb_fit.cpp,
# fb_gen.c) against the SDK's FIT encoder with a stdio IFile, writes a full
# session, and hands the result to tools/fit_check.py.
#
#   tools/host_test.sh                  15 minutes of data, random seed
#   tools/host_test.sh --seconds 3600   an hour
#   UNA_SDK=... tools/host_test.sh --seed 0xC0FFEE
set -e
cd "$(dirname "$0")/.."
ROOT=$(pwd)

UNA_SDK=${UNA_SDK:-$ROOT/../una-sdk}
if [ ! -f "$UNA_SDK/Libs/Source/Fit/FitWriter.cpp" ]; then
    echo "UNA_SDK does not look like a una-sdk checkout: $UNA_SDK" >&2
    exit 1
fi
UNA_SDK=$(cd "$UNA_SDK" && pwd)

OUT=$ROOT/build/host
mkdir -p "$OUT"

APP_ID=$(sed -n 's/^ *\([0-9A-Fa-f]\{16\}\).*/\1/p' tools/app_id.txt | head -1)
[ -n "$APP_ID" ] || { echo "tools/app_id.txt: no 16-hex App ID" >&2; exit 1; }

python3 tools/gen_measures.py >/dev/null

# Same sources the watch links, minus the kernel: FitWriter + FitCrc +
# FitRecordCadence are all fb_fit.cpp needs from the SDK. The generator is C,
# so it is compiled on its own and linked in.
for c in fb_gen fb_fmt fb_measures; do
    ${CC:-clang} -std=c11 -O1 -Wall -Wextra -Isrc -c "src/$c.c" -o "$OUT/$c.o"
done

${CXX:-clang++} -std=c++17 -O1 -Wall -Wextra \
    -DAPP_ID="\"$APP_ID\"" \
    -I"$UNA_SDK/Libs/Header" -Isrc -Itools \
    tools/fit_host_test.cpp \
    src/fb_fit.cpp \
    "$UNA_SDK/Libs/Source/Fit/FitWriter.cpp" \
    "$UNA_SDK/Libs/Source/Fit/FitCrc.cpp" \
    "$UNA_SDK/Libs/Source/Fit/FitRecordCadence.cpp" \
    "$OUT/fb_gen.o" "$OUT/fb_fmt.o" "$OUT/fb_measures.o" \
    -o "$OUT/fit_host_test"

FIT=$OUT/fruitbench_host.fit
"$OUT/fit_host_test" "$FIT" "$@"
echo
python3 tools/fit_check.py "$FIT"
