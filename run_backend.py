#!/usr/bin/env python3
"""
Convenience entry point to run Synesis Backend server.
Usage:
    python run_backend.py
    python run_backend.py --port 8000 --reload
"""
import os
import sys
from pathlib import Path

# Ensure backend directory is in sys.path
backend_dir = Path(__file__).resolve().parent / "backend"
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("PORT", 8000))
    host = os.environ.get("HOST", "127.0.0.1")
    reload = os.environ.get("RELOAD", "true").lower() in ("true", "1", "yes")

    print(f"Starting Synesis Backend on http://{host}:{port}...")
    uvicorn.run("app.main:app", host=host, port=port, reload=reload)
