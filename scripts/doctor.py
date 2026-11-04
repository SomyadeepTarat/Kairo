"""Check local prerequisites without installing software or starting services."""

import json
import shutil
import sys
from collections.abc import Callable


def inspect_environment(
    lookup: Callable[[str], str | None] = shutil.which,
    version: tuple[int, int] = sys.version_info[:2],
) -> tuple[dict[str, bool], dict[str, bool]]:
    """Return required and informational checks; presence does not mean service readiness."""
    required = {
        "python_3_13": version == (3, 13),
        "git": lookup("git") is not None,
        "uv": lookup("uv") is not None,
    }
    optional = {name: lookup(name) is not None for name in ("node", "docker", "ollama")}
    return required, optional


def main() -> int:
    required, optional = inspect_environment()
    print(json.dumps({"required": required, "optional_cli_presence": optional}, indent=2))
    print("Docker/Ollama service readiness is not checked or required for M0.")
    return 0 if all(required.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
