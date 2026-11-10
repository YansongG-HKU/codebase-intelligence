"""``python -m codebase_intelligence.mcp [ROOT]`` companion entry point."""

from __future__ import annotations

import os
import sys

from codebase_intelligence import api
from codebase_intelligence.mcp.server import serve
from codebase_intelligence.util import force_utf8_stdio


def main() -> None:
    force_utf8_stdio()
    raw = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("CBI_ROOT") or "."
    root = api.resolve_root(raw)
    serve(root)


if __name__ == "__main__":
    main()
