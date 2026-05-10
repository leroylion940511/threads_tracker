"""Telegram 指令 handlers.

v3 架構下，使用者不再用 /track <url> 加追蹤，而是被推送 Top 5 後按 ❤️ 升格 candidate。
v1 的 track / list / untrack / poll / digest / timeline 在 M4 重寫前先 stub。
"""

from __future__ import annotations

from sqlalchemy import select
from telegram import Update
from telegram.ext import ContextTypes

from ..db import session_scope
from ..logging import get_logger
from ..models import User

logger = get_logger(__name__)

HELP_TEXT = (
    "Threads Tracker 指令（v3 過渡期）：\n"
    "/start             註冊\n"
    "/help              顯示說明\n"
    "/feed              查看每日推送（M4 上線）\n"
    "/saved             查看已收藏（M5 上線）\n"
    "/ask <id>          進入問答模式（M6 上線）\n"
    "/exit              退出問答模式（M6 上線）"
)

_DEFERRED_MSG = "這個功能還沒上線，等之後的里程碑開放。"


async def _get_or_create_user(session, update: Update) -> User:
    chat = update.effective_chat
    if chat is None:
        raise RuntimeError("update without chat")
    stmt = select(User).where(User.telegram_chat_id == chat.id)
    user = (await session.execute(stmt)).scalar_one_or_none()
    if user is None:
        user = User(
            telegram_chat_id=chat.id,
            telegram_username=update.effective_user.username
            if update.effective_user
            else None,
        )
        session.add(user)
        await session.flush()
    return user


async def start_cmd(update: Update, _context: ContextTypes.DEFAULT_TYPE) -> None:
    async with session_scope() as session:
        await _get_or_create_user(session, update)
    await update.effective_message.reply_text(
        "嗨！這裡是 Threads 熱點追蹤 Bot（v3 開發中）。\n\n" + HELP_TEXT
    )


async def help_cmd(update: Update, _context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.effective_message.reply_text(HELP_TEXT)


async def deferred_cmd(update: Update, _context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.effective_message.reply_text(_DEFERRED_MSG)
