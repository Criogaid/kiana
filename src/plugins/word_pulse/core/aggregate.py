"""Build report values from version-filtered SQL aggregates and label points."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import timedelta

from .timeutil import day_of, local_datetime, window_bounds
from .types import OTHER, ThemeRule


@dataclass(frozen=True, slots=True)
class ClusterCounts:
    cluster_id: int
    messages: int
    users: int


@dataclass(frozen=True, slots=True)
class ClusterStat:
    cluster_id: int
    name: str
    messages: int
    users: int
    percent: int
    delta: int | None


@dataclass(frozen=True, slots=True)
class ReportData:
    theme: ThemeRule
    window_days: int
    relevant_messages: int
    relevant_users: int
    clusters: tuple[ClusterStat, ...]
    daily: tuple[tuple[str, dict[int, int]], ...]
    daily_totals: tuple[int, ...]
    unclassified: int
    data_as_of: int | None
    semantic_enabled: bool
    backfilling: bool


def build(
    theme: ThemeRule,
    window_days: int,
    *,
    cur_clusters: Sequence[ClusterCounts],
    prev_clusters: Sequence[ClusterCounts],
    cur_relevant: tuple[int, int],
    daily_rows: Sequence[tuple[int, int, int]],
    unclassified: int,
    data_as_of: int | None,
    semantic_enabled: bool,
    now: int,
) -> ReportData:
    """Use distinct relevant messages as the percentage denominator, including zero days."""
    names = {cluster.id: cluster.name for cluster in theme.clusters}
    names[OTHER] = "其他"
    previous = {row.cluster_id: row.messages for row in prev_clusters}
    messages, users = cur_relevant
    clusters = tuple(
        ClusterStat(
            row.cluster_id,
            names[row.cluster_id],
            row.messages,
            row.users,
            round(row.messages / messages * 100) if messages else 0,
            row.messages - previous.get(row.cluster_id, 0) if previous else None,
        )
        for row in sorted(
            cur_clusters, key=lambda row: (row.cluster_id == OTHER, -row.messages, row.cluster_id)
        )
        if row.messages and row.cluster_id in names
    )
    first_day = local_datetime(window_bounds(now, window_days)[0]).date()
    buckets: dict[str, dict[int, set[int]]] = {
        (first_day + timedelta(days=offset)).isoformat(): {cluster: set() for cluster in names}
        for offset in range(window_days)
    }
    for archive_id, cluster_id, event_time in daily_rows:
        day = day_of(event_time)
        if day in buckets and cluster_id in names:
            buckets[day][cluster_id].add(archive_id)
    daily = tuple(
        (day, {cluster: len(ids) for cluster, ids in counts.items()})
        for day, counts in buckets.items()
    )
    return ReportData(
        theme,
        window_days,
        messages,
        users,
        clusters,
        daily,
        tuple(len(set().union(*counts.values())) for counts in buckets.values()),
        unclassified,
        data_as_of,
        semantic_enabled,
        theme.backfill_version != theme.rules_version or theme.backfill_next_id is not None,
    )
