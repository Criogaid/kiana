import asyncio
import re
from datetime import datetime, timedelta
from enum import Enum
from functools import partial
from typing import Literal

import akshare as ak
from nonebot import logger, on_regex
from nonebot.adapters.onebot.v11 import Bot, Event, GroupMessageEvent, MessageEvent, MessageSegment
from nonebot.exception import MatcherException
from nonebot.plugin import PluginMetadata

__plugin_meta__ = PluginMetadata(
    name="fund",
    description="基金查询插件",
    usage="发送代码查询信息:\n- 场外基金: 018957、002170\n- 场内ETF: 510300、159915\n- 场内LOF: 163406、501018\n- 个股(需带交易所): 000001.SZ、600000.SH",
)

# 配置常量
HISTORY_DAYS = 30  # 获取历史数据天数
DISPLAY_RECENT_DAYS = 7  # 显示最近天数
CACHE_TTL_MINUTES = 5  # 缓存时间（分钟）

# 全局缓存
_etf_cache = {"data": None, "timestamp": None}
_lof_cache = {"data": None, "timestamp": None}


class CodeType(Enum):
    """代码类型枚举"""

    OFF_MARKET_FUND = "off_market_fund"  # 场外基金
    ETF = "etf"  # 场内ETF基金
    LOF = "lof"  # 场内LOF基金
    STOCK = "stock"  # 股票
    UNKNOWN = "unknown"  # 未知类型


def identify_code_type(code: str) -> CodeType:
    """识别代码类型

    规则说明:
    - 股票必须带交易所后缀 (.SZ/.SH/.BJ)
    - 纯6位数字按前缀分类:
      * 51/58/56/55/15: 场内ETF (沪市/深市)
      * 50/16: 场内LOF (沪市/深市)
      * 00-09: 场外基金 (开放式基金)
      * 其他: 未知类型，需要权威查询

    Args:
        code: 代码字符串

    Returns:
        代码类型枚举
    """
    # 移除可能的空格
    code = code.strip().upper()

    # 带交易所后缀的格式 (如 000001.SZ, 600000.SH) -> 股票
    if re.match(r"^\d{6}\.(SZ|SH|BJ)$", code):
        return CodeType.STOCK

    # 纯6位数字
    if not re.match(r"^\d{6}$", code):
        return CodeType.UNKNOWN

    # 获取代码前两位
    prefix = code[:2]

    # ETF前缀定义 (基于中国证券市场实际编码规则)
    etf_prefixes_sh = {"51", "58", "56", "55"}  # 上交所ETF前缀
    etf_prefixes_sz = {"15"}                    # 深交所ETF前缀

    # LOF前缀定义
    lof_prefixes = {"16", "50"}  # LOF基金前缀

    # 场外基金前缀定义 (主要是开放式基金)
    offmarket_prefixes = {f"{i:02d}" for i in range(10)}  # "00"-"09"

    # ETF判断 (场内ETF)
    if prefix in etf_prefixes_sh or prefix in etf_prefixes_sz:
        return CodeType.ETF

    # LOF判断 (场内/场外双交易)
    if prefix in lof_prefixes:
        return CodeType.LOF

    # 场外基金判断 (开放式基金)
    if prefix in offmarket_prefixes:
        return CodeType.OFF_MARKET_FUND

    # 未知类型 (需要通过权威数据源查询)
    # 这里不再使用兜底策略，避免错误分类
    return CodeType.UNKNOWN


fund_query = on_regex(r"^(\d{6}|\d{6}\.(SZ|SH|BJ))$", re.IGNORECASE)


async def get_etf_spot_data_cached():
    """获取ETF实时数据（带缓存）"""
    now = datetime.now()
    cache_expired = (
        _etf_cache["data"] is None
        or _etf_cache["timestamp"] is None
        or now - _etf_cache["timestamp"] > timedelta(minutes=CACHE_TTL_MINUTES)
    )

    if cache_expired:
        logger.info("ETF缓存过期，重新获取数据")
        loop = asyncio.get_event_loop()
        _etf_cache["data"] = await loop.run_in_executor(None, ak.fund_etf_spot_em)
        _etf_cache["timestamp"] = now
        logger.info(f"ETF数据已缓存，共{len(_etf_cache['data'])}条记录")

    return _etf_cache["data"]


