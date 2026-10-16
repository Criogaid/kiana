"""Transactional rules, classification checkpoints, and read-only label aggregates."""

from __future__ import annotations

import json
import sqlite3
import time
from collections.abc import Sequence
from dataclasses import dataclass

from pydantic import TypeAdapter

from src.storage import get_db

from .core.aggregate import ClusterCounts, ReportData, build
from .core.text import normalize
from .core.timeutil import SECONDS_PER_DAY, day_of, window_bounds
from .core.types import ClassifyOutcome, ClusterRule, ThemeMode, ThemeRule

db = get_db()
_ALIASES = TypeAdapter(list[str])
_MODE = TypeAdapter(ThemeMode)
SCHEMA_STATEMENTS = [
    """CREATE TABLE IF NOT EXISTS word_pulse_theme (
        id INTEGER PRIMARY KEY AUTOINCREMENT, group_id TEXT NOT NULL, name TEXT NOT NULL,
        created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL, UNIQUE(group_id, name))""",
    """CREATE TABLE IF NOT EXISTS word_pulse_cluster (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        theme_id INTEGER NOT NULL REFERENCES word_pulse_theme(id) ON DELETE CASCADE,
        name TEXT NOT NULL, created_at INTEGER NOT NULL, UNIQUE(theme_id, name))""",
    "CREATE INDEX IF NOT EXISTS idx_word_pulse_theme_group ON word_pulse_theme(group_id)",
    "CREATE INDEX IF NOT EXISTS idx_word_pulse_cluster_theme ON word_pulse_cluster(theme_id)",
    """CREATE TABLE IF NOT EXISTS word_pulse_label (
        theme_id INTEGER NOT NULL, archive_id INTEGER NOT NULL, cluster_id INTEGER NOT NULL,
        source TEXT NOT NULL, rules_version INTEGER NOT NULL, user_id TEXT NOT NULL,
        event_time INTEGER NOT NULL, PRIMARY KEY(theme_id, archive_id, cluster_id))""",
    "CREATE INDEX IF NOT EXISTS idx_word_pulse_label_theme_time "
    "ON word_pulse_label(theme_id, rules_version, event_time)",
    """CREATE TABLE IF NOT EXISTS word_pulse_unclassified (
        theme_id INTEGER NOT NULL, day TEXT NOT NULL, rules_version INTEGER NOT NULL,
        count INTEGER NOT NULL, PRIMARY KEY(theme_id, day, rules_version))""",
    """CREATE TABLE IF NOT EXISTS word_pulse_cursor (
        group_id TEXT PRIMARY KEY, last_archive_id INTEGER NOT NULL, updated_at INTEGER NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS word_pulse_budget (
        group_id TEXT NOT NULL, day TEXT NOT NULL, used INTEGER NOT NULL,
        PRIMARY KEY(group_id, day))""",
    "DROP TABLE IF EXISTS word_pulse_charset",
    "DROP TABLE IF EXISTS word_pulse_bucket",
]


def ensure_schema() -> None:
    db.ensure_schema(SCHEMA_STATEMENTS)
    columns = {
        "word_pulse_theme": {
            "mode": "TEXT NOT NULL DEFAULT 'semantic'",
            "rules_version": "INTEGER NOT NULL DEFAULT 1",
            "backfill_version": "INTEGER NOT NULL DEFAULT 0",
            "backfill_next_id": "INTEGER",
            "backfill_until_id": "INTEGER",
        },
        "word_pulse_cluster": {
            "description": "TEXT NOT NULL DEFAULT ''",
            "aliases_json": "TEXT NOT NULL DEFAULT '[]'",
        },
    }

    def add_missing_columns(conn: sqlite3.Connection) -> None:
        for table, definitions in columns.items():
            existing = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
            for name, definition in definitions.items():
                if name not in existing:
                    # All interpolated identifiers come from the static mapping above.
                    conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")

    db.migrate(add_missing_columns)


def _clusters(conn: sqlite3.Connection, theme_id: int) -> tuple[ClusterRule, ...]:
    return tuple(
        ClusterRule(
            row["id"],
            row["name"],
            tuple(_ALIASES.validate_json(row["aliases_json"])),
            row["description"],
        )
        for row in conn.execute(
            "SELECT * FROM word_pulse_cluster WHERE theme_id=? ORDER BY id", (theme_id,)
        )
    )


