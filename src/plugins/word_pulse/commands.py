"""Parse Chinese Word Pulse commands without framework or I/O dependencies."""

import re
from dataclasses import dataclass
from typing import Literal

from .config import DEFAULT_WINDOW_DAYS, MAX_DESCRIPTION_CHARS, MAX_NAME_CHARS, MAX_WINDOW_DAYS

type Action = Literal[
    "overview",
    "list",
    "detail",
    "query",
    "add",
    "remove",
    "delete",
    "alias_add",
    "alias_remove",
    "description",
    "mode",
    "candidates",
]


@dataclass(frozen=True, slots=True)
class Command:
    action: Action
    theme: str = ""
    args: tuple[str, ...] = ()
    window_days: int = DEFAULT_WINDOW_DAYS


@dataclass(frozen=True, slots=True)
class InvalidCommand:
    message: str


_ACTIONS: dict[str, Action] = {
    "词频别名添加": "alias_add",
    "词频别名删除": "alias_remove",
    "词频别名移除": "alias_remove",
    "词频列表": "list",
    "词频详情": "detail",
    "词频添加": "add",
    "词频移除": "remove",
    "词频删除": "delete",
    "词频说明": "description",
    "词频模式": "mode",
    "词频候选": "candidates",
}
USAGE: dict[Action, str] = {
    "overview": "词频",
    "list": "词频列表",
    "detail": "词频详情 <主题>",
    "query": "词频 <主题> [N天/周/月]",
    "add": "词频添加 <主题> <子类...>",
    "remove": "词频移除 <主题> <子类...>",
    "delete": "词频删除 <主题>",
    "alias_add": "词频别名添加 <主题> <子类> <别名...>",
    "alias_remove": "词频别名删除 <主题> <子类> <别名...>",
    "description": "词频说明 <主题> <子类> [一句话]",
    "mode": "词频模式 <主题> 语义|字面",
    "candidates": "词频候选 <主题>",
}
_EXAMPLES: dict[Action, str] = {
    "overview": "词频",
    "list": "词频列表",
    "detail": "词频详情 炒股",
    "query": "词频 炒股 7天",
    "add": "词频添加 炒股 割肉 抄底",
    "remove": "词频移除 炒股 抄底",
    "delete": "词频删除 炒股",
    "alias_add": "词频别名添加 炒股 割肉 止损",
    "alias_remove": "词频别名删除 炒股 割肉 止损",
    "description": "词频说明 炒股 割肉 亏损卖出",
    "mode": "词频模式 炒股 字面",
    "candidates": "词频候选 炒股",
}
ADMIN_ACTIONS = frozenset(
    {"add", "remove", "delete", "alias_add", "alias_remove", "description", "mode", "candidates"}
)


def _invalid(action: Action) -> InvalidCommand:
    return InvalidCommand(f"格式：{USAGE[action]}\n示例：{_EXAMPLES[action]}")


def action_of(text: str) -> Action | None:
    """Resolve the management action from the command word alone, even if arguments are invalid."""
    words = text.strip().removeprefix("/").split(maxsplit=1)
    return _ACTIONS.get(words[0]) if words else None


def parse(text: str) -> Command | InvalidCommand | None:
    text = text.strip().removeprefix("/")
    if text == "词频":
        return Command("overview")
    if not text:
        return None
    command_name, *parts = text.split()
    action = _ACTIONS.get(command_name)
    if action is not None:
        return _parse_action(action, parts)
    return _parse_query(parts) if command_name == "词频" else None


def _parse_query(parts: list[str]) -> Command | InvalidCommand:
    if not 1 <= len(parts) <= 2:
        return _invalid("query")
    days = DEFAULT_WINDOW_DAYS
    if len(parts) == 2:
        match = re.fullmatch(r"([0-9]+)(天|周|月)", parts[1])
        if match is None or len(match[1]) > 3:
            return _invalid("query")
        days = int(match[1]) * {"天": 1, "周": 7, "月": 30}[match[2]]
        if days > MAX_WINDOW_DAYS:
            return InvalidCommand(f"时间范围超过上限 {MAX_WINDOW_DAYS} 天")
        if days < 1:
            return _invalid("query")
    return _validate(Command("query", parts[0], window_days=days))


def _parse_action(action: Action, parts: list[str]) -> Command | InvalidCommand:
    minimum = {
        "list": 0,
        "detail": 1,
        "add": 2,
        "remove": 2,
        "delete": 1,
        "alias_add": 3,
        "alias_remove": 3,
        "description": 2,
        "mode": 2,
        "candidates": 1,
    }
    if len(parts) < minimum[action]:
        return _invalid(action)
    if (
        action in {"list", "detail", "delete", "mode", "candidates"}
        and len(parts) != minimum[action]
    ):
        return _invalid(action)
    if action == "list":
        return Command(action)
    args = tuple(parts[1:])
    if action == "description":
        args = (parts[1], " ".join(parts[2:]))
    if action == "mode" and args[0] not in {"语义", "字面"}:
        return _invalid(action)
    return _validate(Command(action, parts[0], args))


def _validate(command: Command) -> Command | InvalidCommand:
    names = (command.theme, *command.args)
    if command.action == "description":
        names = (command.theme, command.args[0])
        if len(command.args[1]) > MAX_DESCRIPTION_CHARS:
            return InvalidCommand(f"说明最多 {MAX_DESCRIPTION_CHARS} 字")
    if any(len(name) > MAX_NAME_CHARS for name in names):
        return InvalidCommand(f"主题、子类和别名最多 {MAX_NAME_CHARS} 字")
    return command
