"""Cross-stage acceptance for retention, rule races, scheduling and report boundaries."""

import time
from unittest.mock import AsyncMock

import pytest


async def test_retention_preserves_archive_rules_and_cursor(app):
    from src.plugins.word_pulse import db
    from src.plugins.word_pulse.core.types import ClassifyOutcome, Label
    from tests.test_word_pulse_analysis_extra import archive, setup_theme
    from src.storage import get_db
    theme = await setup_theme()
    old = await archive("割肉", 100)
    fresh = await archive("抄底", 1800000000)
    await db.init_cursor("g", 0, 100)
    await db.commit_live_batch("g", ClassifyOutcome((Label(theme.id, old, 0, "ai", "u", 100),), {(theme.id, "1970-01-01"): 1}), old, {theme.id: theme.rules_version}, 1, 100)
    await db.commit_live_batch("g", ClassifyOutcome((Label(theme.id, fresh, 0, "ai", "u", 1800000000),), {}), fresh, {theme.id: theme.rules_version}, 1, 1800000000)
    assert await db.purge_before(1700000000, "2023-11-14") == 1
    assert await db.aggregate_relevant(theme.id, theme.rules_version, 0, 1900000000) == (1, 1)
    assert await db.get_budget_used("g", "1970-01-01") == 0
    assert await db.sum_unclassified(theme.id, theme.rules_version, "1970-01-01", "1970-01-01") == 0
    assert (await db.get_cursor("g"))[0] == fresh
    assert await db.get_theme("g", "炒股") == theme
    assert (await get_db().fetch_one("SELECT COUNT(*) FROM message_archive"))[0] == 2


async def test_rule_edit_during_live_classification_is_reconciled(app, monkeypatch):
    from src.plugins.word_pulse import db, pipeline
    from tests.test_word_pulse_analysis_extra import archive, setup_theme
    theme = await setup_theme("semantic")
    await pipeline.ensure_cursor("g", 100)
    await pipeline.reconcile(theme, 100)
    last = await archive("割肉，亏麻了", 110)
    async def classify(messages, themes):
        await db.add_aliases(theme.id, "割肉", ["亏麻了"])
        return await pipeline.AIClassifier.literal_only(messages, themes)
    classifier = AsyncMock(side_effect=classify)
    monkeypatch.setattr(pipeline.AIClassifier, "classify", classifier)
    await pipeline.run_live("g", 120)
    current = await db.get_theme("g", "炒股")
    classifier.assert_awaited_once()
    assert current.rules_version > theme.rules_version
    assert (await db.get_cursor("g"))[0] == last
    assert await db.aggregate_relevant(theme.id, theme.rules_version, 0, 200) == (1, 1)
    assert await db.sum_unclassified(theme.id, theme.rules_version, "1970-01-01", "1970-01-01") == 1
    assert await db.aggregate_relevant(theme.id, current.rules_version, 0, 200) == (0, 0)
    await pipeline.reconcile(current, 130)
    assert await db.aggregate_relevant(theme.id, theme.rules_version, 0, 200) == (0, 0)
    assert await db.sum_unclassified(theme.id, theme.rules_version, "1970-01-01", "1970-01-01") == 0
    pipeline.config.word_pulse_ai_daily_budget = 0
    pipeline.config.word_pulse_plugin_enabled = True
    await pipeline.tick(130)
    await pipeline.tick(140)
    assert await db.aggregate_relevant(theme.id, current.rules_version, 0, 200) == (1, 1)
    assert await db.sum_unclassified(theme.id, current.rules_version, "1970-01-01", "1970-01-01") == 1
    assert (await db.db.fetch_one("SELECT COUNT(*) FROM word_pulse_label WHERE theme_id=?", (theme.id,)))[0] == 1
    assert (await db.db.fetch_one("SELECT SUM(count) FROM word_pulse_unclassified WHERE theme_id=?", (theme.id,)))[0] == 1


@pytest.mark.parametrize("mode,whitelist,blacklist,allowed", [
    ("all", [], [], ["a", "b"]),
    ("whitelist", ["b"], [], ["b"]),
    ("blacklist", [], ["a"], ["b"]),
])
async def test_group_permissions_apply_to_background_ticks(app, monkeypatch, mode, whitelist, blacklist, allowed):
    from src.plugins.word_pulse import pipeline
    pipeline.config.word_pulse_plugin_enabled = True
    pipeline.config.word_pulse_group_mode = mode
    pipeline.config.word_pulse_group_whitelist = whitelist
    pipeline.config.word_pulse_group_blacklist = blacklist
    monkeypatch.setattr(pipeline.db, "list_groups_with_themes", AsyncMock(return_value=["a", "b"]))
    tick = AsyncMock()
    monkeypatch.setattr(pipeline, "_tick_group", tick)
    await pipeline.tick(100)
    assert [call.args[0] for call in tick.await_args_list] == allowed


