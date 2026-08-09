"""
Prepare the frontend for the Vercel build.

Copies the static site from ``src/`` into ``public/`` so Vercel serves
index.html, css/, js/, and assets/ from the CDN while the FastAPI function
handles the /api routes. Only the frontend files are copied — nothing else.
"""

import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
PUBLIC = ROOT / "public"

COPY_ITEMS = ("index.html", "css", "js", "assets")


def main() -> None:
    if not SRC.exists():
        raise SystemExit(f"Frontend source not found: {SRC}")

    if PUBLIC.exists():
        shutil.rmtree(PUBLIC)
    PUBLIC.mkdir(parents=True)

    for item in COPY_ITEMS:
        src = SRC / item
        if src.exists():
            dst = PUBLIC / item
            if src.is_dir():
                shutil.copytree(src, dst, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
            else:
                shutil.copy2(src, dst)

    print(f"Frontend copied: {SRC} -> {PUBLIC}")


if __name__ == "__main__":
    main()
