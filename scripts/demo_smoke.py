"""Run the real browser replay/manual smoke against a disposable pytest database.

Requires PostgreSQL 18 and `uv run playwright install chromium`. Makes no paid calls.
"""

import subprocess
import sys
from pathlib import Path

if __name__ == "__main__":
    root = Path(__file__).resolve().parents[1]
    raise SystemExit(
        subprocess.call(
            [
                sys.executable,
                "-m",
                "pytest",
                "tests/e2e/test_review_flow.py",
                "-m",
                "e2e",
                "--tb=short",
            ],
            cwd=root,
        )
    )
