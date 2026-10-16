"""Scheduled archive consumption and label retention."""

import time

from nonebot import get_plugin_config, require

from . import db, pipeline
from .config import Config
from .core.timeutil import SECONDS_PER_DAY, day_of

scheduler = require("nonebot_plugin_apscheduler").scheduler
config = get_plugin_config(Config)


@scheduler.scheduled_job(
    "interval",
    minutes=config.word_pulse_tick_minutes,
    id="word_pulse_tick",
    max_instances=1,
    coalesce=True,
    misfire_grace_time=60,
)
async def word_pulse_tick() -> None:
    await pipeline.tick(int(time.time()))


@scheduler.scheduled_job(
    "cron",
    hour=3,
    minute=40,
    id="word_pulse_cleanup",
    misfire_grace_time=300,
)
async def word_pulse_cleanup() -> None:
    cutoff = int(time.time()) - config.word_pulse_label_retention_days * SECONDS_PER_DAY
    await db.purge_before(cutoff, day_of(cutoff))