def _theme(conn: sqlite3.Connection, row: sqlite3.Row) -> ThemeRule:
    return ThemeRule(
        row["id"],
        row["group_id"],
        row["name"],
        _MODE.validate_python(row["mode"]),
        row["rules_version"],
        row["backfill_version"],
        row["backfill_next_id"],
        row["backfill_until_id"],
        _clusters(conn, row["id"]),
    )


async def get_theme(group_id: str, name: str) -> ThemeRule | None:
    def read(conn: sqlite3.Connection) -> ThemeRule | None:
        row = conn.execute(
            "SELECT * FROM word_pulse_theme WHERE group_id=? AND name=?", (group_id, name)
        ).fetchone()
        return _theme(conn, row) if row else None

    return await db.transaction(read)


async def list_themes(group_id: str) -> list[ThemeRule]:
    def read(conn: sqlite3.Connection) -> list[ThemeRule]:
        return [
            _theme(conn, row)
            for row in conn.execute(
                "SELECT * FROM word_pulse_theme WHERE group_id=? ORDER BY id", (group_id,)
            )
        ]

    return await db.transaction(read)


async def list_groups_with_themes() -> list[str]:
    return [
        row["group_id"]
        for row in await db.fetch_all(
            "SELECT DISTINCT group_id FROM word_pulse_theme ORDER BY group_id"
        )
    ]


@dataclass(frozen=True, slots=True)
class RuleChange:
    added: tuple[str, ...]
    conflicts: tuple[tuple[str, str], ...]
    created: bool = False


def _touch(conn: sqlite3.Connection, theme_id: int) -> None:
    conn.execute(
        "UPDATE word_pulse_theme SET rules_version=rules_version+1, updated_at=? WHERE id=?",
        (int(time.time()), theme_id),
    )


def _owners(clusters: Sequence[ClusterRule]) -> dict[str, str]:
    owners = {}
    for cluster in clusters:
        owners[normalize(cluster.name)] = "已是子类"
        for alias in cluster.aliases:
            owners[normalize(alias)] = f"已是「{cluster.name}」的别名"
    return owners


async def add_clusters(group_id: str, theme_name: str, names: Sequence[str]) -> RuleChange:
    def operation(conn: sqlite3.Connection) -> RuleChange:
        now = int(time.time())
        row = conn.execute(
            "SELECT id FROM word_pulse_theme WHERE group_id=? AND name=?", (group_id, theme_name)
        ).fetchone()
        created = row is None
        if row is None:
            conn.execute(
                "INSERT INTO word_pulse_theme(group_id,name,created_at,updated_at) VALUES(?,?,?,?)",
                (group_id, theme_name, now, now),
            )
            row = conn.execute(
                "SELECT id FROM word_pulse_theme WHERE group_id=? AND name=?",
                (group_id, theme_name),
            ).fetchone()
        theme_id = row["id"]
        owners = _owners(_clusters(conn, theme_id))
        added, conflicts = [], []
        for name in names:
            key = normalize(name)
            if key in owners:
                conflicts.append((name, owners[key]))
                continue
            conn.execute(
                "INSERT INTO word_pulse_cluster(theme_id,name,created_at) VALUES(?,?,?)",
                (theme_id, name, now),
            )
            added.append(name)
            owners[key] = "已是子类"
        if added and not created:
            _touch(conn, theme_id)
        return RuleChange(tuple(added), tuple(conflicts), created)

    return await db.transaction(operation)


async def remove_clusters(theme_id: int, names: Sequence[str]) -> list[str]:
    def operation(conn: sqlite3.Connection) -> list[str]:
        wanted = {normalize(name) for name in names}
        removed = []
        for cluster in _clusters(conn, theme_id):
            if normalize(cluster.name) in wanted:
                conn.execute("DELETE FROM word_pulse_cluster WHERE id=?", (cluster.id,))
                removed.append(cluster.name)
        if removed:
            _touch(conn, theme_id)
        return removed

    return await db.transaction(operation)


async def delete_theme(theme_id: int) -> None:
    def operation(conn: sqlite3.Connection) -> None:
        conn.execute("DELETE FROM word_pulse_label WHERE theme_id=?", (theme_id,))
        conn.execute("DELETE FROM word_pulse_unclassified WHERE theme_id=?", (theme_id,))
        conn.execute("DELETE FROM word_pulse_theme WHERE id=?", (theme_id,))

    await db.transaction(operation)


def _find_cluster(conn: sqlite3.Connection, theme_id: int, name: str) -> ClusterRule:
    for cluster in _clusters(conn, theme_id):
        if normalize(cluster.name) == normalize(name):
            return cluster
    raise ValueError(f"主题中没有子类「{name}」")


