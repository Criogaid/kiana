"""Shanghai calendar windows, independent of the process timezone."""

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Asia/Shanghai")
SECONDS_PER_DAY = 86400
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


def local_datetime(ts: int) -> datetime:
    """Convert timestamps arithmetically, including pre-epoch dates on Windows."""
    return (_EPOCH + timedelta(seconds=ts)).astimezone(TZ)


def day_of(ts: int) -> str:
    return local_datetime(ts).date().isoformat()


def window_bounds(now: int, days: int) -> tuple[int, int]:
    if days < 1:
        raise ValueError("days: must be a positive integer")
    midnight = local_datetime(now).replace(hour=0, minute=0, second=0, microsecond=0)
    return int((midnight - timedelta(days=days - 1)).timestamp()), now + 1
