"""Run the deterministic retrieval-only benchmark.

Example:
    python scripts/eval_retrieval.py --root tests/fixtures/retrieval/repo
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from codebase_intelligence.evaluation import evaluate_repository, load_task_set

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_TASKS = ROOT / "bench" / "retrieval_tasks.v1.json"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default="tests/fixtures/retrieval/repo")
    parser.add_argument("--tasks", default=str(DEFAULT_TASKS))
    parser.add_argument("--cache-dir", default=None)
    parser.add_argument("--k", type=int, nargs="+", default=[1, 3, 5])
    parser.add_argument(
        "--compare-baselines",
        action="store_true",
        help="compare tree-only, keyword, pack-order and basic symbol-map baselines",
    )
    parser.add_argument("--json-out", default=None)
    args = parser.parse_args(argv)

    try:
        tasks = load_task_set(args.tasks)
        report = evaluate_repository(
            args.root,
            tasks,
            cache_dir=args.cache_dir,
            ks=args.k,
            compare_baselines=args.compare_baselines,
        )
    except (OSError, ValueError, RuntimeError) as exc:
        parser.error(str(exc))
    rendered = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.json_out:
        target = Path(args.json_out)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(rendered, encoding="utf-8", newline="\n")
    else:
        sys.stdout.write(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
