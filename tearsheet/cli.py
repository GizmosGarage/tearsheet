"""Command entry points — the operator surface."""

from __future__ import annotations

import argparse
import sys

from tearsheet import __version__
from tearsheet.config import ensure_data_dirs
from tearsheet.pipeline import run_company_pipeline
from tearsheet.store.db import init_db


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="tearsheet",
        description="SEC EDGAR extraction pipeline",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")

    subparsers = parser.add_subparsers(dest="command", required=True)

    init_cmd = subparsers.add_parser("init", help="Initialize the local database and data dirs")
    init_cmd.set_defaults(handler=_cmd_init)

    run_cmd = subparsers.add_parser("run", help="Run the end-to-end pipeline for a ticker")
    run_cmd.add_argument("ticker", help="Stock ticker symbol (e.g. AAPL)")
    run_cmd.set_defaults(handler=_cmd_run)

    return parser


def _cmd_init(_: argparse.Namespace) -> int:
    ensure_data_dirs()
    init_db()
    print("Database and data directories ready.")
    return 0


def _cmd_run(args: argparse.Namespace) -> int:
    ensure_data_dirs()
    init_db()
    run_company_pipeline(args.ticker.upper())
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.handler(args)


if __name__ == "__main__":
    sys.exit(main())
