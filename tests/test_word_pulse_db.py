"""Transactional rule versioning and label checkpoint contracts."""

import pytest


async def seed():
    from src.plugins.word_pulse import db
    await db.add_clusters("g", "炒股", ["割肉", "抄底"])
    return await db.get_theme("g", "炒股")


async def test_rule_changes_increment_only_on_real_changes(app):
    from src.plugins.word_pulse import db
    theme = await seed()
    first = theme.rules_version
    result = await db.add_aliases(theme.id, "割肉", ["止损", "抄底"])
    assert result.added == ("止损",)
    assert result.conflicts[0][0] == "抄底"
    assert (await db.get_theme("g", "炒股")).rules_version == first + 1
    await db.add_aliases(theme.id, "抄底", ["止损"])
    await db.add_clusters("g", "炒股", ["止损", "割肉"])
    await db.set_mode(theme.id, "semantic")
    await db.set_description(theme.id, "割肉", "")
    assert (await db.get_theme("g", "炒股")).rules_version == first + 1
    await db.set_description(theme.id, "割肉", "亏损卖出")
    await db.set_mode(theme.id, "literal")
    assert (await db.get_theme("g", "炒股")).rules_version == first + 3
    assert await db.remove_aliases(theme.id, "割肉", ["止损", "不存在"]) == ["止损"]
    assert await db.remove_clusters(theme.id, ["割肉"]) == ["割肉"]
    assert [c.name for c in (await db.get_theme("g", "炒股")).clusters] == ["抄底"]


async def test_normalized_namespace_and_group_isolation(app):
    from src.plugins.word_pulse import db
    await db.add_clusters("g", "游戏", ["MC", "ｍｃ"])
    theme = await db.get_theme("g", "游戏")
    assert len(theme.clusters) == 1
    await db.add_aliases(theme.id, "mc", ["Minecraft"])
    result = await db.add_clusters("g", "游戏", ["ＭＩＮＥＣＲＡＦＴ"])
    assert not result.added
    assert await db.get_theme("other", "游戏") is None


async def test_commit_backfill_version_guard_and_live_visibility(app):
    from src.plugins.word_pulse import db
    from src.plugins.word_pulse.core.types import ClassifyOutcome, Label
    theme = await seed()
    version = theme.rules_version
    await db.init_cursor("g", 4, 100)
    await db.init_backfill(theme.id, version, 1, 4)
    outcome = ClassifyOutcome((Label(theme.id, 5, theme.clusters[0].id, "literal", "u", 100),), {(theme.id, "1970-01-01"): 1})
    await db.commit_live_batch("g", outcome, 5, {theme.id: version}, 1, 100)
    assert await db.get_cursor("g") == (5, 100)
    assert await db.aggregate_relevant(theme.id, version, 0, 200) == (1, 1)
    await db.set_mode(theme.id, "literal")
    assert not await db.commit_backfill_chunk(theme.id, version, outcome, None, 1, 101)
    assert await db.aggregate_relevant(theme.id, version + 1, 0, 200) == (0, 0)
    await db.init_backfill(theme.id, version + 1, 1, 5)
    assert await db.aggregate_relevant(theme.id, version, 0, 200) == (0, 0)
    assert await db.commit_backfill_chunk(theme.id, version + 1, outcome, None, 1, 102)
    assert (await db.get_theme("g", "炒股")).backfill_next_id is None
    assert await db.get_budget_used("g", "1970-01-01") == 2
    await db.delete_theme(theme.id)
    assert await db.get_theme("g", "炒股") is None
    assert await db.aggregate_relevant(theme.id, version + 1, 0, 200) == (0, 0)


async def test_batch_failure_rolls_back_labels_budget_and_cursor(app):
    from src.plugins.word_pulse import db
    from src.plugins.word_pulse.core.types import ClassifyOutcome, Label
    theme = await seed()
    await db.init_cursor("g", 0, 1)
    await db.db.execute("""CREATE TRIGGER reject_cursor BEFORE UPDATE ON word_pulse_cursor
        BEGIN SELECT RAISE(ABORT, 'injected'); END""")
    try:
        with pytest.raises(Exception, match="injected"):
            await db.commit_live_batch("g", ClassifyOutcome((Label(theme.id, 1, 0, "ai", "u", 10),), {}), 1, {theme.id: theme.rules_version}, 1, 10)
        assert await db.get_cursor("g") == (0, 1)
        assert await db.aggregate_relevant(theme.id, theme.rules_version, 0, 20) == (0, 0)
        assert await db.get_budget_used("g", "1970-01-01") == 0
    finally:
        await db.db.execute("DROP TRIGGER reject_cursor")