async def get_lof_spot_data_cached():
    """获取LOF实时数据（带缓存）"""
    now = datetime.now()
    cache_expired = (
        _lof_cache["data"] is None
        or _lof_cache["timestamp"] is None
        or now - _lof_cache["timestamp"] > timedelta(minutes=CACHE_TTL_MINUTES)
    )

    if cache_expired:
        logger.info("LOF缓存过期，重新获取数据")
        loop = asyncio.get_event_loop()
        _lof_cache["data"] = await loop.run_in_executor(None, ak.fund_lof_spot_em)
        _lof_cache["timestamp"] = now
        logger.info(f"LOF数据已缓存，共{len(_lof_cache['data'])}条记录")

    return _lof_cache["data"]


async def get_fund_data(fund_code: str) -> dict:
    """获取基金数据,包括基本信息、业绩和净值信息"""
    try:
        loop = asyncio.get_event_loop()

        # 获取基金基本信息
        basic_info_df = await loop.run_in_executor(
            None, partial(ak.fund_individual_basic_info_xq, symbol=fund_code)
        )

        if basic_info_df.empty or len(basic_info_df) == 0:
            logger.warning(f"未找到场外基金 {fund_code} 的基本信息")
            return {"success": False, "error": "未找到基金信息"}

        # 获取基金业绩数据
        achievement_df = await loop.run_in_executor(
            None, partial(ak.fund_individual_achievement_xq, symbol=fund_code)
        )

        # 获取基金净值数据
        nav_df = await loop.run_in_executor(
            None, partial(ak.fund_open_fund_info_em, symbol=fund_code, indicator="单位净值走势")
        )

        # 检查净值数据是否有效
        if nav_df.empty or len(nav_df) == 0:
            logger.warning(f"基金 {fund_code} 净值数据为空")
            return {"success": False, "error": "净值数据不可用"}

        return {
            "basic_info": basic_info_df,
            "achievement": achievement_df,
            "nav": nav_df,
            "success": True,
        }
    except Exception as e:
        logger.error(f"获取场外基金数据失败 [{fund_code}]: {e}", exc_info=True)
        return {"success": False, "error": str(e)}


async def get_market_fund_data(fund_code: str, fund_type: Literal["etf", "lof"]) -> dict:
    """获取场内基金数据（ETF/LOF通用）

    Args:
        fund_code: 基金代码
        fund_type: 基金类型（etf或lof）

    Returns:
        包含实时行情和历史数据的字典
    """
    try:
        # 根据类型获取实时数据
        if fund_type == "etf":
            spot_df = await get_etf_spot_data_cached()
            hist_func = ak.fund_etf_hist_em
        else:
            spot_df = await get_lof_spot_data_cached()
            hist_func = ak.fund_lof_hist_em

        # 查找指定基金
        fund_info = spot_df[spot_df["代码"] == fund_code]
        if fund_info.empty:
            logger.warning(f"未找到{fund_type.upper()}基金 {fund_code}")
            return {"success": False, "error": f"未找到{fund_type.upper()}基金代码"}

        # 获取历史数据
        end_date = datetime.now().strftime("%Y%m%d")
        start_date = (datetime.now() - timedelta(days=HISTORY_DAYS)).strftime("%Y%m%d")

        loop = asyncio.get_event_loop()
        hist_df = await loop.run_in_executor(
            None,
            partial(
                hist_func,
                symbol=fund_code,
                period="daily",
                start_date=start_date,
                end_date=end_date,
                adjust="",
            ),
        )

        if hist_df.empty or len(hist_df) < 2:
            logger.warning(f"{fund_type.upper()}基金 {fund_code} 历史数据不足")
            return {"success": False, "error": "历史数据不足"}

        return {"spot_info": fund_info.iloc[0], "hist_data": hist_df, "success": True}
    except Exception as e:
        logger.error(f"获取{fund_type.upper()}数据失败 [{fund_code}]: {e}", exc_info=True)
        return {"success": False, "error": str(e)}


async def get_fund_holdings(fund_code: str) -> dict:
    """获取基金十大重仓股信息"""
    try:
        current_year = datetime.now().year

        # 获取基金持仓数据
        loop = asyncio.get_event_loop()
        holdings_df = await loop.run_in_executor(
            None, partial(ak.fund_portfolio_hold_em, symbol=fund_code, date=str(current_year))
        )

        return {
            "holdings": holdings_df,
            "success": True,
        }
    except Exception as e:
        logger.error(f"获取基金持仓数据失败 [{fund_code}]: {e}", exc_info=True)
        return {"success": False, "error": str(e)}


