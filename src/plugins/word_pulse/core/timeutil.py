"""Shanghai calendar windows, independent of the process timezone."""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Asia/Shanghai")
SECONDS_PER_DAY = 86400


def day_of(ts: int) -> str:
    return datetime.fromtimestamp(ts, TZ).date().isoformat()


def window_bounds(now: int, days: int) -> tuple[int, int]:
    if days < 1:
        raise ValueError("days: must be a positive integer")
    midnight = datetime.fromtimestamp(now, TZ).replace(hour=0, minute=0, second=0, microsecond=0)
    return int((midnight - timedelta(days=days - 1)).timestamp()), now + 1
