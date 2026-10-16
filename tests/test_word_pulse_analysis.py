"""Literal/semantic evidence and local aggregation contracts."""

from dataclasses import replace
from datetime import datetime

import pytest


def theme():
    from src.plugins.word_pulse.core.types import ClusterRule, ThemeRule
    return ThemeRule(1, "g", "游戏", "semantic", 1, 1, None, None, (
        ClusterRule(10, "苹果", ("果子",), ""), ClusterRule(11, "苹果手机", (), ""),
        ClusterRule(12, "MC", (), ""),
    ))


@pytest.mark.parametrize("text,relevant,hits", [
    ("苹果手机发布", True, {11}), ("苹果手机发布，苹果回应", True, {10, 11}),
    ("果子好吃", True, {10}), ("MC 和 ｍｃ", True, {12}), ("mcu amc mc2", False, set()),
    ("游戏", True, set()), ("完全无关", False, set()),
])
def test_literal_matching(app, text, relevant, hits):
    from src.plugins.word_pulse.core.text import LiteralMatcher
    assert LiteralMatcher(theme()).match(text) == (relevant, frozenset(hits))


@pytest.mark.parametrize("text,user,noise", [("😀！！！", "u", True), ("啊", "u", True), ("词频 游戏", "u", True), ("/命令", "u", True), ("普通聊天", "bot", True), ("普通聊天", "u", False)])
def test_noise_filter(app, text, user, noise):
    from src.plugins.word_pulse.core.text import is_noise
    assert is_noise(text, user, self_id="bot") == noise


@pytest.mark.parametrize("relevant,literal,ai_relevant,ai_hits,expected", [
    (False, set(), False, set(), []), (True, set(), False, set(), [(0, "literal")]),
    (False, set(), True, set(), [(0, "ai")]),
    (True, {10}, True, {10, 11}, [(10, "literal"), (11, "ai")]),
    (True, {10}, False, set(), [(10, "literal")]),
])
def test_union_and_other_category(app, relevant, literal, ai_relevant, ai_hits, expected):
    from src.plugins.word_pulse.core.merge import AIVerdict, merge
    from src.plugins.word_pulse.core.types import Msg
    result = merge(1, Msg(7, 100, "u", "text"), relevant, frozenset(literal), AIVerdict(ai_relevant, frozenset(ai_hits)))
    assert [(label.cluster_id, label.source) for label in result] == expected
    assert all(label.archive_id == 7 and label.user_id == "u" for label in result)


async def test_literal_fallback_counts_only_semantic_messages(app):
    from src.plugins.word_pulse.classifiers import AIClassifier, LiteralClassifier
    from src.plugins.word_pulse.core.types import Msg
    msgs = [Msg(1, 100, "u", "果子"), Msg(2, 100, "u", "其他聊天")]
    semantic = theme()
    literal = replace(semantic, id=2, mode="literal")
    result = await AIClassifier.literal_only(msgs, [semantic, literal])
    assert sum(result.unclassified.values()) == 2
    assert {key[0] for key in result.unclassified} == {1}
    assert len(result.labels) == 2
    assert not (await LiteralClassifier().classify(msgs, [literal])).unclassified


def test_aggregate_uses_distinct_denominator_and_fills_dates(app):
    from src.plugins.word_pulse.core.aggregate import ClusterCounts, build
    from src.plugins.word_pulse.core.timeutil import TZ
    now = int(datetime(2026, 10, 16, 12, tzinfo=TZ).timestamp())
    result = build(theme(), 3, cur_clusters=[ClusterCounts(10, 2, 1), ClusterCounts(11, 2, 2), ClusterCounts(0, 1, 1)], prev_clusters=[ClusterCounts(10, 1, 1)], cur_relevant=(3, 2), daily_rows=[(1, 10, now), (1, 10, now), (1, 11, now)], unclassified=2, data_as_of=now, semantic_enabled=True, now=now)
    assert result.relevant_messages == 3
    assert [r.cluster_id for r in result.clusters] == [10, 11, 0]
    assert result.clusters[0].percent == 67
    assert result.clusters[0].delta == 1
    assert len(result.daily) == 3
    assert all(count == 0 for count in result.daily[0][1].values())
    assert result.daily[-1][1][10] == 1
    assert not result.backfilling


def test_windows_and_budget_boundaries(app):
    from src.plugins.word_pulse.core.budget import take
    from src.plugins.word_pulse.core.timeutil import TZ, day_of, window_bounds
    now = int(datetime(2026, 10, 16, tzinfo=TZ).timestamp())
    assert window_bounds(now, 1) == (now, now + 1)
    assert day_of(now - 1) == "2026-10-15"
    assert take(-1, 10) == 0
    assert take(3, 10) == 3
    assert take(10, 3) == 3


@pytest.mark.parametrize("coverage_since,backfill_version,next_id,previous_start,expected", [
    pytest.param(None, 1, None, 500, False, id="unknown-coverage"),
    pytest.param(500, 0, None, 500, False, id="stale-backfill-version"),
    pytest.param(500, 1, 7, 500, False, id="pending-backfill"),
    pytest.param(500, 1, None, 500, True, id="coverage-boundary-inclusive"),
    pytest.param(500, 1, None, 499, False, id="before-coverage"),
    pytest.param(0, 1, None, 100, True, id="retention-boundary-inclusive"),
    pytest.param(0, 1, None, 99, False, id="before-retention"),
    pytest.param(500, 1, None, 501, True, id="after-both-boundaries"),
])
def test_previous_window_complete(app, coverage_since, backfill_version, next_id, previous_start, expected):
    from src.plugins.word_pulse.core.aggregate import previous_window_complete
    from src.plugins.word_pulse.core.timeutil import SECONDS_PER_DAY
    rule = replace(theme(), coverage_since=coverage_since, backfill_version=backfill_version, backfill_next_id=next_id)
    retention_days = 31
    now = retention_days * SECONDS_PER_DAY + 100
    assert previous_window_complete(rule, previous_start, now, retention_days) is expected


@pytest.mark.parametrize("version,next_id,expected", [(1, None, False), (0, None, True), (1, 7, True), (0, 7, True)])
def test_is_backfilling(app, version, next_id, expected):
    from src.plugins.word_pulse.core.aggregate import is_backfilling
    assert is_backfilling(replace(theme(), backfill_version=version, backfill_next_id=next_id)) is expected