async def add_aliases(theme_id: int, cluster_name: str, aliases: Sequence[str]) -> RuleChange:
    def operation(conn: sqlite3.Connection) -> RuleChange:
        cluster = _find_cluster(conn, theme_id, cluster_name)
        owners = _owners(_clusters(conn, theme_id))
        added, conflicts = [], []
        for alias in aliases:
            key = normalize(alias)
            if key in owners:
                conflicts.append((alias, owners[key]))
            else:
                added.append(alias)
                owners[key] = f"已是「{cluster.name}」的别名"
        if added:
            conn.execute(
                "UPDATE word_pulse_cluster SET aliases_json=? WHERE id=?",
                (json.dumps([*cluster.aliases, *added], ensure_ascii=False), cluster.id),
            )
            _touch(conn, theme_id)
        return RuleChange(tuple(added), tuple(conflicts))

    return await db.transaction(operation)


async def remove_aliases(theme_id: int, cluster_name: str, aliases: Sequence[str]) -> list[str]:
    def operation(conn: sqlite3.Connection) -> list[str]:
        cluster = _find_cluster(conn, theme_id, cluster_name)
        wanted = {normalize(alias) for alias in aliases}
        removed = [alias for alias in cluster.aliases if normalize(alias) in wanted]
        if removed:
            kept = [alias for alias in cluster.aliases if normalize(alias) not in wanted]
            conn.execute(
                "UPDATE word_pulse_cluster SET aliases_json=? WHERE id=?",
                (json.dumps(kept, ensure_ascii=False), cluster.id),
            )
            _touch(conn, theme_id)
        return removed

    return await db.transaction(operation)


async def set_description(theme_id: int, cluster_name: str, text: str) -> bool:
    def operation(conn: sqlite3.Connection) -> bool:
        cluster = _find_cluster(conn, theme_id, cluster_name)
        if cluster.description == text:
            return False
        conn.execute("UPDATE word_pulse_cluster SET description=? WHERE id=?", (text, cluster.id))
        _touch(conn, theme_id)
        return True

    return await db.transaction(operation)


async def set_mode(theme_id: int, mode: ThemeMode) -> bool:
    def operation(conn: sqlite3.Connection) -> bool:
        changed = (
            conn.execute(
                "UPDATE word_pulse_theme SET mode=? WHERE id=? AND mode<>?", (mode, theme_id, mode)
            ).rowcount
            > 0
        )
        if changed:
            _touch(conn, theme_id)
        return changed

    return await db.transaction(operation)


async def get_cursor(group_id: str) -> tuple[int, int] | None:
    row = await db.fetch_one(
        "SELECT last_archive_id,updated_at FROM word_pulse_cursor WHERE group_id=?", (group_id,)
    )
    return (row[0], row[1]) if row else None


async def init_cursor(group_id: str, last_id: int, now: int) -> None:
    await db.execute(
        "INSERT OR IGNORE INTO word_pulse_cursor VALUES(?,?,?)", (group_id, last_id, now)
    )


async def touch_cursor(group_id: str, now: int) -> None:
    await db.execute("UPDATE word_pulse_cursor SET updated_at=? WHERE group_id=?", (now, group_id))


async def init_backfill(
    theme_id: int, rules_version: int, next_id: int | None, until_id: int
) -> None:
    def operation(conn: sqlite3.Connection) -> None:
        changed = conn.execute(
            "UPDATE word_pulse_theme SET backfill_version=?,backfill_next_id=?,backfill_until_id=? WHERE id=? AND rules_version=?",
            (rules_version, next_id, until_id, theme_id, rules_version),
        ).rowcount
        if changed:
            conn.execute(
                "DELETE FROM word_pulse_label WHERE theme_id=? AND rules_version<?",
                (theme_id, rules_version),
            )
            conn.execute(
                "DELETE FROM word_pulse_unclassified WHERE theme_id=? AND rules_version<?",
                (theme_id, rules_version),
            )

    await db.transaction(operation)


def _write_outcome(
    conn: sqlite3.Connection, outcome: ClassifyOutcome, versions: dict[int, int]
) -> None:
    for label in outcome.labels:
        if label.theme_id not in versions:
            continue
        conn.execute(
            "INSERT OR IGNORE INTO word_pulse_label VALUES(?,?,?,?,?,?,?)",
            (
                label.theme_id,
                label.archive_id,
                label.cluster_id,
                label.source,
                versions[label.theme_id],
                label.user_id,
                label.event_time,
            ),
        )
    for (theme_id, day), count in outcome.unclassified.items():
        if theme_id in versions:
            conn.execute(
                """INSERT INTO word_pulse_unclassified VALUES(?,?,?,?)
                ON CONFLICT(theme_id,day,rules_version) DO UPDATE SET count=count+excluded.count""",
                (theme_id, day, versions[theme_id], count),
            )