async def test_schema_repeatable_and_old_tables_removed(app):
    from src.plugins.word_pulse import db
    theme = await seed()
    db.ensure_schema()
    db.ensure_schema()
    assert await db.get_theme("g", "炒股") == theme
    tables = {r[0] for r in await db.db.fetch_all("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "word_pulse_bucket" not in tables
    assert "word_pulse_charset" not in tables


async def test_report_snapshot_excludes_concurrent_batch(app, monkeypatch):
    import asyncio
    import threading
    from src.plugins.word_pulse import db
    from src.plugins.word_pulse.core.types import ClassifyOutcome, Label

    theme = await seed()
    now = 1800000000
    await db.init_cursor("g", 0, now)
    entered, release = threading.Event(), threading.Event()
    original = db._aggregate_clusters

    def pause(*args):
        result = original(*args)
        entered.set()
        assert release.wait(5), "test did not release report reader"
        return result

    monkeypatch.setattr(db, "_aggregate_clusters", pause)
    reader = asyncio.create_task(db.load_report_data("g", "炒股", 7, now, semantic_available=True))
    writer = None
    try:
        assert await asyncio.to_thread(entered.wait, 5)
        outcome = ClassifyOutcome((Label(theme.id, 1, theme.clusters[0].id, "ai", "u", now),), {})
        writer = asyncio.create_task(db.commit_live_batch("g", outcome, 1, {theme.id: theme.rules_version}, 1, now + 1))
        await asyncio.sleep(0)
        assert not writer.done()
    finally:
        release.set()
        data = await reader
        if writer is not None:
            await writer
    assert data.relevant_messages == 0 and not data.clusters
    assert data.data_as_of == now
    fresh = await db.load_report_data("g", "炒股", 7, now + 1, semantic_available=True)
    assert fresh.relevant_messages == fresh.clusters[0].messages == 1
    assert fresh.data_as_of == now + 1


async def test_migration_preserves_legacy_rules_and_drops_derived_tables(app, tmp_path, monkeypatch):
    from src.plugins.word_pulse import db
    from src.storage.sqlite_manager import SQLiteManager
    manager = SQLiteManager(tmp_path / "legacy.sqlite")
    manager.ensure_schema([
        "CREATE TABLE word_pulse_theme(id INTEGER PRIMARY KEY, group_id TEXT, name TEXT, created_at INTEGER, updated_at INTEGER, UNIQUE(group_id,name))",
        "CREATE TABLE word_pulse_cluster(id INTEGER PRIMARY KEY, theme_id INTEGER REFERENCES word_pulse_theme(id) ON DELETE CASCADE, name TEXT, aliases_json TEXT, created_at INTEGER, UNIQUE(theme_id,name))",
        "CREATE TABLE word_pulse_bucket(value TEXT)",
        "CREATE TABLE word_pulse_charset(value TEXT)",
        "INSERT INTO word_pulse_theme VALUES(1,'g','炒股',10,10)",
        "INSERT INTO word_pulse_cluster VALUES(2,1,'割肉','[\"止损\"]',10)",
    ])
    try:
        with monkeypatch.context() as patch:
            patch.setattr(db, "db", manager)
            db.ensure_schema()
            db.ensure_schema()
            theme = await db.get_theme("g", "炒股")
            assert theme.mode == "semantic" and theme.rules_version == 1
            assert theme.backfill_version == 0
            assert theme.clusters[0].aliases == ("止损",)
            assert theme.clusters[0].description == ""
            tables = {row[0] for row in await manager.fetch_all("SELECT name FROM sqlite_master WHERE type='table'")}
            assert not {"word_pulse_bucket", "word_pulse_charset"} & tables
    finally:
        await manager.close()
