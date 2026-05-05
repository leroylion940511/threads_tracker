"""Telegram 指令 handlers (proposal §4.5)."""

from __future__ import annotations

from sqlalchemy import select
from telegram import Update
from telegram.ext import ContextTypes

from ..db import session_scope
from ..llm.factory import get_summarizer
from ..logging import get_logger
from ..models import DetectionSource, PostStatus, Subscription, TrackedPost, User
from ..scrapers.base import parse_threads_url
from ..scrapers.factory import get_fetcher
from ..services.summarization import (
    SummarizationService,
    TimelineItem,
    parse_evolution,
)
from ..services.tracking import TrackingService

logger = get_logger(__name__)

HELP_TEXT = (
    "Threads Tracker 指令：\n"
    "/track <連結>      加入新貼文到追蹤清單\n"
    "/list              列出目前所有追蹤中的貼文\n"
    "/untrack <id>      移除追蹤\n"
    "/poll <id>         立即重抓一次（demo 用，平常由排程器處理）\n"
    "/digest <id>       立即產生指定貼文的當下摘要\n"
    "/timeline <id>     查看該貼文事件時間軸\n"
    "/settings          調整推播偏好\n"
    "/explore           瀏覽自動偵測候選\n"
    "/help              顯示說明"
)


async def _get_or_create_user(session, update: Update) -> User:
    chat = update.effective_chat
    if chat is None:
        raise RuntimeError("update without chat")
    stmt = select(User).where(User.telegram_chat_id == chat.id)
    user = (await session.execute(stmt)).scalar_one_or_none()
    if user is None:
        user = User(
            telegram_chat_id=chat.id,
            telegram_username=update.effective_user.username if update.effective_user else None,
        )
        session.add(user)
        await session.flush()
    return user


async def start_cmd(update: Update, _context: ContextTypes.DEFAULT_TYPE) -> None:
    async with session_scope() as session:
        await _get_or_create_user(session, update)
    await update.effective_message.reply_text(
        "嗨！這裡是 Threads 熱點追蹤 Bot。\n\n" + HELP_TEXT
    )


