"""Render stored daily counts without pyplot or event-loop CPU work."""

import io
import threading
from pathlib import Path

from matplotlib.figure import Figure
from matplotlib.font_manager import FontProperties
from matplotlib.ticker import MaxNLocator

from .core.aggregate import ReportData
from .core.types import OTHER

_FONT_PATH = Path(__file__).resolve().parents[3] / "fonts" / "SourceHanSansSC-Regular.ttf"
_FONT = FontProperties(fname=str(_FONT_PATH)) if _FONT_PATH.is_file() else None
_COLORS = ("#d1495b", "#00798c", "#edae49", "#30638e", "#5f7a61")
_CHART_LOCK = threading.Lock()


def build_figure(data: ReportData) -> Figure:
    """Build one total series and up to five cluster series; today's markers are hollow."""
    figure = Figure(figsize=(9, 4.8), layout="constrained")
    axis = figure.subplots()
    positions = list(range(len(data.daily)))
    series = [("相关讨论", data.daily_totals, "#202124")]
    top = [cluster for cluster in data.clusters if cluster.cluster_id != OTHER][: len(_COLORS)]
    series.extend(
        (cluster.name, tuple(counts[cluster.cluster_id] for _, counts in data.daily), color)
        for cluster, color in zip(top, _COLORS, strict=False)
    )
    for name, values, color in series:
        axis.plot(positions, values, color=color, linewidth=1.8, label=name)
        axis.plot(
            positions[:-1], values[:-1], color=color, marker="o", linestyle="none", markersize=4
        )
        axis.plot(
            positions[-1:],
            values[-1:],
            color=color,
            marker="o",
            linestyle="none",
            markerfacecolor="white",
            markersize=6,
        )
    axis.set_xticks(
        positions, [day[5:] for day, _ in data.daily], fontproperties=_FONT, rotation=45
    )
    axis.set_ylim(bottom=0)
    axis.yaxis.set_major_locator(MaxNLocator(integer=True))
    axis.set_ylabel("消息条数", fontproperties=_FONT)
    axis.set_title(
        f"{data.theme.name} · 近{data.window_days}天（空心点为今日）", fontproperties=_FONT
    )
    axis.grid(axis="y", color="#d9dde3", linewidth=0.8)
    axis.spines[["top", "right"]].set_visible(False)
    axis.legend(prop=_FONT, frameon=False, ncols=2)
    return figure


def render_trend_chart(data: ReportData) -> bytes | None:
    if not any(data.daily_totals):
        return None
    # Matplotlib's shared font/render state is not thread-safe across theme queries.
    with _CHART_LOCK:
        figure = build_figure(data)
        try:
            output = io.BytesIO()
            figure.savefig(output, format="png", dpi=150, facecolor="white")
            return output.getvalue()
        finally:
            figure.clear()