def _write_budget(conn: sqlite3.Connection, group_id: str, used: int, now: int) -> None:
    if used:
        conn.execute(
            """INSERT INTO word_pulse_budget VALUES(?,?,?)
            ON CONFLICT(group_id,day) DO UPDATE SET used=used+excluded.used""",
            (group_id, day_of(now), used),
        )


async def commit_live_batch(
    group_id: str,
    outcome: ClassifyOutcome,
    new_cursor: int,
    rules_versions: dict[int, int],
    budget_used: int,
    now: int,
) -> None:
    def operation(conn: sqlite3.Connection) -> None:
        # Deletion during an AI request must not recreate orphan label rows.
        existing = {
            row[0]
            for row in conn.execute("SELECT id FROM word_pulse_theme WHERE group_id=?", (group_id,))
        }
        versions = {key: version for key, version in rules_versions.items() if key in existing}
        _write_outcome(conn, outcome, versions)
        _write_budget(conn, group_id, budget_used, now)
        conn.execute(
            "UPDATE word_pulse_cursor SET last_archive_id=?,updated_at=? WHERE group_id=?",
            (new_cursor, now, group_id),
        )

    await db.transaction(operation)


async def commit_backfill_chunk(
    theme_id: int,
    rules_version: int,
    outcome: ClassifyOutcome,
    next_id: int | None,
    budget_used: int,
    now: int,
) -> bool:
    def operation(conn: sqlite3.Connection) -> bool:
        row = conn.execute(
            "SELECT group_id FROM word_pulse_theme WHERE id=? AND rules_version=? AND backfill_version=?",
            (theme_id, rules_version, rules_version),
        ).fetchone()
        if row is None:
            return False
        _write_outcome(conn, outcome, {theme_id: rules_version})
        _write_budget(conn, row[0], budget_used, now)
        conn.execute(
            "UPDATE word_pulse_theme SET backfill_next_id=? WHERE id=?", (next_id, theme_id)
        )
        return True

    return await db.transaction(operation)


async def get_budget_used(group_id: str, day: str) -> int:
    row = await db.fetch_one(
        "SELECT used FROM word_pulse_budget WHERE group_id=? AND day=?", (group_id, day)
    )
    return row[0] if row else 0


async def purge_before(ts: int, day: str) -> int:
    def operation(conn: sqlite3.Connection) -> int:
        count = conn.execute("DELETE FROM word_pulse_label WHERE event_time<?", (ts,)).rowcount
        conn.execute("DELETE FROM word_pulse_unclassified WHERE day<?", (day,))
        conn.execute("DELETE FROM word_pulse_budget WHERE day<?", (day,))
        return count

    return await db.transaction(operation)


def _aggregate_clusters(
    conn: sqlite3.Connection, theme_id: int, rules_version: int, start_ts: int, end_ts: int
) -> list[ClusterCounts]:
    rows = conn.execute(
        """SELECT cluster_id,COUNT(DISTINCT archive_id),COUNT(DISTINCT user_id)
        FROM word_pulse_label WHERE theme_id=? AND rules_version=? AND event_time>=? AND event_time<?
        GROUP BY cluster_id""",
        (theme_id, rules_version, start_ts, end_ts),
    )
    return [ClusterCounts(*row) for row in rows]


async def aggregate_clusters(
    theme_id: int, rules_version: int, start_ts: int, end_ts: int
) -> list[ClusterCounts]:
    return await db.transaction(
        lambda conn: _aggregate_clusters(conn, theme_id, rules_version, start_ts, end_ts)
    )


def _aggregate_relevant(
    conn: sqlite3.Connection, theme_id: int, rules_version: int, start_ts: int, end_ts: int
) -> tuple[int, int]:
    row = conn.execute(
        """SELECT COUNT(DISTINCT archive_id),COUNT(DISTINCT user_id)
        FROM word_pulse_label WHERE theme_id=? AND rules_version=? AND event_time>=? AND event_time<?""",
        (theme_id, rules_version, start_ts, end_ts),
    ).fetchone()
    return row[0], row[1]


