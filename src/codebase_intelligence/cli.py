"""Command-line entry point (initial scaffold)."""

from __future__ import annotations

import argparse


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cbi",
        description="Build a structural, token-aware map of a source repository.",
    )
    parser.add_argument("--version", action="version", version="cbi 0.1.0")
    subparsers = parser.add_subparsers(dest="command")
    scan = subparsers.add_parser("scan", help="Scan a repository (implementation pending).")
    scan.add_argument("path", nargs="?", default=".")
    subparsers.add_parser("map", help="Generate a repository map (implementation pending).")
    subparsers.add_parser("report", help="Generate an architecture report (implementation pending).")
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    if args.command is None:
        parser.print_help()
        return
    parser.error(f"'{args.command}' is designed but not implemented in this scaffold yet.")


if __name__ == "__main__":
    main()
