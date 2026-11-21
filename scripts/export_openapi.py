"""Export the actual FastAPI contract without requiring a database connection."""

import json
from pathlib import Path

from kairo_api.main import create_app
from kairo_core.persistence.repository import RunRepository


def main() -> None:
    # Engine construction performs no I/O; no successful service health is implied.
    repo = RunRepository.from_url(
        "postgresql+psycopg://kairo:kairo_local_only@127.0.0.1:55432/kairo"
    )
    path = Path("docs/api/openapi.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(create_app(repo).openapi(), indent=2) + "\n")
    print(path)


if __name__ == "__main__":
    main()