async def test_one_group_failure_does_not_stop_other_groups(app, monkeypatch):
    from src.plugins.word_pulse import pipeline
    pipeline.config.word_pulse_plugin_enabled = True
    monkeypatch.setattr(pipeline.db, "list_groups_with_themes", AsyncMock(return_value=["a", "b"]))
    tick = AsyncMock(side_effect=[RuntimeError("injected group failure"), None])
    monkeypatch.setattr(pipeline, "_tick_group", tick)
    await pipeline.tick(100)
    assert tick.await_count == 2


async def test_examples_truncated_without_sender_and_cache_invalidates_on_rule_change(app, monkeypatch):
    from src.plugins.word_pulse import db, pipeline, report
    from tests.test_word_pulse_analysis_extra import archive, setup_theme
    now = int(time.time())
    theme = await setup_theme()
    await archive("割肉" + "亏" * 80, now - 1, user="private-identity")
    pipeline.config.word_pulse_plugin_enabled = True
    await pipeline.tick(now)
    trend = AsyncMock(return_value="下降")
    monkeypatch.setattr(report, "_trend_sentence", trend)
    report.config.word_pulse_show_examples = True
    first = await report.build_report("g", "炒股", 7, now)
    assert "割肉" + "亏" * 38 in first.text and "亏" * 39 not in first.text
    assert "private-identity" not in first.text
    await db.touch_cursor("g", now + 10)
    assert await report.build_report("g", "炒股", 7, now + 10) == first
    trend.assert_awaited_once()
    await db.add_aliases(theme.id, "割肉", ["止损"])
    updated = await report.build_report("g", "炒股", 7, now + 11)
    assert updated.data.relevant_messages == 0 and updated.data.backfilling
    assert updated != first


def test_scheduler_and_config_bounds(app):
    from pydantic import ValidationError
    from src.plugins.word_pulse import jobs
    from src.plugins.word_pulse.config import Config
    tick = jobs.scheduler.get_job("word_pulse_tick")
    assert tick.max_instances == 1 and tick.coalesce
    assert tick.trigger.interval.total_seconds() == jobs.config.word_pulse_tick_minutes * 60
    assert jobs.scheduler.get_job("word_pulse_cleanup") is not None
    for field, value in [("word_pulse_ai_daily_budget", -1), ("word_pulse_tick_minutes", 61),
                         ("word_pulse_backfill_days", 32), ("word_pulse_label_retention_days", 6),
                         ("word_pulse_ai_output_mode", "invalid")]:
        with pytest.raises(ValidationError):
            Config(**{field: value})


async def test_rule_edit_after_reconcile_skips_live_and_backfills_once(app, monkeypatch):
    from src.plugins.word_pulse import db, pipeline
    from tests.test_word_pulse_analysis_extra import archive, setup_theme

    theme = await setup_theme("semantic")
    await pipeline.ensure_cursor("g", 100)
    await pipeline.reconcile(theme, 100)
    await db.add_aliases(theme.id, "割肉", ["亏麻了"])
    last = await archive("亏麻了", 110)
    classifier = AsyncMock(side_effect=AssertionError("unreconciled theme must not reach AI"))
    monkeypatch.setattr(pipeline.AIClassifier, "classify", classifier)
    pipeline.config.word_pulse_ai_daily_budget = 0
    await pipeline.run_live("g", 120)

    assert await db.get_cursor("g") == (last, 120)
    assert (await db.db.fetch_one("SELECT COUNT(*) FROM word_pulse_label WHERE theme_id=?", (theme.id,)))[0] == 0
    assert (await db.db.fetch_one("SELECT COUNT(*) FROM word_pulse_unclassified WHERE theme_id=?", (theme.id,)))[0] == 0
    pipeline.config.word_pulse_plugin_enabled = True
    await pipeline.tick(130)
    current = await db.get_theme("g", "炒股")
    assert current.backfill_version == current.rules_version
    assert current.backfill_until_id == last and current.backfill_next_id is None
    assert await db.aggregate_relevant(theme.id, current.rules_version, 0, 200) == (1, 1)
    assert await db.sum_unclassified(theme.id, current.rules_version, "1970-01-01", "1970-01-01") == 1
    await pipeline.tick(140)
    assert await db.aggregate_relevant(theme.id, current.rules_version, 0, 200) == (1, 1)
    assert await db.sum_unclassified(theme.id, current.rules_version, "1970-01-01", "1970-01-01") == 1
    classifier.assert_not_awaited()
