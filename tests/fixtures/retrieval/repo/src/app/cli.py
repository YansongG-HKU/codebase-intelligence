"""Command line entry point."""

from app.core import build_context, rank_files


def main(argv=None):
    """Run the command line interface."""
    return build_context(argv)


def _internal():
    return rank_files([])