async def aggregate_relevant(
    theme_id: int, rules_version: int, start_ts: int, end_ts: int
) -> tuple[int, int]:
    return await db.transaction(
        lambda conn: _aggregate_relevant(conn, theme_id, rules_version, start_ts, end_ts)
    )


def _label_points(
    conn: sqlite3.Connection, theme_id: int, rules_version: int, start_ts: int, end_ts: int
) -> list[tuple[int, int, int]]:
    rows = conn.execute(
        """SELECT archive_id,cluster_id,event_time FROM word_pulse_label
        WHERE theme_id=? AND rules_version=? AND event_time>=? AND event_time<?""",
        (theme_id, rules_version, start_ts, end_ts),
    )
    return [(row[0], row[1], row[2]) for row in rows]


async def fetch_label_points(
    theme_id: int, rules_version: int, start_ts: int, end_ts: int
) -> list[tuple[int, int, int]]:
    return await db.transaction(
        lambda conn: _label_points(conn, theme_id, rules_version, start_ts, end_ts)
    )


def _sum_unclassified(
    conn: sqlite3.Connection, theme_id: int, rules_version: int, start_day: str, end_day: str
) -> int:
    row = conn.execute(
        """SELECT COALESCE(SUM(count),0) FROM word_pulse_unclassified
        WHERE theme_id=? AND rules_version=? AND day>=? AND day<=?""",
        (theme_id, rules_version, start_day, end_day),
    ).fetchone()
    return row[0]


async def sum_unclassified(theme_id: int, rules_version: int, start_day: str, end_day: str) -> int:
    return await db.transaction(
        lambda conn: _sum_unclassified(conn, theme_id, rules_version, start_day, end_day)
    )


async def load_report_data(
    group_id: str, name: str, days: int, now: int, *, semantic_available: bool
) -> ReportData | None:
    """Read rules, progress and counts under the same connection lock and SQL snapshot."""
    start, end = window_bounds(now, days)

    def read(conn: sqlite3.Connection) -> ReportData | None:
        # SELECT does not start a transaction under sqlite3's legacy transaction control.
        conn.execute("BEGIN")
        row = conn.execute(
            "SELECT * FROM word_pulse_theme WHERE group_id=? AND name=?", (group_id, name)
        ).fetchone()
        if row is None:
            return None
        theme = _theme(conn, row)
        cursor = conn.execute(
            "SELECT updated_at FROM word_pulse_cursor WHERE group_id=?", (group_id,)
        ).fetchone()
        identity = (theme.id, theme.rules_version)
        return build(
            theme,
            days,
            cur_clusters=_aggregate_clusters(conn, *identity, start, end),
            prev_clusters=_aggregate_clusters(
                conn, *identity, start - days * SECONDS_PER_DAY, start
            ),
            cur_relevant=_aggregate_relevant(conn, *identity, start, end),
            daily_rows=_label_points(conn, *identity, start, end),
            unclassified=_sum_unclassified(conn, *identity, day_of(start), day_of(now)),
            data_as_of=cursor[0] if cursor else None,
            semantic_enabled=theme.mode == "semantic" and semantic_available,
            now=now,
        )

    return await db.transaction(read)


async def recent_example_ids(
    theme_id: int, rules_version: int, cluster_ids: Sequence[int], start_ts: int, end_ts: int
) -> dict[int, int]:
    result = {}
    for cluster_id in cluster_ids:
        row = await db.fetch_one(
            """SELECT archive_id FROM word_pulse_label
            WHERE theme_id=? AND rules_version=? AND cluster_id=? AND event_time>=? AND event_time<?
            ORDER BY event_time DESC,archive_id DESC LIMIT 1""",
            (theme_id, rules_version, cluster_id, start_ts, end_ts),
        )
        if row:
            result[cluster_id] = row[0]
    return result


async def candidate_archive_ids(
    theme_id: int, rules_version: int, start: int, end: int
) -> list[int]:
    """Select current-version AI evidence without any literal evidence for the same theme/message."""
    rows = await db.fetch_all(
        """SELECT DISTINCT ai.archive_id FROM word_pulse_label AS ai
        WHERE ai.theme_id=? AND ai.rules_version=? AND ai.event_time>=? AND ai.event_time<?
        AND ai.source='ai' AND NOT EXISTS (
            SELECT 1 FROM word_pulse_label AS literal
            WHERE literal.theme_id=ai.theme_id AND literal.archive_id=ai.archive_id
            AND literal.rules_version=ai.rules_version AND literal.source='literal')
        ORDER BY ai.archive_id""",
        (theme_id, rules_version, start, end),
    )
    return [row[0] for row in rows]
