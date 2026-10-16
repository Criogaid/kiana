"""QQ command boundary: permissions, orchestration, and replies."""

import time

from nonebot import get_driver, logger
from nonebot.adapters.onebot.v11 import GroupMessageEvent, Message, MessageEvent, MessageSegment
from nonebot.matcher import Matcher

from . import candidates, db, report
from .commands import ADMIN_ACTIONS, Command, InvalidCommand, parse
from .core.types import ThemeMode

_CHANGED = "统计将在下次后台处理时按新规则重算"


async def handle(event: MessageEvent, matcher: Matcher) -> None:
    request = parse(event.get_plaintext())
    if request is None:
        return
    if not isinstance(event, GroupMessageEvent):
        await matcher.send("仅支持群聊使用")
        return
    if isinstance(request, InvalidCommand):
        await matcher.send(request.message)
        return
    admin = str(event.user_id) in get_driver().config.superusers or event.sender.role in (
        "owner",
        "admin",
    )
    if request.action in ADMIN_ACTIONS and not admin:
        await matcher.send("仅群主、群管理员或 Bot 管理员可用")
        return
    try:
        text = await dispatch(str(event.group_id), request)
    except ValueError as error:
        text = str(error)
    except Exception:
        logger.exception("Word Pulse command failed")
        text = "操作失败，请稍后重试"
    await matcher.send(text)


async def dispatch(group_id: str, command: Command) -> str | Message:
    match command.action:
        case "overview":
            return await report.build_overview(group_id)
        case "list":
            return await report.build_list(group_id)
        case "detail":
            return await report.build_detail(group_id, command.theme)
        case "query":
            result = await report.build_report(
                group_id, command.theme, command.window_days, int(time.time())
            )
            if result.chart is not None:
                return Message(result.text) + MessageSegment.image(result.chart)
            return result.text
        case "add":
            result = await db.add_clusters(group_id, command.theme, command.args)
            return _change_text(result)
        case _:
            return await _manage(group_id, command)


def _change_text(result: db.RuleChange) -> str:
    lines = [f"已添加：{'、'.join(result.added)}" if result.added else "没有新增项"]
    if result.conflicts:
        lines.append(
            "跳过：" + "、".join(f"{name}（{reason}）" for name, reason in result.conflicts)
        )
    if any(len(name) == 1 for name in result.added):
        lines.append("单字写法容易误命中")
    if result.added or result.created:
        lines.append(_CHANGED)
    return "\n".join(lines)


async def _manage(group_id: str, command: Command) -> str:
    theme = await db.get_theme(group_id, command.theme)
    if theme is None:
        return f"本群没有主题「{command.theme}」。\n" + await report.build_list(group_id)
    match command.action:
        case "candidates":
            return await candidates.scan_candidates(theme, int(time.time()))
        case "delete":
            await db.delete_theme(theme.id)
            return f"已删除主题「{theme.name}」"
        case "remove":
            removed = await db.remove_clusters(theme.id, command.args)
            return _removed(removed)
        case "alias_add":
            return _change_text(await db.add_aliases(theme.id, command.args[0], command.args[1:]))
        case "alias_remove":
            return _removed(await db.remove_aliases(theme.id, command.args[0], command.args[1:]))
        case "description":
            changed = await db.set_description(theme.id, command.args[0], command.args[1])
        case "mode":
            mode: ThemeMode = "semantic" if command.args[0] == "语义" else "literal"
            changed = await db.set_mode(theme.id, mode)
        case _:
            raise ValueError("Unsupported management action")
    return "已更新\n" + _CHANGED if changed else "没有变化"


def _removed(names: list[str]) -> str:
    return f"已移除：{'、'.join(names)}\n{_CHANGED}" if names else "没有可移除的项"