async def get_stock_data(stock_code: str) -> dict:
    """获取个股数据

    Args:
        stock_code: 股票代码(如 000001.SZ 或 000001)

    Returns:
        包含股票历史数据的字典
    """
    try:
        # 处理股票代码格式
        if "." in stock_code:
            # 格式: 000001.SZ -> symbol=000001, market=sz
            code, exchange = stock_code.split(".")
            market = exchange.lower()
        else:
            # 根据代码前缀判断市场
            market = "sh" if stock_code.startswith(("60", "68")) else "sz"
            code = stock_code

        # 获取历史数据
        end_date = datetime.now().strftime("%Y%m%d")
        start_date = (datetime.now() - timedelta(days=HISTORY_DAYS)).strftime("%Y%m%d")

        loop = asyncio.get_event_loop()
        hist_df = await loop.run_in_executor(
            None,
            partial(
                ak.stock_zh_a_hist,
                symbol=code,
                period="daily",
                start_date=start_date,
                end_date=end_date,
                adjust="qfq",
            ),
        )

        if hist_df.empty or len(hist_df) < 2:
            logger.warning(f"股票 {stock_code} 历史数据不足")
            return {"success": False, "error": "历史数据不足"}

        return {"hist_data": hist_df, "code": code, "market": market, "success": True}
    except Exception as e:
        logger.error(f"获取股票数据失败 [{stock_code}]: {e}", exc_info=True)
        return {"success": False, "error": str(e)}


async def format_stock_info(stock_code: str, stock_data: dict) -> str:
    """格式化股票信息文本

    Args:
        stock_code: 股票代码
        stock_data: 股票数据字典

    Returns:
        格式化后的信息文本
    """
    try:
        hist_df = stock_data["hist_data"]

        if hist_df.empty or len(hist_df) == 0:
            return f"股票 {stock_code}\n暂无数据"

        # 获取最新交易日数据
        latest = hist_df.iloc[-1]
        stock_name = latest.get("股票名称", f"股票 {stock_code}")

        # 安全地获取数值数据
        try:
            latest_price = float(latest.get("收盘", 0))
            change_pct = float(latest.get("涨跌幅", 0))
            change_amount = float(latest.get("涨跌额", 0))
            high = float(latest.get("最高", 0))
            low = float(latest.get("最低", 0))
            open_price = float(latest.get("开盘", 0))
        except (ValueError, TypeError) as e:
            logger.error(f"股票 {stock_code} 数据转换失败: {e}")
            return f"股票 {stock_code}\n数据格式异常"

        volume = latest.get("成交量", "N/A")
        turnover = latest.get("成交额", "N/A")

        # 构建信息文本
        info_lines = [
            stock_name,
            f"代码: {stock_code}",
            "",
            f"最新价: {latest_price:.2f}",
        ]

        if change_pct > 0:
            info_lines.append(f"涨跌幅: +{change_pct:.2f}% (+{change_amount:.2f})")
        else:
            info_lines.append(f"涨跌幅: {change_pct:.2f}% ({change_amount:.2f})")

        info_lines.extend(
            [
                f"今开: {open_price:.2f}  最高: {high:.2f}  最低: {low:.2f}",
                f"成交量: {volume}",
                f"成交额: {turnover}",
                "",
                "最近交易日涨跌:",
            ]
        )

        # 添加最近交易日的涨跌幅
        recent_hist = hist_df.tail(DISPLAY_RECENT_DAYS).iloc[::-1]
        for _, row in recent_hist.iterrows():
            try:
                date_str = row.get("日期", "")
                daily_change = float(row.get("涨跌幅", 0))
                close_price = float(row.get("收盘", 0))

                if daily_change > 0:
                    info_lines.append(f"{date_str}: +{daily_change:.2f}% ({close_price:.2f})")
                else:
                    info_lines.append(f"{date_str}: {daily_change:.2f}% ({close_price:.2f})")
            except (ValueError, TypeError):
                continue

        return "\n".join(info_lines)

    except Exception as e:
        logger.error(f"格式化股票信息失败 [{stock_code}]: {e}", exc_info=True)
        return f"股票 {stock_code}\n数据格式化失败: {e!s}"


