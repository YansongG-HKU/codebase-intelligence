"""Entry point of the demo application fixture."""

from __future__ import annotations

from app.services import create_default_service
from app.util import format_header


def main() -> int:
    """Print every task known to the default service."""

    service = create_default_service()
    print(format_header("Tasks"))
    for line in service.describe():
        print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
