from codebase_intelligence.cli import build_parser


def test_cli_help_parser() -> None:
    parser = build_parser()
    args = parser.parse_args(["scan", "."])
    assert args.command == "scan"
    assert args.path == "."
