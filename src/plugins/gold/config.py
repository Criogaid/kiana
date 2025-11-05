from typing import Literal

from pydantic import BaseModel, Field


class Config(BaseModel):
    # 功能开关
    gold_plugin_enabled: bool = Field(default=True, description="是否启用金价查询插件")
    gold_enable_price_query: bool = Field(default=True, description="是否启用金价查询功能")
    gold_enable_chart: bool = Field(default=True, description="是否启用金价走势图功能")

    # 分群配置
    gold_group_mode: Literal["all", "whitelist", "blacklist"] = Field(
        default="all",
        description="群组控制模式: all(全部群启用) | whitelist(仅白名单群) | blacklist(黑名单外的群)",
    )
    gold_group_whitelist: list[str] = Field(
        default=[], description="白名单群组(仅在 whitelist 模式生效)"
    )
    gold_group_blacklist: list[str] = Field(
        default=[], description="黑名单群组(仅在 blacklist 模式生效)"
    )

    # 功能配置
    cooldown_time: int = 1  # 冷却时间（秒）
    price_fetch_interval: int = 600  # 金价获取间隔时间（秒）
    chart_window_hours: int = 120  # 趋势图展示的时间窗口（小时）
    price_history_limit: int = 86400  # 内存中保留的历史数据最大数量
    min_window_seconds: int = 3600  # 趋势图最小时间窗口（秒），默认为一小时
    API_URL: str = "https://mbmodule-openapi.paas.cmbchina.com/product/v1/func/market-center"
    API_HEADERS: dict = {
        "Host": "mbmodule-openapi.paas.cmbchina.com",
        "Connection": "keep-alive",
        "sec-ch-ua": '"Chromium";v="128", "Not;A=Brand";v="24", "Android WebView";v="128"',
        "Accept": "application/json, text/plain, */*",
        "sec-ch-ua-platform": "Android",
        "sec-ch-ua-mobile": "?1",
        "User-Agent": "Mozilla/5.0 (Windows NT 6.1; WOW64; rv:34.0) Gecko/20100101 Firefox/34.0",
        "Origin": "https://mbmodulecdn.cmbimg.com",
        "X-Requested-With": "cmb.pb",
        "Sec-Fetch-Site": "cross-site",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Dest": "empty",
        "Referer": "https://mbmodulecdn.cmbimg.com/",
        "Accept-Language": "zh-CN,zh;q=0.9,en-US;q=0.8,en;q=0.7",
        "Content-Type": "application/x-www-form-urlencoded",
    }
    API_PAYLOAD: str = 'params=[{"prdType":"H","prdCode":""}]'
