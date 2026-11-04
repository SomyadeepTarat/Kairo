"""Run the same local foundation checks for both contributors; stop on failure."""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMMANDS = (
    ("ruff", "format", "--check", "."),
    ("ruff", "check", "."),
    ("mypy",),
    ("pytest",),
)


def main() -> int:
    for arguments in COMMANDS:
        print(f"Checking: {' '.join(arguments)}", flush=True)
        result = subprocess.run([sys.executable, "-m", *arguments], cwd=ROOT, check=False)
        if result.returncode:
            return result.returncode
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
