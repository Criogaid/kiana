"""Fund 插件配置管理模块

基于 NoneBot2 最佳实践的配置管理
"""

from typing import ClassVar

from pydantic import BaseModel, Field


class Config(BaseModel):
    """Fund 插件配置类

    遵循 NoneBot2 插件配置标准，支持环境变量和配置文件
    """

    # 插件开关
    fund_plugin_enabled: bool = Field(default=True, description="是否启用基金查询插件")

    # 数据获取配置
    fund_history_days: int = Field(default=30, ge=1, le=365, description="获取历史数据天数")
    fund_display_recent_days: int = Field(default=7, ge=1, le=30, description="显示最近天数")

    # 缓存配置
    fund_cache_ttl_minutes: int = Field(default=5, ge=1, le=60, description="缓存有效期（分钟）")
    fund_max_cache_size: int = Field(default=100, ge=10, le=1000, description="最大缓存条目数")

    # 功能开关
    fund_enable_etf: bool = Field(default=True, description="是否启用ETF查询")
    fund_enable_lof: bool = Field(default=True, description="是否启用LOF查询")
    fund_enable_stocks: bool = Field(default=True, description="是否启用股票查询")
    fund_enable_off_market: bool = Field(default=True, description="是否启用场外基金查询")

    # 数据源配置
    fund_enable_data_source_fallback: bool = Field(
        default=True, description="是否启用数据源切换（东方财富→同花顺）"
    )

    class Config:
        extra = "ignore"  # 忽略未定义的配置项
        json_encoders: ClassVar[dict] = {
            # 可以添加自定义编码器
        }