async def format_etf_info(fund_code: str, etf_data: dict) -> str:
    """格式化场内ETF/LOF基金信息文本

    Args:
        fund_code: 基金代码
        etf_data: ETF数据字典

    Returns:
        格式化后的信息文本
    """
    try:
        spot_info = etf_data["spot_info"]
        hist_df = etf_data["hist_data"]

        # 安全地获取数据
        fund_name = spot_info.get("名称", f"基金 {fund_code}")

        try:
            latest_price = float(spot_info.get("最新价", 0))
            change_pct = float(spot_info.get("涨跌幅", 0))
            change_amount = float(spot_info.get("涨跌额", 0))
        except (ValueError, TypeError) as e:
            logger.error(f"ETF {fund_code} 数据转换失败: {e}")
            return f"基金 {fund_code}\n数据格式异常"

        volume = spot_info.get("成交量", "N/A")
        turnover = spot_info.get("成交额", "N/A")

        # 构建信息文本
        info_lines = [
            fund_name,
            f"代码: {fund_code}",
            "",
            f"最新价: {latest_price:.3f}",
        ]

        if change_pct > 0:
            info_lines.append(f"涨跌幅: +{change_pct:.2f}% (+{change_amount:.3f})")
        else:
            info_lines.append(f"涨跌幅: {change_pct:.2f}% ({change_amount:.3f})")

        info_lines.extend(
            [
                f"成交量: {volume}",
                f"成交额: {turnover}",
                "",
                "最近交易日涨跌:",
            ]
        )

        # 添加最近交易日的涨跌幅
        recent_hist = hist_df.tail(DISPLAY_RECENT_DAYS).iloc[::-1]
        for _, row in recent_hist.iterrows():
            try:
                date_str = row.get("日期", "")
                daily_change = float(row.get("涨跌幅", 0))
                close_price = float(row.get("收盘", 0))

                if daily_change > 0:
                    info_lines.append(f"{date_str}: +{daily_change:.2f}% ({close_price:.3f})")
                else:
                    info_lines.append(f"{date_str}: {daily_change:.2f}% ({close_price:.3f})")
            except (ValueError, TypeError):
                continue

        return "\n".join(info_lines)

    except Exception as e:
        logger.error(f"格式化ETF信息失败 [{fund_code}]: {e}", exc_info=True)
        return f"基金 {fund_code}\n数据格式化失败: {e!s}"


async def format_fund_info(fund_code: str, fund_data: dict) -> str:
    """格式化基金信息文本"""
    try:
        basic_info_df = fund_data["basic_info"]
        achievement_df = fund_data["achievement"]
        nav_df = fund_data["nav"]

        # 从基本信息中获取基金名称
        fund_name_row = basic_info_df[basic_info_df["item"] == "基金名称"]
        if not fund_name_row.empty:
            fund_name = fund_name_row.iloc[0]["value"]
        else:
            fund_name = f"基金 {fund_code}"

        # 获取最近交易日的数据
        recent_nav = nav_df.tail(DISPLAY_RECENT_DAYS).iloc[::-1]

        # 构建信息文本
        info_lines = [
            fund_name,
            f"代码: {fund_code}",
            "",
            "最近交易日收益:",
        ]

        for _, row in recent_nav.iterrows():
            try:
                date_str = row.get("净值日期", "")
                daily_return = float(row.get("日增长率", 0))
                if daily_return > 0:
                    info_lines.append(f"{date_str}: +{daily_return:.2f}%")
                else:
                    info_lines.append(f"{date_str}: {daily_return:.2f}%")
            except (ValueError, TypeError):
                continue

        info_lines.extend(["", "阶段收益:"])

        # 添加阶段收益数据
        stage_periods = ["近1月", "近3月", "近6月", "近1年", "近3年", "近5年"]
        for period in stage_periods:
            try:
                period_data = achievement_df[achievement_df["周期"] == period]
                if not period_data.empty:
                    return_rate = float(period_data.iloc[0]["本产品区间收益"])
                    info_lines.append(f"{period}: {return_rate:.2f}%")
            except (KeyError, ValueError, IndexError) as e:
                # 如果某个周期的数据不存在或格式错误,跳过该周期
                logger.debug(f"跳过周期 {period} 的数据: {e}")
                continue

        return "\n".join(info_lines)

    except Exception as e:
        logger.error(f"格式化基金信息失败 [{fund_code}]: {e}", exc_info=True)
        return f"基金 {fund_code}\n数据格式化失败: {e!s}"