async def help_cmd(update: Update, _context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.effective_message.reply_text(HELP_TEXT)


async def track_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.effective_message.reply_text("用法：/track <Threads 貼文連結>")
        return
    url = context.args[0]
    try:
        parse_threads_url(url)
    except ValueError as e:
        await update.effective_message.reply_text(f"連結格式不正確：{e}")
        return

    fetcher = get_fetcher()
    async with session_scope() as session:
        user = await _get_or_create_user(session, update)
        service = TrackingService(session, fetcher)
        try:
            tracked = await service.add_tracked_post(url, source=DetectionSource.MANUAL)
        except Exception as exc:  # noqa: BLE001
            logger.error("bot.track_failed", error=str(exc))
            await update.effective_message.reply_text(f"加入失敗：{exc}")
            return

        sub_exists = await session.execute(
            select(Subscription).where(
                Subscription.user_id == user.id,
                Subscription.tracked_post_id == tracked.id,
            )
        )
        if sub_exists.scalar_one_or_none() is None:
            session.add(Subscription(user_id=user.id, tracked_post_id=tracked.id))

    await update.effective_message.reply_text(
        f"已加入追蹤 #{tracked.id}\n@{tracked.author_username}: {tracked.original_content[:80]}…"
    )


async def list_cmd(update: Update, _context: ContextTypes.DEFAULT_TYPE) -> None:
    async with session_scope() as session:
        user = await _get_or_create_user(session, update)
        stmt = (
            select(TrackedPost)
            .join(Subscription, Subscription.tracked_post_id == TrackedPost.id)
            .where(
                Subscription.user_id == user.id,
                TrackedPost.status == PostStatus.ACTIVE.value,
            )
            .order_by(TrackedPost.detected_at.desc())
        )
        rows = list((await session.execute(stmt)).scalars().all())

    if not rows:
        await update.effective_message.reply_text("追蹤清單是空的。用 /track <連結> 開始。")
        return
    lines = [
        f"#{r.id} @{r.author_username} [{r.polling_tier}]\n  {r.post_url}"
        for r in rows
    ]
    await update.effective_message.reply_text("\n\n".join(lines))


async def untrack_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.effective_message.reply_text("用法：/untrack <id>")
        return
    try:
        tracked_id = int(context.args[0])
    except ValueError:
        await update.effective_message.reply_text("id 必須是數字")
        return

    async with session_scope() as session:
        user = await _get_or_create_user(session, update)
        sub = (
            await session.execute(
                select(Subscription).where(
                    Subscription.user_id == user.id,
                    Subscription.tracked_post_id == tracked_id,
                )
            )
        ).scalar_one_or_none()
        if sub is None:
            await update.effective_message.reply_text(f"沒有訂閱 #{tracked_id}")
            return
        await session.delete(sub)

    await update.effective_message.reply_text(f"已取消訂閱 #{tracked_id}")


async def poll_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """手動觸發單一貼文的一次重抓 — 主要給 demo 用，平常由排程器處理."""
    if not context.args:
        await update.effective_message.reply_text("用法：/poll <id>")
        return
    try:
        tracked_id = int(context.args[0])
    except ValueError:
        await update.effective_message.reply_text("id 必須是數字")
        return

    fetcher = get_fetcher()
    async with session_scope() as session:
        user = await _get_or_create_user(session, update)
        if not await _user_subscribed(session, user.id, tracked_id):
            await update.effective_message.reply_text(f"沒有訂閱 #{tracked_id}")
            return
        tracked = await session.get(TrackedPost, tracked_id)
        if tracked is None:
            await update.effective_message.reply_text(f"找不到 #{tracked_id}")
            return
        service = TrackingService(session, fetcher)
        try:
            snapshot = await service.poll_once(tracked)
        except Exception as exc:  # noqa: BLE001
            logger.error("bot.poll_failed", tracked_id=tracked_id, error=str(exc))
            await update.effective_message.reply_text(f"重抓失敗：{exc}")
            return

    await update.effective_message.reply_text(
        f"已重抓 #{tracked_id}：{snapshot.like_count or 0} 讚 / "
        f"{snapshot.reply_count or 0} 留言"
    )


async def digest_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.effective_message.reply_text("用法：/digest <id>")
        return
    try:
        tracked_id = int(context.args[0])
    except ValueError:
        await update.effective_message.reply_text("id 必須是數字")
        return

    try:
        summarizer = get_summarizer()
    except (RuntimeError, ValueError) as exc:
        await update.effective_message.reply_text(f"摘要服務未啟用：{exc}")
        return

    async with session_scope() as session:
        user = await _get_or_create_user(session, update)
        if not await _user_subscribed(session, user.id, tracked_id):
            await update.effective_message.reply_text(f"沒有訂閱 #{tracked_id}")
            return

        service = SummarizationService(session, summarizer)
        try:
            record = await service.get_or_create_evolution(tracked_id)
        except Exception as exc:  # noqa: BLE001
            logger.error("bot.digest_failed", tracked_id=tracked_id, error=str(exc))
            await update.effective_message.reply_text(f"產生摘要失敗：{exc}")
            return

        if record is None:
            await update.effective_message.reply_text(f"找不到 #{tracked_id}")
            return

        tracked = await session.get(TrackedPost, tracked_id)
        summary = parse_evolution(record)
        text = _format_evolution(tracked, record, summary)

    await update.effective_message.reply_text(text)


async def timeline_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.effective_message.reply_text("用法：/timeline <id>")
        return
    try:
        tracked_id = int(context.args[0])
    except ValueError:
        await update.effective_message.reply_text("id 必須是數字")
        return

    async with session_scope() as session:
        user = await _get_or_create_user(session, update)
        if not await _user_subscribed(session, user.id, tracked_id):
            await update.effective_message.reply_text(f"沒有訂閱 #{tracked_id}")
            return
        service = SummarizationService(session)
        items = await service.build_timeline(tracked_id)

    if not items:
        await update.effective_message.reply_text(f"#{tracked_id} 還沒有時間軸資料。")
        return
    await update.effective_message.reply_text(_format_timeline(tracked_id, items))


async def _user_subscribed(session, user_id: int, tracked_id: int) -> bool:
    sub = await session.execute(
        select(Subscription).where(
            Subscription.user_id == user_id,
            Subscription.tracked_post_id == tracked_id,
        )
    )
    return sub.scalar_one_or_none() is not None


def _format_evolution(tracked: TrackedPost | None, record, summary) -> str:
    header = f"📌 #{record.tracked_post_id}"
    if tracked is not None:
        header = f"📌 #{tracked.id} @{tracked.author_username}"
    generated = record.generated_at
    ts = generated.strftime("%Y-%m-%d %H:%M") if generated else "—"
    lines = [header, f"（摘要產生於 {ts}）", "", summary.narrative]
    if summary.milestones:
        lines.append("")
        lines.append("關鍵節點：")
        lines.extend(f"• {m}" for m in summary.milestones)
    return "\n".join(lines)


def _format_timeline(tracked_id: int, items: list[TimelineItem]) -> str:
    lines = [f"⏱ #{tracked_id} 時間軸"]
    for it in items:
        ts = it.occurred_at.strftime("%m-%d %H:%M")
        if it.detail:
            lines.append(f"[{ts}] {it.title} — {it.detail}")
        else:
            lines.append(f"[{ts}] {it.title}")
    return "\n".join(lines)


async def settings_cmd(update: Update, _context: ContextTypes.DEFAULT_TYPE) -> None:
    # TODO Week 5: 推播偏好設定
    await update.effective_message.reply_text("偏好設定將於第五週上線。")


async def explore_cmd(update: Update, _context: ContextTypes.DEFAULT_TYPE) -> None:
    # TODO Week 5: 自動偵測候選清單
    await update.effective_message.reply_text("自動偵測候選將於第五週上線。")
