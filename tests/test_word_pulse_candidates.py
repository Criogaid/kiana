"""Local phrase discovery thresholds, semantic-only inputs, and scan serialization."""

import asyncio
import threading
from unittest.mock import AsyncMock

import pytest


def theme():
    from src.plugins.word_pulse.core.types import ClusterRule, ThemeRule
    return ThemeRule(1, "g", "炒股", "semantic", 1, 1, None, None,
                     (ClusterRule(2, "割肉", ("止损",), ""),))


def messages(texts, users=None):
    from src.plugins.word_pulse.core.types import Msg
    return [Msg(i + 1, 1800000000, users[i] if users else str(i % 2), text)
            for i, text in enumerate(texts)]


def test_thresholds_and_substring_absorption():
    from src.plugins.word_pulse.core.candidates import discover_candidates
    texts = ["满仓套牢", "满仓套牢", "满仓套牢"]
    assert not discover_candidates(theme(), messages(texts[:2]))
    assert not discover_candidates(theme(), messages(texts, ["u"] * 3))
    result = discover_candidates(theme(), messages(texts))
    assert [(p.phrase, p.message_count, p.user_count) for p in result] == [("满仓套牢", 3, 2)]
    assert not discover_candidates(theme(), messages(["割肉止损炒股"] * 3))
    assert not discover_candidates(theme(), messages(["哈哈哈哈"] * 3))


def test_repetition_in_one_message_does_not_satisfy_support():
    from src.plugins.word_pulse.core.candidates import discover_candidates
    assert not discover_candidates(theme(), messages(["满仓套牢" * 20, "无关内容"]))


async def test_scan_only_ai_without_literal_current_theme_version(app, monkeypatch):
    from src.plugins.word_pulse import candidates, db
    from src.plugins.word_pulse.core.types import ClassifyOutcome, Label
    from tests.test_word_pulse_analysis_extra import archive
    from src.plugins.ai_provider import service
    forbidden = AsyncMock(side_effect=AssertionError("candidate scan must not call AI"))
    monkeypatch.setattr(service, "complete", forbidden)
    await db.add_clusters("g", "炒股", ["割肉", "抄底"])
    current = await db.get_theme("g", "炒股")
    now = 1800000000
    await db.init_cursor("g", 0, now)
    labels = []
    included = []
    for i in range(6):
        mid = await archive("满仓套牢" if i < 3 else "错误候选", now - 1, user=str(i % 2))
        labels.append(Label(current.id, mid, current.clusters[0].id, "ai", str(i % 2), now - 1))
        if i < 3:
            included.append(mid)
        else:
            labels.append(Label(current.id, mid, current.clusters[1].id, "literal", str(i % 2), now - 1))
    await db.commit_live_batch("g", ClassifyOutcome(tuple(labels), {}), mid, {current.id: current.rules_version}, 6, now)
    assert await db.candidate_archive_ids(current.id, current.rules_version, now - 10, now + 1) == included
    assert not await db.candidate_archive_ids(current.id, current.rules_version + 1, now - 10, now + 1)
    assert not await db.candidate_archive_ids(current.id, current.rules_version, now + 1, now + 10)
    text = await candidates.scan_candidates(current, now)
    assert "满仓套牢（3条 / 2人）" in text
    assert "错误候选" not in text
    forbidden.assert_not_awaited()
    await db.set_mode(current.id, "literal")
    current = await db.get_theme("g", "炒股")
    assert await candidates.scan_candidates(current, now) == "字面模式的主题不支持候选发现"


async def test_cancellation_keeps_single_scan_until_thread_finishes(app, monkeypatch):
    from src.plugins.word_pulse import candidates
    entered, release = threading.Event(), threading.Event()
    def mine(*args):
        entered.set()
        assert release.wait(5)
        return ()
    monkeypatch.setattr(candidates, "discover_candidates", mine)
    scan = asyncio.create_task(candidates.scan_candidates(theme(), 1800000000))
    try:
        assert await asyncio.to_thread(entered.wait, 5)
        scan.cancel()
        await asyncio.sleep(0)
        scan.cancel()
        assert "正在扫描" in await candidates.scan_candidates(theme(), 1800000000)
        assert not scan.done()
    finally:
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await scan
    assert not candidates._scan_locks[1].locked()
