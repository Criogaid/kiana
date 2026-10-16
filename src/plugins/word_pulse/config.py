"""Word Pulse operational configuration and command limits."""

from typing import Literal

from pydantic import BaseModel, Field

from src.plugins.group_permission import GroupPermissionMixin

BATCH_SIZE = 50
LIVE_MAX_PER_TICK = 1000
BACKFILL_MAX_PER_TICK = 500
FAIL_SKIP_THRESHOLD = 3
CLASSIFY_TIMEOUT = 60.0
TREND_TIMEOUT = 15.0
MAX_WINDOW_DAYS = 31
DEFAULT_WINDOW_DAYS = 7
RESULT_CACHE_TTL = 300
QUERY_COOLDOWN = 30
MAX_TEXT_CHARS = 300
MAX_NAME_CHARS = 20
MAX_DESCRIPTION_CHARS = 50
MAX_TREND_CHARS = 60
MAX_EXAMPLE_CHARS = 40
MAX_EXAMPLE_CLUSTERS = 3


class Config(GroupPermissionMixin, BaseModel):
    word_pulse_plugin_enabled: bool = False
    word_pulse_ai_daily_budget: int = Field(2000, ge=0)
    word_pulse_ai_output_mode: Literal["strict", "json"] = "strict"
    word_pulse_tick_minutes: int = Field(10, ge=1, le=60)
    word_pulse_backfill_days: int = Field(7, ge=1, le=31)
    word_pulse_label_retention_days: int = Field(31, ge=7, le=365)
    word_pulse_show_examples: bool = False
    word_pulse_group_mode: Literal["all", "whitelist", "blacklist"] = "all"
    word_pulse_group_whitelist: list[str] = Field(default_factory=list)
    word_pulse_group_blacklist: list[str] = Field(default_factory=list)
