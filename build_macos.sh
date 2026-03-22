#!/bin/bash
# Fovea - macOS App Builder
# Creates a .app bundle and .dmg installer
# No developer account needed — uses ad-hoc signing

set -e
cd "$(dirname "$0")"

APP_NAME="Fovea"
APP_VERSION="0.1.0"
BUNDLE_ID="com.fovea.app"
BUILD_DIR="build"
APP_DIR="$BUILD_DIR/$APP_NAME.app"
DMG_NAME="$APP_NAME-$APP_VERSION-macOS.dmg"

echo "=== Building $APP_NAME.app ==="

# Clean
rm -rf "$BUILD_DIR"
mkdir -p "$APP_DIR/Contents/MacOS"
mkdir -p "$APP_DIR/Contents/Resources/src"
mkdir -p "$APP_DIR/Contents/Resources/static"

# ---- Info.plist ----
cat > "$APP_DIR/Contents/Info.plist" << PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleName</key>
    <string>$APP_NAME</string>
    <key>CFBundleDisplayName</key>
    <string>$APP_NAME</string>
    <key>CFBundleIdentifier</key>
    <string>$BUNDLE_ID</string>
    <key>CFBundleVersion</key>
    <string>$APP_VERSION</string>
    <key>CFBundleShortVersionString</key>
    <string>$APP_VERSION</string>
    <key>CFBundleExecutable</key>
    <string>fovea-launcher</string>
    <key>CFBundlePackageType</key>
    <string>APPL</string>
    <key>LSMinimumSystemVersion</key>
    <string>12.0</string>
    <key>NSHighResolutionCapable</key>
    <true/>
    <key>LSUIElement</key>
    <false/>
    <key>NSAppTransportSecurity</key>
    <dict>
        <key>NSAllowsLocalNetworking</key>
        <true/>
    </dict>
</dict>
</plist>
PLIST

# ---- Launcher script ----
cat > "$APP_DIR/Contents/MacOS/fovea-launcher" << 'LAUNCHER'
#!/bin/bash
# Fovea launcher — sets up environment and starts the app

DIR="$(cd "$(dirname "$0")/../Resources" && pwd)"
VENV="$DIR/.venv"
SRC="$DIR/src"
LOG="/tmp/fovea-app.log"

export PYTHONDONTWRITEBYTECODE=1

# Find best Python (prefer Homebrew 3.11+ over system 3.9)
PYTHON=""
for p in /opt/homebrew/bin/python3 /usr/local/bin/python3 /usr/bin/python3; do
    if [ -x "$p" ]; then
        ver=$("$p" -c "import sys; print(sys.version_info.minor)" 2>/dev/null)
        if [ "$ver" -ge 11 ] 2>/dev/null; then
            PYTHON="$p"
            break
        fi
    fi
done
# Fallback to whatever python3 is available
[ -z "$PYTHON" ] && PYTHON=$(which python3)

# Create venv if needed
if [ ! -d "$VENV" ]; then
    echo "First launch: setting up environment (Python: $PYTHON)..." > "$LOG"

    osascript -e 'display notification "Setting up for first launch... This may take a minute." with title "Fovea"' 2>/dev/null

    "$PYTHON" -m venv "$VENV" >> "$LOG" 2>&1

    source "$VENV/bin/activate"

    # Upgrade pip first
    pip install -q --upgrade pip >> "$LOG" 2>&1

    # Core deps
    pip install -q fastapi uvicorn pillow httpx pywebview >> "$LOG" 2>&1

    # RAW support
    pip install -q rawpy >> "$LOG" 2>&1 || true

    echo "Setup complete" >> "$LOG"
else
    source "$VENV/bin/activate"
fi

cd "$SRC"
exec python3 app.py >> "$LOG" 2>&1
LAUNCHER

chmod +x "$APP_DIR/Contents/MacOS/fovea-launcher"

# ---- Copy source files ----
echo "Copying source files..."
for f in *.py; do
    cp "$f" "$APP_DIR/Contents/Resources/src/"
done
cp -r static "$APP_DIR/Contents/Resources/src/"
mkdir -p "$APP_DIR/Contents/Resources/src/data"
mkdir -p "$APP_DIR/Contents/Resources/src/thumbnails"

# ---- Copy icon ----
if [ -f "fovea.icns" ]; then
    cp fovea.icns "$APP_DIR/Contents/Resources/fovea.icns"
    # Also copy to src so app.py can find it
    cp fovea.icns "$APP_DIR/Contents/Resources/src/fovea.icns"
    /usr/libexec/PlistBuddy -c "Add :CFBundleIconFile string fovea" "$APP_DIR/Contents/Info.plist" 2>/dev/null || true
    echo "Icon: OK"
else
    echo "Icon: fovea.icns not found, run build with icon_raw.png first"
fi

# ---- Ad-hoc code signing ----
echo "Signing (ad-hoc)..."
codesign --force --deep -s - "$APP_DIR"
echo "Signed: OK"

# ---- Create DMG ----
echo "Creating DMG..."
DMG_TEMP="$BUILD_DIR/dmg_temp"
mkdir -p "$DMG_TEMP"
cp -r "$APP_DIR" "$DMG_TEMP/"

# Add Applications symlink for drag-and-drop install
ln -s /Applications "$DMG_TEMP/Applications"

hdiutil create -volname "$APP_NAME" -srcfolder "$DMG_TEMP" -ov -format UDZO "$BUILD_DIR/$DMG_NAME"
rm -rf "$DMG_TEMP"

echo ""
echo "=== Build complete ==="
echo "App:  $APP_DIR"
echo "DMG:  $BUILD_DIR/$DMG_NAME"
echo ""
echo "To install: open the DMG and drag Fovea to Applications."
echo "First launch will take ~1 minute to set up the Python environment."
echo ""
echo "To add AI analysis support after install, open Terminal and run:"
echo "  cd /Applications/Fovea.app/Contents/Resources"
echo "  source .venv/bin/activate"
echo "  pip install torch open-clip-torch insightface onnxruntime opencv-python"
