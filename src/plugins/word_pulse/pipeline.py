"""Consume archive messages and reconcile rule versions in bounded background batches."""

import asyncio
from collections.abc import Sequence

from nonebot import get_plugin_config, logger, require

from . import db
from .classifiers import AIClassifier, ai_available
from .config import (
    BACKFILL_MAX_PER_TICK,
    BATCH_SIZE,
    CLASSIFY_TIMEOUT,
    FAIL_SKIP_THRESHOLD,
    LIVE_MAX_PER_TICK,
    Config,
)
from .core.budget import take
from .core.text import is_noise
from .core.timeutil import day_of, window_bounds
from .core.types import EMPTY_OUTCOME, ClassifyOutcome, Msg, ThemeRule
from .errors import WordPulseAIError

_archive = require("src.plugins.message_archive").db
config = get_plugin_config(Config)
_tick_lock = asyncio.Lock()
_fail_counts: dict[str, int] = {}


async def tick(now: int) -> None:
    if not config.word_pulse_plugin_enabled or _tick_lock.locked():
        return
    async with _tick_lock:
        for group_id in await db.list_groups_with_themes():
            if not _group_enabled(group_id):
                continue
            try:
                await _tick_group(group_id, now)
            except Exception:
                logger.exception("Word Pulse group {} tick failed", group_id)


def _group_enabled(group_id: str) -> bool:
    match config.word_pulse_group_mode:
        case "whitelist":
            return group_id in config.word_pulse_group_whitelist
        case "blacklist":
            return group_id not in config.word_pulse_group_blacklist
        case _:
            return True


async def _tick_group(group_id: str, now: int) -> None:
    await ensure_cursor(group_id, now)
    for theme in await db.list_themes(group_id):
        await reconcile(theme, now)
    await run_live(group_id, now)
    for theme in await db.list_themes(group_id):
        if theme.backfill_next_id is not None:
            await run_backfill(theme, now)


async def ensure_cursor(group_id: str, now: int) -> None:
    if await db.get_cursor(group_id) is None:
        await db.init_cursor(group_id, await _archive.get_group_max_id(group_id), now)


async def _cursor(group_id: str) -> tuple[int, int]:
    cursor = await db.get_cursor(group_id)
    if cursor is None:
        raise RuntimeError("cursor: ensure_cursor must run before consumption")
    return cursor


async def reconcile(theme: ThemeRule, now: int) -> None:
    if theme.backfill_version == theme.rules_version:
        return
    start, _ = window_bounds(now, config.word_pulse_backfill_days)
    first_id = await _archive.get_group_first_id_since(theme.group_id, start)
    until_id, _ = await _cursor(theme.group_id)
    next_id = first_id if first_id is not None and first_id <= until_id else None
    await db.init_backfill(theme.id, theme.rules_version, next_id, until_id, start)


async def run_live(group_id: str, now: int) -> None:
    cursor, _ = await _cursor(group_id)
    raw = await _archive.fetch_group_texts_after_id(group_id, cursor, limit=LIVE_MAX_PER_TICK)
    if not raw:
        await db.touch_cursor(group_id, now)
        return
    themes = await db.list_themes(group_id)
    msgs = [
        Msg(row.id, row.event_time, row.user_id, row.plain_text)
        for row in raw
        if not is_noise(row.plain_text, row.user_id, self_id=row.self_id)
    ]
    result = await _classify_with_budget(group_id, msgs, themes, key=f"live:{group_id}", now=now)
    if result is None:
        return
    outcome, used = result
    await db.commit_live_batch(
        group_id,
        outcome,
        raw[-1].id,
        {theme.id: theme.rules_version for theme in themes},
        used,
        now,
    )


async def run_backfill(theme: ThemeRule, now: int) -> None:
    if theme.backfill_next_id is None or theme.backfill_until_id is None:
        return
    raw = await _archive.fetch_group_texts_after_id(
        theme.group_id,
        theme.backfill_next_id - 1,
        until_id=theme.backfill_until_id,
        limit=BACKFILL_MAX_PER_TICK,
    )
    msgs = [
        Msg(row.id, row.event_time, row.user_id, row.plain_text)
        for row in raw
        if not is_noise(row.plain_text, row.user_id, self_id=row.self_id)
    ]
    result = await _classify_with_budget(
        theme.group_id, msgs, [theme], key=f"bf:{theme.id}", now=now
    )
    if result is None:
        return
    outcome, used = result
    done = len(raw) < BACKFILL_MAX_PER_TICK or raw[-1].id >= theme.backfill_until_id
    next_id = None if done else raw[-1].id + 1
    await db.commit_backfill_chunk(theme.id, theme.rules_version, outcome, next_id, used, now)


async def _classify_with_budget(
    group_id: str,
    msgs: Sequence[Msg],
    themes: Sequence[ThemeRule],
    *,
    key: str,
    now: int,
) -> tuple[ClassifyOutcome, int] | None:
    if not msgs:
        _fail_counts.pop(key, None)
        return EMPTY_OUTCOME, 0
    if not any(theme.mode == "semantic" for theme in themes) or not ai_available():
        _fail_counts.pop(key, None)
        return await AIClassifier.literal_only(msgs, themes), 0
    used_today = await db.get_budget_used(group_id, day_of(now))
    count = take(config.word_pulse_ai_daily_budget - used_today, len(msgs))
    head, tail = msgs[:count], msgs[count:]
    classifier = AIClassifier(
        batch_size=BATCH_SIZE,
        output_mode=config.word_pulse_ai_output_mode,
        timeout=CLASSIFY_TIMEOUT,
    )
    try:
        head_out = await classifier.classify(head, themes) if head else EMPTY_OUTCOME
    except WordPulseAIError:
        _fail_counts[key] = _fail_counts.get(key, 0) + 1
        logger.exception(
            "Word Pulse classification failed for {} (attempt {})", key, _fail_counts[key]
        )
        if _fail_counts[key] < FAIL_SKIP_THRESHOLD:
            return None
        head_out, count, tail = EMPTY_OUTCOME, 0, msgs
    _fail_counts.pop(key, None)
    tail_out = await AIClassifier.literal_only(tail, themes)
    return head_out | tail_out, count
