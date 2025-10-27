import http.client
import io
import json
import re
import time
from collections import deque
from datetime import datetime

import matplotlib.pyplot as plt
from nonebot import get_driver, get_plugin_config, logger, on_fullmatch, on_regex, require
from nonebot.adapters.onebot.v11 import Bot, Event, MessageSegment
from nonebot.params import RegexGroup
from nonebot.plugin import PluginMetadata

from src.storage import get_db

from .config import Config

__plugin_meta__ = PluginMetadata(
    name="gold",
    description="实时黄金价格查询和走势图生成",
    usage=(
        "金价 - 查询当前金价\n"
        "金价走势 [时间] - 查看金价走势图\n"
        "时间格式: 1小时、24小时、7天、1月等"
    ),
    config=Config,
)

config = get_plugin_config(Config)


# ==================== Rule 检查函数 ====================


async def is_price_query_enabled() -> bool:
    """检查金价查询功能是否启用"""
    return config.gold_plugin_enabled and config.gold_enable_price_query


async def is_chart_enabled() -> bool:
    """检查走势图功能是否启用"""
    return config.gold_plugin_enabled and config.gold_enable_chart


# ==================== 事件响应器 ====================

gold = on_fullmatch("金价", rule=is_price_query_enabled)
gold_chart = on_regex(
    r"^(金价走势|金价趋势|黄金走势|黄金趋势|金价图|黄金图)\s*(.*)$",
    rule=is_chart_enabled,
    priority=5,
    block=True,
)

# 存储冷却时间的字典，每个群单独冷却
cooldown_dict = {}

PRICE_HISTORY_LIMIT = max(86400, config.price_history_limit)
MIN_WINDOW_SECONDS = 60
CHART_WINDOW_SECONDS = max(MIN_WINDOW_SECONDS, config.chart_window_hours * 3600)
price_history: deque[tuple[float, float]] = deque(maxlen=PRICE_HISTORY_LIMIT)

scheduler = require("nonebot_plugin_apscheduler").scheduler
driver = get_driver()

db = get_db()
db.ensure_schema(
    [
        """
        CREATE TABLE IF NOT EXISTS gold_price_history (
            timestamp REAL PRIMARY KEY,
            price REAL NOT NULL
        )
        """
    ]
)


async def load_price_history() -> None:
    """从数据库加载最近的价格历史"""
    rows = await db.fetch_all(
        """
        SELECT timestamp, price
        FROM gold_price_history
        ORDER BY timestamp DESC
        LIMIT ?
        """,
        (PRICE_HISTORY_LIMIT,),
    )

    price_history.clear()
    for row in reversed(rows):
        price_history.append((row["timestamp"], row["price"]))

    if rows:
        logger.info(f"已从数据库加载 {len(rows)} 条历史金价数据")


async def persist_price(timestamp: float, price: float) -> None:
    """写入数据库并维护内存中的价格历史"""
    if len(price_history) == PRICE_HISTORY_LIMIT:
        oldest_timestamp, _ = price_history.popleft()
        await db.execute(
            "DELETE FROM gold_price_history WHERE timestamp = ?",
            (oldest_timestamp,),
        )

    price_history.append((timestamp, price))
    await db.execute(
        """
        INSERT OR REPLACE INTO gold_price_history (timestamp, price)
        VALUES (?, ?)
        """,
        (timestamp, price),
    )


async def fetch_gold_price() -> float | None:
    """获取金价"""
    try:
        conn = http.client.HTTPSConnection("mbmodule-openapi.paas.cmbchina.com")
        payload = config.API_PAYLOAD
        headers = config.API_HEADERS
        conn.request("POST", config.API_URL, payload, headers)
        res = conn.getresponse()
        data = res.read()

        json_data = json.loads(data.decode("utf-8"))
        if json_data.get("success"):
            return float(json_data["data"]["FQAMBPRCZ1"]["zBuyPrc"])
        return None
    except (OSError, http.client.HTTPException, json.JSONDecodeError, KeyError, ValueError) as e:
        logger.error(f"获取金价失败: {e}")
        return None