async def format_fund_holdings(fund_code: str, holdings_data: dict) -> str:
    """格式化基金十大重仓股信息"""
    try:
        holdings_df = holdings_data["holdings"]

        if holdings_df.empty:
            return f"基金 {fund_code}\n暂无持仓数据"

        # 获取最新季度的数据
        unique_quarters = holdings_df["季度"].unique()
        latest_quarter = sorted(unique_quarters, reverse=True)[0]
        latest_holdings = holdings_df[holdings_df["季度"] == latest_quarter].head(10)

        info_lines = [
            f"十大重仓股 ({latest_quarter})",
            "",
        ]

        for idx, (_, row) in enumerate(latest_holdings.iterrows(), 1):
            try:
                stock_code = row.get("股票代码", "")
                stock_name = row.get("股票名称", "")
                ratio = float(row.get("占净值比例", 0))
                info_lines.append(f"{idx}. {stock_name}({stock_code}) {ratio:.2f}%")
            except (ValueError, TypeError):
                continue

        return "\n".join(info_lines)

    except Exception as e:
        logger.error(f"格式化基金持仓信息失败 [{fund_code}]: {e}", exc_info=True)
        return f"基金 {fund_code}\n持仓数据格式化失败: {e!s}"


async def create_forward_nodes(
    bot: Bot,
    info_text: str,
    holdings_text: str | None = None,
) -> list[dict]:
    """创建合并转发消息节点"""
    forward_nodes = []

    # 基金基本信息节点
    text_node = {
        "type": "node",
        "data": {"name": "", "uin": bot.self_id, "content": info_text},
    }
    forward_nodes.append(text_node)

    # 十大重仓股信息节点
    if holdings_text:
        holdings_node = {
            "type": "node",
            "data": {"name": "", "uin": bot.self_id, "content": holdings_text},
        }
        forward_nodes.append(holdings_node)

    return forward_nodes


async def send_forward_message(bot: Bot, event: MessageEvent, forward_nodes: list):
    """发送合并转发消息"""
    if isinstance(event, GroupMessageEvent):
        await bot.call_api(
            "send_group_forward_msg",
            group_id=event.group_id,
            messages=forward_nodes,
        )
    else:
        await bot.call_api(
            "send_private_forward_msg",
            user_id=event.user_id,
            messages=forward_nodes,
        )


async def query_by_code_type(code: str, code_type: CodeType) -> tuple[str | None, str | None]:
    """根据代码类型查询数据并格式化

    Args:
        code: 代码字符串
        code_type: 代码类型

    Returns:
        (info_text, holdings_text) 元组
    """
    info_text = None
    holdings_text = None

    if code_type == CodeType.OFF_MARKET_FUND:
        # 场外基金
        fund_data = await get_fund_data(code)
        if not fund_data["success"]:
            return None, None

        info_text = await format_fund_info(code, fund_data)

        # 获取持仓数据
        holdings_data = await get_fund_holdings(code)
        if holdings_data["success"]:
            holdings_text = await format_fund_holdings(code, holdings_data)
        else:
            logger.warning(f"获取基金持仓数据失败: {holdings_data.get('error', '未知错误')}")

    elif code_type == CodeType.ETF:
        # 场内ETF
        etf_data = await get_market_fund_data(code, "etf")
        if not etf_data["success"]:
            return None, None
        info_text = await format_etf_info(code, etf_data)

    elif code_type == CodeType.LOF:
        # 场内LOF
        lof_data = await get_market_fund_data(code, "lof")
        if not lof_data["success"]:
            return None, None
        info_text = await format_etf_info(code, lof_data)

    elif code_type == CodeType.STOCK:
        # 个股
        stock_data = await get_stock_data(code)
        if not stock_data["success"]:
            return None, None
        info_text = await format_stock_info(code, stock_data)

    return info_text, holdings_text


@fund_query.handle()
async def handle_fund_query(bot: Bot, event: MessageEvent):
    """处理基金/股票查询请求"""
    code = str(event.message).strip()

    try:
        # 识别代码类型
        code_type = identify_code_type(code)

        if code_type == CodeType.UNKNOWN:
            logger.info(f"未识别的代码类型: {code}")
            return

        # 查询数据
        info_text, holdings_text = await query_by_code_type(code, code_type)

        # 创建并发送合并转发消息
        if info_text:
            forward_nodes = await create_forward_nodes(bot, info_text, holdings_text)
            await send_forward_message(bot, event, forward_nodes)

    except MatcherException:
        raise
    except Exception as e:
        logger.error(f"处理查询请求失败 [{code}]: {e}", exc_info=True)
        return
