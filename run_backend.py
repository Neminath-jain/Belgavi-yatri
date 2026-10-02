"""
Launcher script for the NWKRTC Belagavi Division Live Tracker FastAPI backend.
Usage:
    python run_backend.py
"""

import os
import sys
import uvicorn

if __name__ == "__main__":
    # Ensure current working directory is in sys.path
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

    host = os.getenv("API_HOST", "0.0.0.0")
    port = int(os.getenv("API_PORT", "8000"))
    reload = os.getenv("API_RELOAD", "True").lower() in ("true", "1", "yes")

    print("=" * 70)
    print("  NWKRTC Belagavi Division Live Tracker — FastAPI Backend")
    print(f"  Server URL:    http://localhost:{port}")
    print(f"  Swagger Docs:  http://localhost:{port}/docs")
    print(f"  ReDoc Docs:    http://localhost:{port}/redoc")
    print("=" * 70)

    uvicorn.run(
        "backend.main:app",
        host=host,
        port=port,
        reload=reload,
        log_level="info",
    )
