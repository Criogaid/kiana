"""Chart semantics, PNG rendering and report delivery fallback."""

import io
import time
from unittest.mock import AsyncMock

from PIL import Image


def data():
    from src.plugins.word_pulse.core.aggregate import ClusterCounts, build
    from src.plugins.word_pulse.core.types import ClusterRule, ThemeRule
    theme = ThemeRule(1, "g", "炒股", "literal", 1, 1, None, None,
                      tuple(ClusterRule(i, f"子类{i}", (), "") for i in range(1, 7)))
    return build(theme, 7, cur_clusters=[ClusterCounts(i, 1, 1) for i in range(1, 7)],
                 prev_clusters=[], cur_relevant=(1, 1),
                 daily_rows=[(9, i, 1800000000) for i in range(1, 7)],
                 unclassified=0, data_as_of=1800000000, semantic_enabled=False, now=1800000000)


def test_chart_distinct_total_top_five_and_hollow_today(tmp_path):
    from src.plugins.word_pulse.render import build_figure, render_trend_chart
    report = data()
    assert report.daily_totals == (0, 0, 0, 0, 0, 0, 1)
    assert sum(report.daily[-1][1].values()) == 6
    figure = build_figure(report)
    try:
        lines = figure.axes[0].get_lines()
        assert len(lines) == 18  # Six series, each with history and today's separate marker.
        assert list(lines[0].get_ydata()) == list(report.daily_totals)
        for today in lines[2::3]:
            assert today.get_markerfacecolor() == "white"
            assert list(today.get_xdata()) == [6]
    finally:
        figure.clear()
    png = render_trend_chart(report)
    image = Image.open(io.BytesIO(png))
    assert image.format == "PNG" and image.size == (1350, 720)
    assert image.getbbox() is not None
    (tmp_path / "word-pulse-preview.png").write_bytes(png)


def test_all_zero_does_not_render(monkeypatch):
    from dataclasses import replace
    from src.plugins.word_pulse import render
    def fail(*args):
        raise AssertionError("zero data must not create a figure")
    monkeypatch.setattr(render, "build_figure", fail)
    assert render.render_trend_chart(replace(data(), daily_totals=(0,) * 7)) is None


async def test_query_sends_image_and_falls_back_to_text_when_rendering_fails(app, monkeypatch):
    from nonebot.adapters.onebot.v11 import Message
    from src.plugins.word_pulse import db, handlers, render, report
    from src.plugins.word_pulse.commands import parse
    from src.plugins.word_pulse.core.types import ClassifyOutcome, Label
    now = int(time.time())
    await db.add_clusters("g", "炒股", ["割肉"])
    theme = await db.get_theme("g", "炒股")
    await db.set_mode(theme.id, "literal")
    theme = await db.get_theme("g", "炒股")
    await db.init_cursor("g", 0, now)
    await db.commit_live_batch("g", ClassifyOutcome((Label(theme.id, 1, theme.clusters[0].id, "literal", "u", now),), {}),
                               1, {theme.id: theme.rules_version}, 0, now)
    monkeypatch.setattr(report, "_trend_sentence", AsyncMock(return_value=None))
    response = await handlers.dispatch("g", parse("词频 炒股"))
    assert isinstance(response, Message)
    assert response["image"] and "相关讨论 1 条" in response.extract_plain_text()
    report.result_cache.clear()
    def broken(data):
        raise RuntimeError("injected rendering failure")
    monkeypatch.setattr(render, "render_trend_chart", broken)
    response = await handlers.dispatch("g", parse("词频 炒股"))
    assert isinstance(response, str) and "相关讨论 1 条" in response
