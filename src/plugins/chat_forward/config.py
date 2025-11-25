from typing import Literal

from pydantic import BaseModel, Field


class Config(BaseModel):
    chat_forward_plugin_enabled: bool = Field(default=True, description="是否启用打包消息插件")

    chat_forward_group_mode: Literal["all", "whitelist", "blacklist"] = Field(
        default="all",
        description="群组控制模式: all(全部群启用) | whitelist(仅白名单群) | blacklist(黑名单外的群)",
    )
    chat_forward_group_whitelist: list[str] = Field(
        default=[], description="白名单群组(仅在 whitelist 模式生效)"
    )
    chat_forward_group_blacklist: list[str] = Field(
        default=[], description="黑名单群组(仅在 blacklist 模式生效)"
    )

    # 功能参数
    chat_forward_default_count: int = Field(default=15, description="默认打包消息条数")
    chat_forward_max_count: int = Field(default=100, description="最大允许打包消息条数")
    chat_forward_cooldown: int = Field(default=10, description="冷却时间（秒）")
