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
    <string>Fovea</string>
    <key>CFBundlePackageType</key>
    <string>APPL</string>
    <key>LSMinimumSystemVersion</key>
    <string>12.0</string>
    <key>NSHighResolutionCapable</key>
    <true/>
    <key>LSUIElement</key>
    <false/>
    <key>NSPhotoLibraryUsageDescription</key>
    <string>Fovea needs access to your Photos to help you organize, analyze, and clean up your photo library.</string>
    <key>NSAppTransportSecurity</key>
    <dict>
        <key>NSAllowsLocalNetworking</key>
        <true/>
    </dict>
</dict>
</plist>
PLIST

# ---- Compile native Swift launcher ----
echo "Compiling native app..."
swiftc -O \
    -o "$APP_DIR/Contents/MacOS/Fovea" \
    -framework Cocoa \
    -framework WebKit \
    -framework Photos \
    FoveaApp.swift
echo "Compiled: OK"

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
