#!/usr/bin/env bash
# =============================================================================
# Build script for jpeigo-slides — Linux/macOS executable
# For Windows: see build.bat
# =============================================================================
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
FRONTEND_OUT="$ROOT_DIR/backend/app/frontend"

echo "=== jpeigo-slides Portable Build ==="
echo ""

# Step 1: Build frontend
echo "═══ 1/3 Building frontend ═══"
cd "$ROOT_DIR"
npm install
npm run build
echo "  ✅ Frontend built"

# Step 2: Copy static files to backend
echo ""
echo "═══ 2/3 Copying to backend ═══"
rm -rf "$FRONTEND_OUT"
mkdir -p "$FRONTEND_OUT"
cp -r "$ROOT_DIR/out/"* "$FRONTEND_OUT/"
echo "  ✅ Copied"

# Step 3: Bundle with PyInstaller
echo ""
echo "═══ 3/3 Building executable ═══"
cd "$ROOT_DIR/backend"
pip install pyinstaller -q

pyinstaller \
  --onefile \
  --name "jpeigo-slides" \
  --add-data ".:backend" \
  --add-data "$FRONTEND_OUT:backend/app/frontend" \
  --hidden-import "uvicorn.logging" \
  --hidden-import "uvicorn.loops.auto" \
  --hidden-import "uvicorn.protocols.http.auto" \
  --hidden-import "uvicorn.protocols.websocket.auto" \
  --hidden-import "lxml._elementpath" \
  --collect-submodules "pptx" \
  --collect-submodules "lxml" \
  --add-data ".env.example:." \
  --add-data "app/templates/setup.html:app/templates" \
  app/run.py

echo ""
echo "═══ Build Complete ═══"
echo "Executable: $ROOT_DIR/backend/dist/jpeigo-slides"
echo ""
echo "To ship:"
echo "  1. mkdir jpeigo-slides-portable"
echo "  2. cp backend/dist/jpeigo-slides jpeigo-slides-portable/"
echo "  3. cp backend/.env.example jpeigo-slides-portable/"
echo "  4. cd jpeigo-slides-portable && mkdir backend && mv .env.example backend/"
echo "  5. zip -r jpeigo-slides-windows.zip jpeigo-slides-portable/"
