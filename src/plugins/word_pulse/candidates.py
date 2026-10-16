"""Administrator-only local discovery from semantic evidence without literal matches."""

import asyncio

from nonebot import require

from . import db
from .core.candidates import discover_candidates
from .core.timeutil import window_bounds
from .core.types import Msg, ThemeRule

_archive = require("src.plugins.message_archive").db
WINDOW_DAYS = 7
_scan_locks: dict[int, asyncio.Lock] = {}


async def scan_candidates(theme: ThemeRule, now: int) -> str:
    if theme.mode == "literal":
        return "字面模式的主题不支持候选发现"
    lock = _scan_locks.setdefault(theme.id, asyncio.Lock())
    if lock.locked():
        return "该主题正在扫描候选，请稍后再试"
    async with lock:
        ids = await db.candidate_archive_ids(
            theme.id, theme.rules_version, *window_bounds(now, WINDOW_DAYS)
        )
        texts = await _archive.fetch_texts_by_ids(ids)
        messages = [
            Msg(row.id, row.event_time, row.user_id, row.plain_text) for row in texts.values()
        ]
        # Shield the worker so cancellation cannot release the scan lock while CPU work continues.
        worker = asyncio.create_task(asyncio.to_thread(discover_candidates, theme, messages))
        try:
            phrases = await asyncio.shield(worker)
        except asyncio.CancelledError:
            while not worker.done():
                try:
                    await asyncio.shield(worker)
                except asyncio.CancelledError:
                    continue
            worker.result()
            raise
    if not phrases:
        return f"「{theme.name}」近{WINDOW_DAYS}天暂无符合条件的候选"
    lines = [f"「{theme.name}」近{WINDOW_DAYS}天候选："]
    lines.extend(
        f"· {item.phrase}（{item.message_count}条 / {item.user_count}人）" for item in phrases
    )
    lines.append(
        f"可用「词频别名添加 {theme.name} <子类> <别名>」或「词频添加 {theme.name} <子类>」收录"
    )
    return "\n".join(lines)
