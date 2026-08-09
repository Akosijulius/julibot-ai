"""
Support running the app as a module:  python -m app

Delegates to the shared launcher (run.py) so behavior — reading HOST/PORT
from .env, port-conflict detection, the startup banner — stays identical
no matter which command you use.
"""

import sys
from pathlib import Path

# Ensure the project root is on sys.path so `from run import main` resolves.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from run import main as run_server  # noqa: E402


if __name__ == "__main__":
    sys.exit(run_server())
