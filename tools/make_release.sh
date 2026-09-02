#!/bin/sh
# Build the uploadable release archive for apps.unawatch.com.
#
# Layout follows Docs/app-config-json.md ("Output Package"): the .uapp, the
# app-manifest.json, an icon.png, and the assets/ folder with the app icons and
# the preview screenshots. Everything in the zip is generated here, so the
# archive can always be thrown away and rebuilt.
#
#   tools/make_release.sh            build the app, then package
#   tools/make_release.sh --no-build use whatever is already in Output/
#
# The checks below are the point of having a script at all. Three artifacts
# have to agree on the App ID -- the .uapp image, the manifest the store
# matches uploads by, and the developer_data_id the recorder writes into every
# FIT file -- and a fourth thing has to agree with the manifest too: the
# measure table compiled into the watch. A drift in any of them is a release
# whose charts silently do not appear.
set -e
cd "$(dirname "$0")/.."
ROOT=$(pwd)

STAGE=$ROOT/release/package
MANIFEST=$ROOT/app-manifest.json
UNA_SDK=${UNA_SDK:-$ROOT/../una-sdk}

if [ "$1" != "--no-build" ]; then
    sh tools/build.sh >/dev/null
fi

# ------------------------------------------------- generated files are current
python3 tools/gen_measures.py --check
python3 tools/gen_icons.py >/dev/null

UAPP=$(ls -t "$ROOT"/Output/*.uapp 2>/dev/null | head -1)
[ -n "$UAPP" ] || { echo "no .uapp in Output/ -- build first" >&2; exit 1; }
UAPP_NAME=$(basename "$UAPP")

# ------------------------------------------------------ manifest vs. the build
# Read the manifest as JSON, not with sed: every customMeasure has an "id"
# too, and a line-based match happily returns all thirty-three of them.
CM_ID=$(sed -n 's/^ *\([0-9A-Fa-f]\{16\}\).*/\1/p' tools/app_id.txt | head -1)
MF_ID=$(python3 -c 'import json;print(json.load(open("app-manifest.json"))["id"])')
MF_BIN=$(python3 -c 'import json;print(json.load(open("app-manifest.json"))["binary"])')
MF_VER=$(python3 -c 'import json;print(json.load(open("app-manifest.json"))["appVersion"])')

[ "$CM_ID" = "$MF_ID" ] || { echo "id mismatch: app_id.txt $CM_ID != manifest $MF_ID" >&2; exit 1; }
[ "$UAPP_NAME" = "$MF_BIN" ] || { echo "binary mismatch: built $UAPP_NAME != manifest $MF_BIN" >&2; exit 1; }
case "$UAPP_NAME" in
    *"_$MF_VER".uapp) ;;
    *) echo "appVersion $MF_VER is not the version in $UAPP_NAME" >&2; exit 1 ;;
esac

# The id the packer actually stamped into the image, not just what CMake was
# told: a stale build directory is exactly how those two drift apart. It sits
# at the head of the .uapp as a little-endian u64, not as text.
python3 - "$UAPP" "$MF_ID" <<'EOF'
import sys
image, want = sys.argv[1], sys.argv[2]
head = open(image, "rb").read(8)
got = "%016X" % int.from_bytes(head, "little")
if got != want.upper():
    sys.exit("id mismatch: %s carries %s, manifest says %s" % (image, got, want))
EOF

# ------------------------------------------------------------- manifest checks
if [ -f "$UNA_SDK/Utilities/Scripts/app_packer/min_kernel_version.py" ]; then
    python3 "$UNA_SDK/Utilities/Scripts/app_packer/min_kernel_version.py" --stamp "$MANIFEST"
    python3 "$UNA_SDK/Utilities/Scripts/app_packer/min_kernel_version.py" --check "$MANIFEST"
    python3 "$UNA_SDK/Utilities/Scripts/app_packer/validate_app_config.py" --check "$MANIFEST"
else
    echo "warning: no una-sdk at $UNA_SDK -- skipped the manifest checks" >&2
fi

# The manifest's 32 measures and the table the watch compiled in must be the
# same catalogue: this is the check that a chart missing on the phone is not
# just a typo in an id.
python3 - <<'EOF'
import json, re, sys
mf = json.load(open("app-manifest.json"))
ids_manifest = [m["id"] for m in mf["customMeasures"]]
src = open("src/fb_measures.c").read()
ids_c = re.findall(r'\{ "([a-z0-9_]+)",', src)
if ids_manifest != ids_c:
    sys.exit("manifest and src/fb_measures.c disagree:\n  manifest: %s\n  c table : %s"
             % (ids_manifest, ids_c))
missing = [m["id"] for m in mf["customMeasures"]
           if not m["icon"].startswith("assets/icons/measures/")]
if missing:
    sys.exit("measure icons must live under assets/icons/measures/: %s" % missing)
print("catalogue: %d measures, manifest and watch table agree" % len(ids_c))
EOF

# ------------------------------------------------------------------- staging
rm -rf "$ROOT/release"
mkdir -p "$STAGE/assets/icons/measures"

cp "$UAPP" "$STAGE/$UAPP_NAME"
cp "$MANIFEST" "$STAGE/app-manifest.json"
# The store icon is the full-size artwork; the two small ones are what the
# watch itself draws and are already embedded in the .uapp -- they ride along
# so the listing can show them.
cp Resources/icon_store.png "$STAGE/icon.png"
cp Resources/icon_60x60.png Resources/icon_30x30.png "$STAGE/assets/icons/"
cp Resources/measures/*.png "$STAGE/assets/icons/measures/"

# The screenshots go in by the folder convention from Docs/app-config-json.md
# ("Package Content"). They are deliberately NOT referenced from a "previews"
# key in the manifest -- see the note in README.md: UOOM was accepted with that
# key, PEEK's script records an upload rejected over it, and PEEK was accepted
# without it while shipping this same folder. Omitting it is the option that
# cannot block the release.
make -C host >/dev/null
python3 tools/gen_previews.py --out "$STAGE/assets/previews"

# Every icon the manifest points at has to be in the archive.
python3 - <<'EOF'
import json, os, sys
mf = json.load(open("release/package/app-manifest.json"))
root = "release/package"
missing = [mf["icon"]] if not os.path.exists(os.path.join(root, mf["icon"])) else []
missing += [m["icon"] for m in mf["customMeasures"]
            if not os.path.exists(os.path.join(root, m["icon"]))]
if missing:
    sys.exit("manifest points at files that are not in the package: %s" % missing)
print("assets: icon.png + %d measure icons present" % len(mf["customMeasures"]))
EOF

# -------------------------------------------------------------------- archive
ZIP=$ROOT/release/${UAPP_NAME%.uapp}.zip
(cd "$STAGE" && zip -qr "$ZIP" . -x '.*')

echo
echo "$ZIP"
unzip -l "$ZIP" | sed -n '4,$p' | head -20
echo "..."
unzip -l "$ZIP" | tail -3