@scheduler.scheduled_job("interval", seconds=config.price_fetch_interval)
async def record_price():
    """定时记录金价"""
    # 检查插件是否启用
    if not config.gold_plugin_enabled:
        return

    current_time = time.time()

    price = await fetch_gold_price()
    if price is not None:
        await persist_price(current_time, price)


def generate_chart(window_seconds: int | None = None) -> bytes:
    """生成金价走势图"""
    plt.style.use("bmh")

    plt.figure(figsize=(12, 6))
    plt.clf()

    effective_window = CHART_WINDOW_SECONDS if window_seconds is None else max(
        MIN_WINDOW_SECONDS, window_seconds
    )
    cutoff = time.time() - effective_window
    window_data = [(t, p) for t, p in price_history if t >= cutoff]
    if len(window_data) < 2:
        window_data = list(price_history)

    times, prices = zip(*window_data, strict=False)
    # 转换为本地时间
    times = [datetime.fromtimestamp(t).astimezone() for t in times]

    plt.plot(times, prices)
    plt.grid(True)

    # 自动调整x轴日期格式
    plt.gcf().autofmt_xdate()

    buf = io.BytesIO()
    plt.savefig(buf, format="PNG")
    buf.seek(0)
    return buf.getvalue()


@gold.handle()
async def _(bot: Bot, event: Event):
    # 获取当前时间
    current_time = time.time()

    # 获取群号
    group_id = event.group_id

    # 检查是否在冷却时间内
    if (
        cooldown_dict.get(group_id, {}).get("last_call_time", 0) + config.cooldown_time
        > current_time
    ):
        remaining_time = int(
            cooldown_dict[group_id]["last_call_time"] + config.cooldown_time - current_time
        )
        if remaining_time == 0:
            remaining_time = 1
        await gold.finish(f"冷却中，请等待 {remaining_time} 秒后再试")
        return

    price = await fetch_gold_price()
    if price is not None:
        # 更新冷却时间
        if group_id not in cooldown_dict:
            cooldown_dict[group_id] = {}
        cooldown_dict[group_id]["last_call_time"] = current_time

        await gold.finish(f"{price}")
    else:
        await gold.finish("获取金价失败")


@gold_chart.handle()
async def _(bot: Bot, event: Event, matches: tuple[str, str] = RegexGroup()):
    """处理金价走势图请求"""
    if len(price_history) < 2:
        await gold_chart.finish("数据收集中，请稍后再试")
        return

    suffix = matches[1].strip() if len(matches) > 1 else ""
    custom_window: int | None = None

    if suffix:
        parsed_window = parse_window_spec(suffix)
        if parsed_window is None:
            await gold_chart.finish("我听不懂哦")
            return
        custom_window = parsed_window

    try:
        image_data = generate_chart(custom_window)
        await gold_chart.send(MessageSegment.image(image_data))
    except Exception as e:
        await gold_chart.send(f"生成图表失败: {e!s}")


@driver.on_startup
async def _():
    await load_price_history()
WINDOW_PATTERN = re.compile(
    r"(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>分钟|分|min|m|小时|时|h|天|日|d|周|星期|w|月)",
    re.IGNORECASE,
)


def parse_window_spec(spec: str) -> int | None:
    match = WINDOW_PATTERN.search(spec)
    if not match:
        return None

    value = float(match.group("value"))
    unit = match.group("unit").lower()

    if unit in {"分钟", "分", "min", "m"}:
        base = 60
    elif unit in {"小时", "时", "h"}:
        base = 3600
    elif unit in {"天", "日", "d"}:
        base = 86400
    elif unit in {"周", "星期", "w"}:
        base = 7 * 86400
    elif unit == "月":
        base = 30 * 86400
    else:
        return None

    seconds = int(value * base)
    if seconds <= 0:
        return None
    return max(MIN_WINDOW_SECONDS, seconds)
