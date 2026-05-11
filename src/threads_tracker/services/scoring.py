"""評分層 — v3 §4.2 三段式：硬規則 → Haiku → 加權合併.

公開介面：
    apply_hard_rules(candidate)         → RulesResult     （第一段，純規則）
    combine_final(rules, haiku)         → FinalScore      （第三段，加權）
    ScoringService(session, classifier)
        .score_candidate(candidate_id)  → ScoringOutcome  （三段一氣呵成 + 寫表）
        .score_pending(limit=...)       → list[outcomes]  （給 scheduler 用）

scoring_records 三段寫入；每段獨立 cost_usd。失敗策略：
    - rules 不通過 → 立刻寫 RULES row（passed=False）並回傳，不呼叫 Haiku。
    - Haiku 失敗 → 寫 HAIKU row（passed=None, details={'error': ...}）後跳過 FINAL。
    - 同一 candidate 重複呼叫 score_candidate 會直接返回既有 FINAL（idempotent）。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..llm.haiku import CandidateScore, HaikuClassifier
from ..logging import get_logger
from ..models import (
    CandidatePost,
    LLMPurpose,
    LLMRecord,
    ScoringRecord,
    ScoringStage,
)

logger = get_logger(__name__)


# --- 規則參數（之後可拉到 config） ----------------------------------------

#: 互動速度（likes+replies / hour）下限；低於此值代表沒人理。
VELOCITY_MIN_PER_HOUR: float = 30.0

#: 互動速度上限——超過此值映射到 1.0（避免極端值主宰加權）。
VELOCITY_NORMALIZATION_CAP: float = 300.0

#: 作者粉絲上限——超過視為「已是中型 KOL」，不在素人探勘範圍。
AUTHOR_FOLLOWER_MAX: int = 10_000

#: 內文長度區間（按字元數）。
CONTENT_LENGTH_MIN: int = 30
CONTENT_LENGTH_MAX: int = 500

#: 業配黑名單（任一命中即視為業配）。寬鬆過濾，誤殺可接受。
SPONSORED_PATTERNS: tuple[str, ...] = (
    "業配", "業配文", "合作邀稿", "邀稿", "贊助", "廠商提供",
    "團購", "代購", "蝦皮分潤", "聯盟連結", "affiliate",
    "#AD", "#ad", "#PR", "#pr", "#sponsored",
)

#: 加權公式（v3 §4.2 第三層）：final = 0.4·v + 0.3·s + 0.2·g + 0.1·n
WEIGHT_VELOCITY: float = 0.4
WEIGHT_SEMANTIC: float = 0.3
WEIGHT_GRASSROOTS: float = 0.2
WEIGHT_NOVELTY: float = 0.1

#: Haiku verdict 為 "track" 且 final_score 至少這個門檻才視為通過。
FINAL_SCORE_PASS_THRESHOLD: float = 0.5


# --- 繁中偵測（簡 vs 繁字符比對） ------------------------------------------

# 注意：刻意只列「常用簡繁差異字」，足以拒掉純簡體內容；
# 對混排或港式詞彙不會誤殺。完整轉換建議導入 opencc，目前不引依賴。
_SIMPLIFIED_MARKERS = frozenset(
    "这说为来国对时个会发点过还问没让从话给样开经现办间认识东"
    "应该机长见贵贱体买卖车马鸡鱼鸟龙风电龟无与产业园专门联归"
    "听经历独议责讲讨论营运转换续传统总线键键盘称称呼觉资讯"
)
_TRADITIONAL_MARKERS = frozenset(
    "這說為來國對時個會發點過還問沒讓從話給樣開經現辦間認識東"
    "應該機長見貴賤體買賣車馬雞魚鳥龍風電龜無與產業園專門聯歸"
    "聽經歷獨議責講討論營運轉換續傳統總線鍵鍵盤稱稱呼覺資訊"
)
_CJK_RE = re.compile(r"[一-鿿]")


def _is_traditional_chinese(text: str) -> tuple[bool, dict[str, int]]:
    """繁中啟發式：CJK 字佔比 ≥ 30% 且繁體標記字 ≥ 簡體標記字。"""
    if not text:
        return False, {"han": 0, "trad": 0, "simp": 0}
    han = sum(1 for c in text if _CJK_RE.match(c))
    trad = sum(1 for c in text if c in _TRADITIONAL_MARKERS)
    simp = sum(1 for c in text if c in _SIMPLIFIED_MARKERS)
    stats = {"han": han, "trad": trad, "simp": simp, "length": len(text)}
    if han == 0:
        return False, stats
    if han / max(1, len(text)) < 0.30:
        return False, stats
    # 簡體標記字明顯多於繁體 → 判為非繁中
    if simp > trad and simp >= 3:
        return False, stats
    return True, stats


def _contains_sponsored_marker(text: str) -> tuple[bool, list[str]]:
    if not text:
        return False, []
    hits = [pat for pat in SPONSORED_PATTERNS if pat in text]
    return bool(hits), hits


# --- 規則結果 / Haiku 結果 / 最終分 ---------------------------------------


@dataclass(slots=True)
class RulesResult:
    """硬規則層輸出；passed=False 時 reason 標明哪條沒過."""

    passed: bool
    velocity_per_hour: float
    velocity_normalized: float  # 0..1 — 進加權公式的 v
    reason: str | None
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class FinalScore:
    """第三段加權合併輸出."""

    velocity: float       # v
    semantic: float       # s
    grassroots: float     # g
    novelty: float        # n
    final_score: float    # 0..1
    passed: bool          # final ≥ threshold AND haiku verdict == track


@dataclass(slots=True)
class ScoringOutcome:
    """`score_candidate` 的回傳值——三段都包."""

    candidate_id: int
    rules: RulesResult
    haiku: CandidateScore | None
    final: FinalScore | None


# --- 第一段：硬規則 -------------------------------------------------------


def apply_hard_rules(
    candidate: CandidatePost, *, now: datetime | None = None
) -> RulesResult:
    """提案 §4.2 第一層：互動速度 / 粉絲 / 繁中 / 長度 / 業配."""
    now = now or datetime.now(timezone.utc)
    content = candidate.content or ""
    details: dict[str, Any] = {}

    # 1) 互動速度
    posted_at = candidate.posted_at
    if posted_at is None:
        # 沒 posted_at 退而求其次用 discovered_at；舊資料偶見，記錄起來
        posted_at = candidate.discovered_at
        details["posted_at_fallback"] = "discovered_at"
    if posted_at.tzinfo is None:
        posted_at = posted_at.replace(tzinfo=timezone.utc)
    age_hours = max(0.25, (now - posted_at).total_seconds() / 3600.0)
    interactions = (candidate.initial_likes or 0) + (candidate.initial_replies or 0)
    velocity = interactions / age_hours
    velocity_norm = min(1.0, velocity / VELOCITY_NORMALIZATION_CAP)
    details["velocity_per_hour"] = round(velocity, 2)
    details["velocity_normalized"] = round(velocity_norm, 4)
    details["age_hours"] = round(age_hours, 2)
    details["interactions"] = interactions

    if velocity < VELOCITY_MIN_PER_HOUR:
        return RulesResult(
            passed=False,
            velocity_per_hour=velocity,
            velocity_normalized=velocity_norm,
            reason=f"velocity_too_low:{velocity:.1f}<{VELOCITY_MIN_PER_HOUR}",
            details=details,
        )

    # 2) 作者粉絲（None 視為「未知 → 給通過，details 標記」）
    follower = candidate.author_follower_count
    details["author_follower_count"] = follower
    if follower is not None and follower > AUTHOR_FOLLOWER_MAX:
        return RulesResult(
            passed=False,
            velocity_per_hour=velocity,
            velocity_normalized=velocity_norm,
            reason=f"author_too_big:{follower}>{AUTHOR_FOLLOWER_MAX}",
            details=details,
        )

    # 3) 文字長度
    length = len(content)
    details["content_length"] = length
    if length < CONTENT_LENGTH_MIN or length > CONTENT_LENGTH_MAX:
        return RulesResult(
            passed=False,
            velocity_per_hour=velocity,
            velocity_normalized=velocity_norm,
            reason=f"length_out_of_range:{length}",
            details=details,
        )

    # 4) 繁中
    is_trad, trad_stats = _is_traditional_chinese(content)
    details["chinese_stats"] = trad_stats
    if not is_trad:
        return RulesResult(
            passed=False,
            velocity_per_hour=velocity,
            velocity_normalized=velocity_norm,
            reason="not_traditional_chinese",
            details=details,
        )

    # 5) 業配黑名單
    is_sponsored, hits = _contains_sponsored_marker(content)
    if is_sponsored:
        details["sponsored_markers"] = hits
        return RulesResult(
            passed=False,
            velocity_per_hour=velocity,
            velocity_normalized=velocity_norm,
            reason=f"sponsored_marker:{hits[0]}",
            details=details,
        )

    return RulesResult(
        passed=True,
        velocity_per_hour=velocity,
        velocity_normalized=velocity_norm,
        reason=None,
        details=details,
    )


# --- 第三段：加權合併 -----------------------------------------------------


def combine_final(rules: RulesResult, haiku: CandidateScore) -> FinalScore:
    """v3 §4.2 公式：final = 0.4·v + 0.3·s + 0.2·g + 0.1·n.

    s = (story_potential + emotional_pull) / 2   ← Haiku 5 軸中與「敘事+情緒」相關的兩軸
    g = grassroots
    n = novelty
    authenticity 不進加權；做為 verdict 條件之一（Haiku 自己判完）.
    """
    v = rules.velocity_normalized
    s = (haiku.story_potential + haiku.emotional_pull) / 2
    g = haiku.grassroots
    n = haiku.novelty
    final = (
        WEIGHT_VELOCITY * v
        + WEIGHT_SEMANTIC * s
        + WEIGHT_GRASSROOTS * g
        + WEIGHT_NOVELTY * n
    )
    passed = haiku.verdict == "track" and final >= FINAL_SCORE_PASS_THRESHOLD
    return FinalScore(
        velocity=v,
        semantic=s,
        grassroots=g,
        novelty=n,
        final_score=round(final, 4),
        passed=passed,
    )


# --- ScoringService（orchestration + DB 寫入） -----------------------------


class ScoringService:
    def __init__(
        self,
        session: AsyncSession,
        classifier: HaikuClassifier | None = None,
    ) -> None:
        self._session = session
        self._classifier = classifier  # 允許 None（純規則模式 / 測試）

    async def score_candidate(
        self,
        candidate_id: int,
        *,
        now: datetime | None = None,
    ) -> ScoringOutcome:
        """三段一氣呵成；同一 candidate 若已有 FINAL row 直接 short-circuit."""
        candidate = await self._session.get(CandidatePost, candidate_id)
        if candidate is None:
            raise ValueError(f"Candidate #{candidate_id} not found")

        if await self._has_final_record(candidate_id):
            logger.debug("scoring.skip_already_final", candidate_id=candidate_id)
            return await self._reload_outcome(candidate)

        # 第一段：規則
        rules = apply_hard_rules(candidate, now=now)
        await self._write_record(
            candidate_id=candidate_id,
            stage=ScoringStage.RULES,
            passed=rules.passed,
            score=rules.velocity_normalized,
            details={"reason": rules.reason, **rules.details},
            cost_usd=Decimal("0"),
        )
        if not rules.passed:
            await self._session.commit()
            logger.info(
                "scoring.rules_rejected",
                candidate_id=candidate_id,
                reason=rules.reason,
            )
            return ScoringOutcome(candidate_id, rules, None, None)

        # 第二段：Haiku
        if self._classifier is None:
            # 沒接 LLM 就只跑規則層；details 留訊息
            await self._session.commit()
            logger.warning(
                "scoring.no_classifier", candidate_id=candidate_id
            )
            return ScoringOutcome(candidate_id, rules, None, None)

        haiku_result: CandidateScore | None
        try:
            haiku_result = await self._classifier.score_candidate(
                content=candidate.content or "",
                author_username=candidate.author_username,
                follower_count=candidate.author_follower_count,
            )
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "scoring.haiku_failed",
                candidate_id=candidate_id,
                error=str(exc),
            )
            await self._write_record(
                candidate_id=candidate_id,
                stage=ScoringStage.HAIKU,
                passed=None,
                score=None,
                details={"error": str(exc)},
                cost_usd=Decimal("0"),
            )
            await self._session.commit()
            return ScoringOutcome(candidate_id, rules, None, None)

        await self._write_record(
            candidate_id=candidate_id,
            stage=ScoringStage.HAIKU,
            passed=haiku_result.verdict == "track",
            score=haiku_result.overall(),
            details=haiku_result.to_dict(),
            cost_usd=Decimal(str(haiku_result.cost_usd)),
        )
        await self._write_llm_record(candidate_id, haiku_result)

        # 第三段：加權
        final = combine_final(rules, haiku_result)
        await self._write_record(
            candidate_id=candidate_id,
            stage=ScoringStage.FINAL,
            passed=final.passed,
            score=final.final_score,
            details={
                "v": final.velocity,
                "s": final.semantic,
                "g": final.grassroots,
                "n": final.novelty,
                "haiku_verdict": haiku_result.verdict,
                "threshold": FINAL_SCORE_PASS_THRESHOLD,
            },
            cost_usd=None,
        )
        await self._session.commit()
        logger.info(
            "scoring.final",
            candidate_id=candidate_id,
            final_score=final.final_score,
            passed=final.passed,
        )
        return ScoringOutcome(candidate_id, rules, haiku_result, final)

    async def score_pending(
        self, *, limit: int = 50, now: datetime | None = None
    ) -> list[ScoringOutcome]:
        """掃描還沒進 scoring_records 的 candidates，逐一評分."""
        stmt = (
            select(CandidatePost.id)
            .outerjoin(
                ScoringRecord,
                (ScoringRecord.candidate_post_id == CandidatePost.id)
                & (ScoringRecord.stage == ScoringStage.RULES.value),
            )
            .where(ScoringRecord.id.is_(None))
            .order_by(CandidatePost.discovered_at.asc())
            .limit(limit)
        )
        ids = list((await self._session.execute(stmt)).scalars().all())
        outcomes: list[ScoringOutcome] = []
        for cid in ids:
            try:
                outcomes.append(await self.score_candidate(cid, now=now))
            except Exception as exc:  # noqa: BLE001
                logger.error(
                    "scoring.candidate_failed",
                    candidate_id=cid,
                    error=str(exc),
                )
        logger.info(
            "scoring.batch_done",
            requested=len(ids),
            processed=len(outcomes),
        )
        return outcomes

    # --- internals -------------------------------------------------------

    async def _has_final_record(self, candidate_id: int) -> bool:
        stmt = select(ScoringRecord.id).where(
            ScoringRecord.candidate_post_id == candidate_id,
            ScoringRecord.stage == ScoringStage.FINAL.value,
        )
        return (await self._session.execute(stmt)).first() is not None

    async def _reload_outcome(self, candidate: CandidatePost) -> ScoringOutcome:
        """idempotent return — 從既有 scoring_records 重建一個 outcome 供呼叫端使用."""
        # 簡單做：不重建 dataclass，僅回傳 placeholder（FINAL 已寫即視為完成）
        rules_stub = RulesResult(
            passed=True,
            velocity_per_hour=0.0,
            velocity_normalized=0.0,
            reason="cached",
            details={"cached": True},
        )
        return ScoringOutcome(candidate.id, rules_stub, None, None)

    async def _write_record(
        self,
        *,
        candidate_id: int,
        stage: ScoringStage,
        passed: bool | None,
        score: float | None,
        details: dict[str, Any] | None,
        cost_usd: Decimal | None,
    ) -> None:
        rec = ScoringRecord(
            candidate_post_id=candidate_id,
            stage=stage.value,
            passed=passed,
            score=score,
            details=details,
            cost_usd=cost_usd,
        )
        self._session.add(rec)
        await self._session.flush()

    async def _write_llm_record(
        self, candidate_id: int, score: CandidateScore
    ) -> None:
        rec = LLMRecord(
            purpose=LLMPurpose.SCORING.value,
            related_id=candidate_id,
            model=score.model,
            input_tokens=score.input_tokens,
            output_tokens=score.output_tokens,
            cost_usd=Decimal(str(score.cost_usd)),
            content=score.raw_response,
        )
        self._session.add(rec)
        await self._session.flush()


__all__ = [
    "AUTHOR_FOLLOWER_MAX",
    "CONTENT_LENGTH_MAX",
    "CONTENT_LENGTH_MIN",
    "FINAL_SCORE_PASS_THRESHOLD",
    "FinalScore",
    "RulesResult",
    "SPONSORED_PATTERNS",
    "ScoringOutcome",
    "ScoringService",
    "VELOCITY_MIN_PER_HOUR",
    "VELOCITY_NORMALIZATION_CAP",
    "WEIGHT_GRASSROOTS",
    "WEIGHT_NOVELTY",
    "WEIGHT_SEMANTIC",
    "WEIGHT_VELOCITY",
    "apply_hard_rules",
    "combine_final",
]
