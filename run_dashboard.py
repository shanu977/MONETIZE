#!/usr/bin/env python3
"""MONETIZE Admin Dashboard — Single-command launcher.

Starts FastAPI backend (CCTV + Zones + Customers + Mock APIs) and serves
the Vite-built frontend at http://127.0.0.1:8000

Usage:
    python run_dashboard.py
    python run_dashboard.py --port 8000 --host 127.0.0.1

Requires: pip install -r requirements.txt && cd dashboard && npm run build
"""
import argparse
import subprocess
import sys
from pathlib import Path

def main():
    parser = argparse.ArgumentParser(description="MONETIZE Admin Dashboard")
    parser.add_argument("--host", default="127.0.0.1", help="Host")
    parser.add_argument("--port", type=int, default=8000, help="Port")
    parser.add_argument("--reload", action="store_true", help="Auto-reload for dev")
    args = parser.parse_args()

    # Ensure frontend is built
    dist = Path("dashboard/dist/index.html")
    if not dist.exists():
        print("Frontend not built. Building... (npm run build)")
        subprocess.run(["npm", "run", "build"], cwd="dashboard", check=False, shell=True)

    print(f"""
╔════════════════════════════════════════════════════╗
║  MONETIZE — Admin Dashboard                        ║
║  http://{args.host}:{args.port}/                            ║
║                                                    ║
║  API docs: http://{args.host}:{args.port}/docs                ║
║  CCTV: test 1.mp4 (DEMO) → future RTSP             ║
║  Zones: zones/<map_id>.json via ZoneManager        ║
╚════════════════════════════════════════════════════╝
""")
    import uvicorn
    uvicorn.run("app.api.main:app", host=args.host, port=args.port, reload=args.reload)

if __name__ == "__main__":
    main()
