"""Build the static GitHub Pages bundle from the verified datasets.

Output goes to ``_site/`` and contains the JSON datasets plus a small,
dependency-free client that renders them and refuses to calculate with rates
older than ``max_age_hours``.
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

from .validate_data import validate_banks, validate_cbu

ROOT = Path(__file__).resolve().parent.parent
SITE_SRC = ROOT / "site"
DATA_FILES = ("data/banks.json", "data/cbu.json")
OUTPUT = ROOT / "_site"


def build(output: Path = OUTPUT) -> Path:
    validate_banks(ROOT / "data" / "banks.json")
    validate_cbu(ROOT / "data" / "cbu.json")

    if output.exists():
        shutil.rmtree(output)
    output.mkdir(parents=True)
    (output / "data").mkdir()

    for name in ("index.html", "app.js", "styles.css"):
        shutil.copy2(SITE_SRC / name, output / name)
    for name in DATA_FILES:
        shutil.copy2(ROOT / name, output / name)

    # Disable Jekyll processing so files are served verbatim.
    (output / ".nojekyll").write_text("", encoding="utf-8")
    return output


def main() -> int:
    try:
        path = build()
    except SystemExit as error:  # raised by validate_*
        return int(error.code or 1)
    print(f"built static bundle at {path.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
