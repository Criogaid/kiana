"""Group topic reports backed by background archive classification."""

from nonebot import get_driver, get_plugin_config, on_message, require
from nonebot.adapters.onebot.v11 import MessageEvent
from nonebot.plugin import PluginMetadata
from nonebot.rule import Rule

from src.plugins.group_permission import create_group_rule

from .config import Config

require("src.plugins.message_archive")
require("src.plugins.ai_provider")
require("nonebot_plugin_apscheduler")

from . import db, jobs  # noqa: E402 - declare dependencies before entry adapters
from .commands import USAGE, parse  # noqa: E402
from .handlers import handle  # noqa: E402

config = get_plugin_config(Config)
__plugin_meta__ = PluginMetadata(
    name="word_pulse",
    description="Group topic discussion counts with background semantic or literal classification",
    usage="\n".join(USAGE.values()),
    config=Config,
)
word_pulse_rule = create_group_rule(lambda: config, "word_pulse_plugin_enabled", "word_pulse_")


async def is_command(event: MessageEvent) -> bool:
    return parse(event.get_plaintext()) is not None


matcher = on_message(rule=word_pulse_rule & Rule(is_command), priority=5, block=True)
matcher.handle()(handle)


@get_driver().on_startup
async def initialize() -> None:
    db.ensure_schema()
