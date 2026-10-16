"""QQ entry permissions and read-only reporting through the new command path."""

from datetime import datetime
from unittest.mock import AsyncMock

import pytest
from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent, Message, PrivateMessageEvent
from nonebot.adapters.onebot.v11.event import Sender


def _make_group_event(text, *, role="member", message_id=1):
    message = Message(text)
    return GroupMessageEvent(time=100, self_id=987654321, post_type="message", sub_type="normal", user_id=100001, message_type="group", group_id=200001, message_id=message_id, message=message, original_message=message.copy(), raw_message=str(message), font=0, sender=Sender(user_id=100001, nickname="user", role=role))


def _make_private_event(text):
    message = Message(text)
    return PrivateMessageEvent(time=100, self_id=987654321, post_type="message", sub_type="friend", user_id=100001, message_type="private", message_id=1, message=message, original_message=message.copy(), raw_message=text, font=0, sender=Sender(user_id=100001))


@pytest.mark.parametrize("text,role,expected", [
    ("词频添加 炒股 割肉", "member", "仅群主、群管理员或 Bot 管理员可用"),
    ("词频列表", "member", "本群暂无主题"),
    ("词频添加 炒股 割肉", "admin", "已添加：割肉\n统计将在下次后台处理时按新规则重算"),
])
async def test_matcher_permissions_and_persistence(app, monkeypatch, text, role, expected):
    from src.plugins import word_pulse
    monkeypatch.setattr(word_pulse.config, "word_pulse_plugin_enabled", True)
    event = _make_group_event(text, role=role)
    async with app.test_matcher(word_pulse.matcher) as ctx:
        bot = ctx.create_bot(base=Bot, self_id="987654321")
        ctx.should_call_api("get_group_member_info", {"group_id": 200001, "user_id": 987654321, "no_cache": True}, result={"shut_up_timestamp": 0})
        ctx.receive_event(bot, event)
        ctx.should_pass_rule()
        ctx.should_call_send(event, expected, result={"message_id": 100})
    theme = await word_pulse.db.get_theme("200001", "炒股")
    assert (theme is not None) == (role == "admin")


async def test_private_message_rejected(app, monkeypatch):
    from src.plugins import word_pulse
    monkeypatch.setattr(word_pulse.config, "word_pulse_plugin_enabled", True)
    event = _make_private_event("词频 炒股")
    async with app.test_matcher(word_pulse.matcher) as ctx:
        bot = ctx.create_bot(base=Bot, self_id="987654321")
        ctx.receive_event(bot, event)
        ctx.should_pass_rule()
        ctx.should_call_send(event, "仅支持群聊使用", result={"message_id": 101})


async def test_handler_uses_plaintext_for_quoted_command(app):
    from src.plugins.word_pulse import db, handlers
    event = _make_group_event("词频添加 炒股 割肉", role="owner")
    event.raw_message = "[CQ:reply,id=99]词频添加 炒股 割肉"
    sender = AsyncMock()
    await handlers.handle(event, sender)
    assert (await db.get_theme("200001", "炒股")).clusters[0].name == "割肉"
    sender.send.assert_awaited_once()


async def test_management_conflicts_and_immediate_delete(app):
    from src.plugins.word_pulse import db, handlers
    from src.plugins.word_pulse.commands import parse
    for text in ("词频添加 炒股 割肉 抄底", "词频别名添加 炒股 割肉 止损", "词频说明 炒股 割肉 亏损卖出", "词频模式 炒股 字面"):
        await handlers.dispatch("g", parse(text))
    response = await handlers.dispatch("g", parse("词频添加 炒股 止损 清仓"))
    assert "清仓" in response and "已是「割肉」的别名" in response
    detail = await handlers.dispatch("g", parse("词频详情 炒股"))
    assert "亏损卖出" in detail and "止损" in detail and "字面" in detail
    await handlers.dispatch("g", parse("词频别名移除 炒股 割肉 止损"))
    await handlers.dispatch("g", parse("词频移除 炒股 清仓"))
    await handlers.dispatch("g", parse("词频删除 炒股"))
    assert await db.get_theme("g", "炒股") is None


async def test_full_report_uses_background_labels_and_no_classification(app, monkeypatch):
    from src.plugins.word_pulse import db, pipeline, report
    from src.plugins.word_pulse.core.timeutil import TZ
    from tests.test_word_pulse_analysis_extra import archive, setup_theme
    now = int(datetime(2026, 10, 16, 12, tzinfo=TZ).timestamp())
    await setup_theme()
    await archive("割肉和抄底", now - 1, user="u")
    await archive("割肉", now - 2, user="v")
    pipeline.config.word_pulse_plugin_enabled = True
    await pipeline.tick(now)
    forbidden = AsyncMock(side_effect=AssertionError("query must not classify"))
    monkeypatch.setattr(pipeline.AIClassifier, "classify", forbidden)
    trend = AsyncMock(side_effect=RuntimeError("service unavailable"))
    monkeypatch.setattr(report._ai, "complete", trend)
    first = await report.build_report("g", "炒股", 7, now)
    assert first.data.relevant_messages == 2 and first.data.relevant_users == 2
    assert [(c.messages, c.users) for c in first.data.clusters] == [(2, 2), (1, 1)]
    assert "100%" in first.text and "50%" in first.text
    assert "📈" not in first.text
    second = await report.build_report("g", "炒股", 7, now + 1)
    assert second == first
    trend.assert_awaited_once()
    forbidden.assert_not_awaited()
    assert (await db.get_cursor("g"))[1] == now


async def test_no_ai_and_zero_data_are_queryable(app, monkeypatch):
    from src.plugins.ai_provider.config import config
    from src.plugins.word_pulse import report
    from tests.test_word_pulse_analysis_extra import setup_theme
    await setup_theme("semantic")
    monkeypatch.setattr(config, "ai_providers", [])
    result = await report.build_report("g", "炒股", 7, 100)
    assert result.data.relevant_messages == 0
    assert "未启用语义分类" in result.text
    assert "重算中" in result.text


async def test_ordinary_chat_produces_no_reply(app, monkeypatch):
    from src.plugins import word_pulse
    monkeypatch.setattr(word_pulse.config, "word_pulse_plugin_enabled", True)
    event = _make_group_event("词频很高")
    async with app.test_matcher(word_pulse.matcher) as ctx:
        bot = ctx.create_bot(base=Bot, self_id="987654321")
        ctx.receive_event(bot, event)
        ctx.should_not_pass_rule()


async def test_quoted_command_routes_through_matcher(app, monkeypatch):
    from src.plugins import word_pulse
    from nonebot.adapters.onebot.v11 import MessageSegment
    monkeypatch.setattr(word_pulse.config, "word_pulse_plugin_enabled", True)
    event = _make_group_event("词频列表")
    event.message = MessageSegment.reply(99) + event.message
    event.original_message = event.message.copy()
    event.raw_message = str(event.message)
    async with app.test_matcher(word_pulse.matcher) as ctx:
        bot = ctx.create_bot(base=Bot, self_id="987654321")
        ctx.should_call_api("get_group_member_info", {"group_id": 200001, "user_id": 987654321, "no_cache": True}, result={"shut_up_timestamp": 0})
        ctx.receive_event(bot, event)
        ctx.should_pass_rule()
        ctx.should_call_send(event, "本群暂无主题", result={"message_id": 101})
