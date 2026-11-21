"""Start the trusted-local API, worker, coordinator and evaluation consumer."""

import os

import uvicorn


def main() -> None:
    os.environ.setdefault("KAIRO_EMBEDDED_WORKER", "1")
    uvicorn.run("kairo_api.main:create_app", factory=True, host="127.0.0.1", port=8000)


if __name__ == "__main__":
    main()
