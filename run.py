"""
JULIBOT dev server launcher.

This is the *reliable* way to start the app. It:
  - reads HOST/PORT from .env (single source of truth)
  - detects a port already in use (the #1 cause of "localhost refuses to connect")
  - prints a clear startup banner with the URL to open
  - starts a stable single process by default (no reloader orphan risk on Windows)

Usage:
    python run.py              # stable start (recommended)
    python run.py --reload     # hot-reload while developing
    python run.py --open       # also open the browser
    python run.py --force      # kill whatever holds the port, then start
"""

import argparse
import socket
import subprocess
import sys
from pathlib import Path

# Make sure the project root is importable even when run from elsewhere.
PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import uvicorn  # noqa: E402  (imported after sys.path setup)

from app.core.config import get_settings  # noqa: E402
from app.core.logging import setup_logging  # noqa: E402

BANNER = (
    "==========================================================\n"
    "  JULIBOT {version} — dev server\n"
    "  URL:      {url}\n"
    "  Docs:     {url}/docs\n"
    "  Env:      {environment}\n"
    "  Reload:   {reload}\n"
    "----------------------------------------------------------\n"
    "  Press CTRL+C to stop.\n"
    "=========================================================="
)


def _port_in_use(host: str, port: int) -> bool:
    """Return True if something is already listening on host:port."""
    try:
        # No SO_REUSEADDR on purpose: on Windows that flag allows a second
        # bind even when another socket is listening, which would hide the
        # very conflict we're trying to detect.
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind((host, port))
        return False
    except OSError:
        return True


def _pid_on_port(port: int) -> str | None:
    """Best-effort: return the PID listening on `port`, else None."""
    try:
        if sys.platform == "win32":
            out = subprocess.run(
                ["netstat", "-ano"], capture_output=True, text=True, timeout=10
            ).stdout
            for line in out.splitlines():
                parts = line.split()
                # TCP lines: [proto, local, foreign, state, pid]
                if (
                    len(parts) >= 5
                    and parts[0] == "TCP"
                    and parts[1].endswith(f":{port}")
                    and parts[3] == "LISTENING"
                ):
                    return parts[4]
        else:
            try:
                out = subprocess.run(
                    ["lsof", "-ti", f"tcp:{port}"],
                    capture_output=True,
                    text=True,
                    timeout=10,
                ).stdout.strip()
                if out:
                    return out.splitlines()[0]
            except FileNotFoundError:
                out = subprocess.run(
                    ["ss", "-ltnp"], capture_output=True, text=True, timeout=10
                ).stdout
                for line in out.splitlines():
                    if f":{port}" in line:
                        parts = [p for p in line.replace("pid=", "pid=").split()]
                        for p in parts:
                            if p.startswith("pid="):
                                return p.split("=")[1].split(",")[0]
    except Exception:
        return None
    return None


def _kill_pid(pid: str) -> None:
    """Force-kill a process by PID (platform-aware)."""
    try:
        if sys.platform == "win32":
            subprocess.run(["taskkill", "/PID", pid, "/F"], timeout=10)
        else:
            subprocess.run(["kill", "-9", pid], timeout=10)
        print(f"  Killed process {pid}.")
    except Exception as e:
        print(f"  Could not kill process {pid}: {e}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Start the JULIBOT dev server (reads HOST/PORT from .env)."
    )
    parser.add_argument(
        "--reload",
        action="store_true",
        help="enable hot-reload. Default is OFF because the reloader can leave "
        "orphan processes holding the port on Windows.",
    )
    parser.add_argument(
        "--no-reload",
        dest="reload",
        action="store_false",
        help="disable hot-reload (default).",
    )
    parser.add_argument(
        "--open",
        action="store_true",
        help="open the app in your default browser after startup.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="if the port is already in use, kill the process holding it and start anyway.",
    )
    parser.add_argument("--host", default=None, help="override bind address.")
    parser.add_argument("--port", type=int, default=None, help="override bind port.")
    parser.set_defaults(reload=False)
    args = parser.parse_args()

    setup_logging()
    settings = get_settings()

    host = args.host or settings.host
    port = args.port or settings.port
    url = f"http://localhost:{port}"

    # ── Port conflict handling — the #1 cause of "connection refused" ──────
    if _port_in_use(host, port):
        pid = _pid_on_port(port)
        owner = f" (PID {pid})" if pid else ""
        print(f"\n  ERROR: Port {port} is already in use{owner}.")
        print(f"  Nothing new can bind to it, so the browser will get \"connection refused\".\n")
        if args.force and pid:
            print(f"  --force given: killing PID {pid} and retrying...")
            _kill_pid(pid)
            # Give the OS a moment to release the socket.
            import time
            time.sleep(1)
        else:
            print("  Options:")
            if sys.platform == "win32":
                print(f"    taskkill /PID {pid} /F      (close the old JULIBOT first)")
            elif pid:
                print(f"    kill -9 {pid}")
            print("    or:  python run.py --force   (kill it and start anyway)")
            print("    or:  python run.py --port 8001   (use a different port)\n")
            return 1

    print(BANNER.format(
        version=settings.app_version,
        url=url,
        environment=settings.environment,
        reload="on" if args.reload else "off",
    ))
    print()

    if args.open:
        import webbrowser

        webbrowser.open(url)

    uvicorn.run(
        "app.main:app",
        host=host,
        port=port,
        reload=args.reload,
        log_level="info",
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
