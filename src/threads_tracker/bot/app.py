"""Telegram Application bootstrap."""

from __future__ import annotations

from telegram.ext import Application, ApplicationBuilder, CommandHandler

from ..config import get_settings
from ..logging import configure_logging, get_logger
from . import handlers

logger = get_logger(__name__)


def build_application() -> Application:
    s = get_settings()
    if not s.telegram_bot_token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is not configured")

    app = ApplicationBuilder().token(s.telegram_bot_token).build()
    app.add_handler(CommandHandler("start", handlers.start_cmd))
    app.add_handler(CommandHandler("help", handlers.help_cmd))
    # v3 placeholder commands — wired in M4 / M5 / M6
    for name in ("feed", "saved", "ask", "exit", "digest", "timeline"):
        app.add_handler(CommandHandler(name, handlers.deferred_cmd))
    return app


def run_polling() -> None:
    """Run the Telegram bot via long polling. Blocks the calling thread."""
    configure_logging()
    app = build_application()
    logger.info("bot.start_polling")
    app.run_polling()
