"""命令列入口：`uv run threads-tracker [api|bot]`."""

from __future__ import annotations

import argparse
import sys

import uvicorn

from .bot import run_polling


def main() -> None:
    parser = argparse.ArgumentParser(prog="threads-tracker")
    sub = parser.add_subparsers(dest="cmd", required=True)

    api = sub.add_parser("api", help="Run the FastAPI server (with scheduler)")
    api.add_argument("--host", default="127.0.0.1")
    api.add_argument("--port", type=int, default=8000)
    api.add_argument("--reload", action="store_true")

    sub.add_parser("bot", help="Run the Telegram bot via long polling")

    args = parser.parse_args()

    if args.cmd == "api":
        uvicorn.run(
            "threads_tracker.api:app",
            host=args.host,
            port=args.port,
            reload=args.reload,
        )
    elif args.cmd == "bot":
        run_polling()
    else:  # pragma: no cover
        parser.print_help()
        sys.exit(1)
