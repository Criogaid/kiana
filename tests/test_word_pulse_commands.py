"""Chinese command boundaries and validation."""

import pytest


@pytest.mark.parametrize("text,action,theme,args,days", [
    ("词频", "overview", "", (), 7),
    ("/词频列表", "list", "", (), 7),
    ("词频详情 炒股", "detail", "炒股", (), 7),
    ("词频 炒股", "query", "炒股", (), 7),
    ("词频 炒股 2周", "query", "炒股", (), 14),
    ("词频 炒股 1月", "query", "炒股", (), 30),
    ("词频添加 炒股 割肉 抄底", "add", "炒股", ("割肉", "抄底"), 7),
    ("词频移除 炒股 割肉", "remove", "炒股", ("割肉",), 7),
    ("词频删除 炒股", "delete", "炒股", (), 7),
    ("词频别名添加 炒股 割肉 止损", "alias_add", "炒股", ("割肉", "止损"), 7),
    ("词频别名删除 炒股 割肉 止损", "alias_remove", "炒股", ("割肉", "止损"), 7),
    ("词频别名移除 炒股 割肉 止损", "alias_remove", "炒股", ("割肉", "止损"), 7),
    ("词频说明 炒股 割肉 亏损 卖出", "description", "炒股", ("割肉", "亏损 卖出"), 7),
    ("词频说明 炒股 割肉", "description", "炒股", ("割肉", ""), 7),
    ("词频模式 炒股 字面", "mode", "炒股", ("字面",), 7),
    ("词频候选 炒股", "candidates", "炒股", (), 7),
])
def test_parse_commands(app, text, action, theme, args, days):
    from src.plugins.word_pulse.commands import Command, parse
    assert parse(text) == Command(action, theme, args, days)


@pytest.mark.parametrize("text", ["", "/", "词频很高", "词频添加了", "总结 7天 炒股", "普通聊天"])
def test_non_commands_are_ignored(app, text):
    from src.plugins.word_pulse.commands import parse
    assert parse(text) is None


@pytest.mark.parametrize("text", [
    "词频添加", "词频添加 炒股", "词频别名添加 炒股 割肉", "词频删除 炒股 多余",
    "词频列表 多余", "词频模式 炒股 unknown", "词频 炒股 0天", "词频 炒股 32天",
    "词频 炒股 2月", "词频 炒股 7d", "词频 " + "长" * 21,
    "词频说明 炒股 割肉 " + "长" * 51,
])
def test_invalid_known_commands_report_format_or_limit(app, text):
    from src.plugins.word_pulse.commands import InvalidCommand, parse
    assert isinstance(parse(text), InvalidCommand)
