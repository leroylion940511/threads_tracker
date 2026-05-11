"""評分層測試 — 規則 / 加權 / 三段寫入 / batch（不打 LLM）."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from threads_tracker.db import Base
from threads_tracker.llm.haiku import CandidateScore
from threads_tracker.models import (
    CandidatePost,
    LLMRecord,
    ScoringRecord,
    ScoringStage,
)
from threads_tracker.services.scoring import (
    FINAL_SCORE_PASS_THRESHOLD,
    ScoringService,
    apply_hard_rules,
    combine_final,
)


# --- fixtures ------------------------------------------------------------


@pytest.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as s:
        yield s
    await engine.dispose()


def _candidate(
    *,
    post_id: str = "P1",
    content: str = "今天搭捷運遇到一個阿伯，他突然開始講起他年輕時的故事，我整個被吸引住了，後續發展讓我意想不到，回到家還在想這件事。",
    posted_minutes_ago: int = 60,
    likes: int = 80,
    replies: int = 20,
    follower: int | None = 500,
) -> CandidatePost:
    now = datetime.now(timezone.utc)
    return CandidatePost(
        threads_post_id=post_id,
        author_username="alice",
        author_follower_count=follower,
        post_url=f"https://www.threads.net/@alice/post/{post_id}",
        content=content,
        posted_at=now - timedelta(minutes=posted_minutes_ago),
        discovered_at=now,
        discovery_source="test",
        initial_likes=likes,
        initial_replies=replies,
        initial_reposts=0,
    )


class FakeClassifier:
    """假的 HaikuClassifier；可以指定回傳分數或丟例外."""

    def __init__(
        self, score: CandidateScore | None = None, exc: Exception | None = None
    ) -> None:
        self._score = score
        self._exc = exc
        self.calls: list[dict] = []

    async def score_candidate(
        self,
        *,
        content: str,
        author_username: str | None = None,
        follower_count: int | None = None,
    ) -> CandidateScore:
        self.calls.append(
            {
                "content": content,
                "author": author_username,
                "followers": follower_count,
            }
        )
        if self._exc is not None:
            raise self._exc
        assert self._score is not None
        return self._score


def _haiku_score(
    *,
    verdict: str = "track",
    story: float = 0.8,
    emo: float = 0.7,
    grass: float = 0.9,
    novelty: float = 0.6,
    authenticity: float = 0.8,
) -> CandidateScore:
    return CandidateScore(
        story_potential=story,
        emotional_pull=emo,
        grassroots=grass,
        novelty=novelty,
        authenticity=authenticity,
        verdict=verdict,  # type: ignore[arg-type]
        reason="test",
        model="haiku-test",
        input_tokens=120,
        output_tokens=40,
        cost_usd=0.000320,
        raw_response='{"verdict":"track"}',
    )


# --- 硬規則 --------------------------------------------------------------


def test_rules_pass_typical_post():
    cand = _candidate()
    result = apply_hard_rules(cand)
    assert result.passed is True
    assert result.reason is None
    assert result.velocity_per_hour > 30
    assert 0.0 < result.velocity_normalized <= 1.0


def test_rules_reject_low_velocity():
    cand = _candidate(likes=2, replies=0, posted_minutes_ago=60)
    result = apply_hard_rules(cand)
    assert result.passed is False
    assert "velocity_too_low" in result.reason


def test_rules_reject_big_author():
    cand = _candidate(follower=50_000)
    result = apply_hard_rules(cand)
    assert result.passed is False
    assert "author_too_big" in result.reason


def test_rules_pass_when_follower_unknown():
    cand = _candidate(follower=None)
    result = apply_hard_rules(cand)
    assert result.passed is True


def test_rules_reject_too_short():
    cand = _candidate(content="哈哈太短了")
    result = apply_hard_rules(cand)
    assert result.passed is False
    assert "length_out_of_range" in result.reason


def test_rules_reject_too_long():
    cand = _candidate(content="今天" * 300)
    result = apply_hard_rules(cand)
    assert result.passed is False
    assert "length_out_of_range" in result.reason


def test_rules_reject_simplified_chinese():
    cand = _candidate(
        content=(
            "这是一个简体中文的测试帖子，说的是今天发生的事情，没想到这么多人来问，"
            "我会继续更新这个事件的发展，让大家都能看到。"
        )
    )
    result = apply_hard_rules(cand)
    assert result.passed is False
    assert result.reason == "not_traditional_chinese"


def test_rules_reject_non_chinese():
    cand = _candidate(
        content=(
            "This is a long english only post that does not contain any chinese "
            "characters and should be rejected by the traditional-chinese gate."
        )
    )
    result = apply_hard_rules(cand)
    assert result.passed is False
    assert result.reason == "not_traditional_chinese"


def test_rules_reject_sponsored():
    cand = _candidate(
        content=(
            "今天要跟大家分享一個超棒的好物，這是業配文沒錯但真的好用，"
            "用了之後完全改變我的生活，推薦給有需要的朋友們參考看看。"
        )
    )
    result = apply_hard_rules(cand)
    assert result.passed is False
    assert result.reason.startswith("sponsored_marker")


def test_rules_velocity_normalized_caps_at_one():
    cand = _candidate(likes=10_000, replies=5_000, posted_minutes_ago=30)
    result = apply_hard_rules(cand)
    assert result.velocity_normalized == 1.0


# --- 加權 ----------------------------------------------------------------


def test_combine_final_formula():
    rules = apply_hard_rules(_candidate())
    haiku = _haiku_score(story=1.0, emo=1.0, grass=1.0, novelty=1.0)
    final = combine_final(rules, haiku)
    # v=rules.normalized, s=1, g=1, n=1 → final = 0.4·v + 0.6
    expected = 0.4 * rules.velocity_normalized + 0.3 * 1.0 + 0.2 * 1.0 + 0.1 * 1.0
    assert final.final_score == round(expected, 4)
    assert final.passed is True


def test_combine_final_fails_when_verdict_skip():
    rules = apply_hard_rules(_candidate())
    haiku = _haiku_score(verdict="skip", story=1.0, emo=1.0, grass=1.0, novelty=1.0)
    final = combine_final(rules, haiku)
    assert final.passed is False, "verdict=skip must short-circuit passed"


def test_combine_final_fails_when_below_threshold():
    rules = apply_hard_rules(_candidate(likes=40, replies=0, posted_minutes_ago=60))
    haiku = _haiku_score(story=0.1, emo=0.1, grass=0.1, novelty=0.1)
    final = combine_final(rules, haiku)
    assert final.final_score < FINAL_SCORE_PASS_THRESHOLD
    assert final.passed is False


# --- ScoringService 三段寫入 --------------------------------------------


async def test_score_candidate_rules_only_when_rules_fail(session):
    cand = _candidate(likes=1, replies=0)
    session.add(cand)
    await session.commit()

    classifier = FakeClassifier(score=_haiku_score())
    service = ScoringService(session, classifier)
    outcome = await service.score_candidate(cand.id)

    assert outcome.rules.passed is False
    assert outcome.haiku is None
    assert outcome.final is None
    assert classifier.calls == [], "Haiku must not be called when rules fail"

    rows = (
        await session.execute(
            select(ScoringRecord).where(
                ScoringRecord.candidate_post_id == cand.id
            )
        )
    ).scalars().all()
    assert [r.stage for r in rows] == [ScoringStage.RULES.value]


async def test_score_candidate_three_stage_write(session):
    cand = _candidate()
    session.add(cand)
    await session.commit()

    classifier = FakeClassifier(score=_haiku_score())
    service = ScoringService(session, classifier)
    outcome = await service.score_candidate(cand.id)

    assert outcome.rules.passed is True
    assert outcome.haiku is not None
    assert outcome.final is not None
    assert outcome.final.passed is True
    assert classifier.calls and classifier.calls[0]["author"] == "alice"

    rows = (
        await session.execute(
            select(ScoringRecord)
            .where(ScoringRecord.candidate_post_id == cand.id)
            .order_by(ScoringRecord.id)
        )
    ).scalars().all()
    stages = [r.stage for r in rows]
    assert stages == [
        ScoringStage.RULES.value,
        ScoringStage.HAIKU.value,
        ScoringStage.FINAL.value,
    ]

    final_row = rows[-1]
    assert final_row.passed is True
    assert final_row.score == outcome.final.final_score
    assert final_row.details["haiku_verdict"] == "track"

    # LLM audit row written
    llm_rows = (
        await session.execute(
            select(LLMRecord).where(LLMRecord.related_id == cand.id)
        )
    ).scalars().all()
    assert len(llm_rows) == 1
    assert llm_rows[0].purpose == "scoring"
    assert llm_rows[0].input_tokens == 120
    assert llm_rows[0].output_tokens == 40


async def test_score_candidate_haiku_failure_writes_only_rules_haiku(session):
    cand = _candidate()
    session.add(cand)
    await session.commit()

    classifier = FakeClassifier(exc=RuntimeError("api 500"))
    service = ScoringService(session, classifier)
    outcome = await service.score_candidate(cand.id)

    assert outcome.rules.passed is True
    assert outcome.haiku is None
    assert outcome.final is None

    rows = (
        await session.execute(
            select(ScoringRecord)
            .where(ScoringRecord.candidate_post_id == cand.id)
            .order_by(ScoringRecord.id)
        )
    ).scalars().all()
    stages = [r.stage for r in rows]
    assert stages == [ScoringStage.RULES.value, ScoringStage.HAIKU.value]
    haiku_row = rows[1]
    assert haiku_row.passed is None
    assert "api 500" in haiku_row.details["error"]


async def test_score_candidate_idempotent(session):
    cand = _candidate()
    session.add(cand)
    await session.commit()

    classifier = FakeClassifier(score=_haiku_score())
    service = ScoringService(session, classifier)
    await service.score_candidate(cand.id)
    await service.score_candidate(cand.id)  # second call should short-circuit

    final_rows = (
        await session.execute(
            select(ScoringRecord)
            .where(
                ScoringRecord.candidate_post_id == cand.id,
                ScoringRecord.stage == ScoringStage.FINAL.value,
            )
        )
    ).scalars().all()
    assert len(final_rows) == 1


async def test_score_candidate_without_classifier_runs_rules_only(session):
    cand = _candidate()
    session.add(cand)
    await session.commit()

    service = ScoringService(session, classifier=None)
    outcome = await service.score_candidate(cand.id)
    assert outcome.rules.passed is True
    assert outcome.haiku is None
    assert outcome.final is None

    rows = (
        await session.execute(
            select(ScoringRecord).where(
                ScoringRecord.candidate_post_id == cand.id
            )
        )
    ).scalars().all()
    assert [r.stage for r in rows] == [ScoringStage.RULES.value]


async def test_score_pending_picks_unscored_only(session):
    cand_a = _candidate(post_id="A")
    cand_b = _candidate(post_id="B")
    cand_c = _candidate(post_id="C", likes=0, replies=0)  # will fail rules
    session.add_all([cand_a, cand_b, cand_c])
    await session.commit()

    classifier = FakeClassifier(score=_haiku_score())
    service = ScoringService(session, classifier)
    outcomes = await service.score_pending()
    assert len(outcomes) == 3

    # second batch finds none
    outcomes_2 = await service.score_pending()
    assert outcomes_2 == []
