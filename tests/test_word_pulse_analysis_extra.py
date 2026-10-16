"""Background live/backfill processing with real SQLite state."""

from unittest.mock import AsyncMock

import pytest


async def archive(text, when=100, group="g", user="u"):
    from src.storage import get_db
    db = get_db()
    await db.execute("""INSERT INTO message_archive
        (session_type,session_id,message_id,event_time,self_id,user_id,sender_name,message_cq,plain_text)
        VALUES('group',?,(SELECT COALESCE(MAX(message_id),0)+1 FROM message_archive),?,'bot',?,'','',?)""", (group, when, user, text))
    return (await db.fetch_one("SELECT MAX(id) FROM message_archive"))[0]


async def setup_theme(mode="literal"):
    from src.plugins.word_pulse import db
    await db.add_clusters("g", "炒股", ["割肉", "抄底"])
    theme = await db.get_theme("g", "炒股")
    await db.set_mode(theme.id, mode)
    return await db.get_theme("g", "炒股")


async def test_first_tick_backfills_then_live_consumes_once(app, monkeypatch):
    from src.plugins.word_pulse import db, pipeline
    theme = await setup_theme()
    old_id = await archive("割肉")
    pipeline.config.word_pulse_plugin_enabled = True
    await pipeline.tick(200)
    assert (await db.get_cursor("g"))[0] == old_id
    assert await db.aggregate_relevant(theme.id, theme.rules_version, 0, 300) == (1, 1)
    new_id = await archive("割肉和抄底", 210, user="v")
    await pipeline.tick(220)
    assert (await db.get_cursor("g"))[0] == new_id
    assert await db.aggregate_relevant(theme.id, theme.rules_version, 0, 300) == (2, 2)
    await pipeline.tick(230)
    assert await db.aggregate_relevant(theme.id, theme.rules_version, 0, 300) == (2, 2)
    await db.add_aliases(theme.id, "割肉", ["亏麻了"])
    await archive("亏麻了", 240)
    await pipeline.tick(250)
    current = await db.get_theme("g", "炒股")
    assert current.backfill_next_id is None
    assert await db.aggregate_relevant(theme.id, current.rules_version, 0, 300) == (3, 2)
    assert await db.aggregate_relevant(theme.id, theme.rules_version, 0, 300) == (0, 0)


async def test_third_ai_failure_falls_back_without_stalling_cursor(app, monkeypatch):
    from src.plugins.word_pulse import db, pipeline
    from src.plugins.word_pulse.errors import WordPulseAITimeoutError
    theme = await setup_theme("semantic")
    await pipeline.ensure_cursor("g", 10)
    last_id = await archive("割肉", 20)
    fail = AsyncMock(side_effect=WordPulseAITimeoutError("timeout"))
    monkeypatch.setattr(pipeline.AIClassifier, "classify", fail)
    for now in (30, 40):
        await pipeline.run_live("g", now)
        assert (await db.get_cursor("g"))[0] < last_id
    await pipeline.run_live("g", 50)
    assert (await db.get_cursor("g"))[0] == last_id
    assert fail.await_count == 3
    assert await db.sum_unclassified(theme.id, theme.rules_version, "1970-01-01", "1970-01-01") == 1
    assert await db.aggregate_relevant(theme.id, theme.rules_version, 0, 100) == (1, 1)
    assert await db.get_budget_used("g", "1970-01-01") == 0


async def test_budget_caps_ai_head_and_records_unclassified_tail(app, monkeypatch):
    from src.plugins.word_pulse import db, pipeline
    from src.plugins.word_pulse.core.types import ClassifyOutcome
    theme = await setup_theme("semantic")
    pipeline.config.word_pulse_ai_daily_budget = 1
    await pipeline.ensure_cursor("g", 10)
    await archive("未知说法", 20)
    await archive("割肉", 21)
    classify = AsyncMock(return_value=ClassifyOutcome((), {}))
    monkeypatch.setattr(pipeline.AIClassifier, "classify", classify)
    await pipeline.run_live("g", 30)
    assert len(classify.call_args.args[0]) == 1
    assert await db.get_budget_used("g", "1970-01-01") == 1
    assert await db.sum_unclassified(theme.id, theme.rules_version, "1970-01-01", "1970-01-01") == 1
    assert await db.aggregate_relevant(theme.id, theme.rules_version, 0, 100) == (1, 1)


async def test_disabled_or_locked_tick_does_no_work(app, monkeypatch):
    from src.plugins.word_pulse import pipeline
    groups = AsyncMock(side_effect=AssertionError("must not read groups"))
    monkeypatch.setattr(pipeline.db, "list_groups_with_themes", groups)
    await pipeline.tick(100)
    pipeline.config.word_pulse_plugin_enabled = True
    async with pipeline._tick_lock:
        await pipeline.tick(100)
    groups.assert_not_awaited()


async def test_noise_is_skipped_but_cursor_advances(app):
    from src.plugins.word_pulse import db, pipeline
    theme = await setup_theme("semantic")
    await pipeline.ensure_cursor("g", 10)
    await archive("词频 炒股", 20)
    await archive("！！！", 21)
    end = await archive("割肉", 22, user="bot")
    await pipeline.run_live("g", 30)
    assert (await db.get_cursor("g"))[0] == end
    assert await db.aggregate_relevant(theme.id, theme.rules_version, 0, 100) == (0, 0)
    assert await db.sum_unclassified(theme.id, theme.rules_version, "1970-01-01", "1970-01-01") == 0


@pytest.mark.parametrize("has_archive", [False, True])
async def test_reconcile_records_backfill_window_coverage(app, monkeypatch, has_archive):
    from datetime import datetime
    from src.plugins.word_pulse import db, pipeline
    from src.plugins.word_pulse.core.timeutil import TZ, window_bounds
    theme = await setup_theme()
    now = int(datetime(2026, 10, 16, 12, tzinfo=TZ).timestamp())
    monkeypatch.setattr(pipeline.config, "word_pulse_backfill_days", 3)
    start, _ = window_bounds(now, 3)
    archive_id = await archive("割肉", start) if has_archive else None
    await pipeline.ensure_cursor("g", now)
    await pipeline.reconcile(theme, now)
    current = await db.get_theme("g", "炒股")
    assert current.coverage_since == start
    assert current.backfill_version == current.rules_version
    assert current.backfill_next_id == archive_id
    await pipeline.reconcile(current, now + 86400)
    assert await db.get_theme("g", "炒股") == current
