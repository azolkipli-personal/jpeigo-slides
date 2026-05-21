"""
jpeigo-slides — Portable launcher entry point.
Used by PyInstaller to create a standalone executable.
"""
import os
import sys
import webbrowser
from pathlib import Path


# Determine the app root directory
if getattr(sys, 'frozen', False):
    # PyInstaller bundle: resources are extracted to MEIPASS
    BASE_DIR = Path(sys._MEIPASS)
    # Change CWD to the executable's directory so .env and uploads are local
    os.chdir(Path(sys.executable).parent)
else:
    # Running from source
    BASE_DIR = Path(__file__).parent
    os.chdir(BASE_DIR)

# Ensure backend modules are importable
sys.path.insert(0, str(BASE_DIR))

# Load .env from the executable's working directory
env_path = Path.cwd() / "backend" / ".env"
if not env_path.exists():
    # Also check next to the executable itself
    env_path = Path.cwd() / ".env"
if env_path.exists():
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())

# Change into backend directory so relative paths (uploads/, outputs/) work
os.chdir(BASE_DIR)

import uvicorn


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8002))
    print()
    print("  ╔══════════════════════════════════════════╗")
    print("  ║        jpeigo-slides  v1.0.0             ║")
    print("  ║  PPTX Translator — English ↔ Japanese    ║")
    print("  ╠══════════════════════════════════════════╣")
    print(f"  ║  Open:  http://localhost:{port}/           ║")
    print(f"  ║  Setup: http://localhost:{port}/setup      ║")
    print("  ╚══════════════════════════════════════════╝")
    print("  Press Ctrl+C to stop the server.")
    print()
    webbrowser.open(f"http://localhost:{port}/")
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=port,
        reload=False,
        log_level="info",
    )
