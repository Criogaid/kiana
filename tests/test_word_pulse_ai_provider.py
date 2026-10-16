"""词频通过真实 SDK 验证共享路由、三协议严格结构化输出与错误绑定。"""

import json

import httpx2
import pytest

from tests.ai_mock_transport import mock_ai_http


def _reply(protocol, content, failure=None):
    if protocol == "openai_chat":
        return {
            "choices": [{
                "finish_reason": "length" if failure == "truncated" else "stop",
                "message": {
                    "role": "assistant", "content": content,
                    "refusal": "拒绝" if failure == "refused" else None,
                },
            }],
        }
    if protocol == "anthropic_messages":
        return {
            "content": [{"type": "text", "text": content}],
            "stop_reason": {"truncated": "max_tokens", "refused": "refusal"}.get(
                failure, "end_turn"
            ),
        }
    return {
        "status": "incomplete" if failure == "truncated" else "completed",
        "incomplete_details": (
            {"reason": "max_output_tokens"} if failure == "truncated" else None
        ),
        "output": [{
            "type": "message", "id": "msg-1", "role": "assistant",
            "status": "completed",
            "content": (
                [{"type": "refusal", "refusal": "拒绝"}]
                if failure == "refused"
                else [{"type": "output_text", "text": content, "annotations": []}]
            ),
        }],
    }


def _install(protocol):
    from src.plugins.ai_provider.config import config

    config.ai_providers = [*config.ai_providers, {
        "id": "word", "protocol": protocol,
        "base_url": "https://word.example/v1", "api_key": "word-key",
        "models": ["word-model"], "max_tokens": 2048, "temperature_policy": "send",
    }]
    config.ai_plugin_models = {"word_pulse.classify": "word/word-model"}


def _wire_schema(protocol: str, body: dict) -> dict:
    if protocol == "openai_chat":
        contract = body["response_format"]["json_schema"]
        assert contract["strict"] is True
        return contract["schema"]
    if protocol == "openai_responses":
        contract = body["text"]["format"]
        assert contract["strict"] is True
        return contract["schema"]
    return body["output_config"]["format"]["schema"]


def _inputs():
    from src.plugins.word_pulse.core.types import ClusterRule, Msg, ThemeRule
    return [Msg(99, 100, "private-user-id", "今天茅子涨了")], [
        ThemeRule(1, "private-group", "炒股", "semantic", 1, 1, None, None,
                  (ClusterRule(10, "茅台", ("茅子",), "白酒公司"),))
    ]


@pytest.mark.parametrize("protocol", ["openai_chat", "openai_responses", "anthropic_messages"])
@pytest.mark.parametrize("mode", ["strict", "json"])
async def test_classification_uses_shared_route_and_payload(protocol, mode):
    from src.plugins.word_pulse.classifiers import AIClassifier
    _install(protocol)
    content = json.dumps({"results": [{"i": 0, "hits": [{"theme": "炒股", "clusters": ["茅台"]}]}]}, ensure_ascii=False)
    with mock_ai_http(lambda request: httpx2.Response(200, json=_reply(protocol, content))) as http:
        result = await AIClassifier(batch_size=50, output_mode=mode, timeout=10).classify(*_inputs())
    assert [(label.archive_id, label.cluster_id) for label in result.labels] == [(99, 10)]
    assert not result.unclassified
    assert len(http.requests) == 1
    body = http.bodies()[0]
    assert body["model"] == "word-model"
    assert http.requests[0].url.host == "word.example"
    if mode == "strict":
        assert _wire_schema(protocol, body)["additionalProperties"] is False
    messages = body["input"] if protocol == "openai_responses" else body["messages"]
    payload = json.loads(next(item["content"] for item in messages if item["role"] == "user"))
    assert payload["messages"] == [{"i": 0, "text": "今天茅子涨了"}]
    assert payload["themes"][0]["clusters"][0]["aliases"] == ["茅子"]
    assert "private-user-id" not in json.dumps(payload)
    assert "private-group" not in json.dumps(payload)


@pytest.mark.parametrize("protocol", ["openai_chat", "openai_responses", "anthropic_messages"])
@pytest.mark.parametrize("failure", ["truncated", "refused"])
async def test_classification_rejects_incomplete_or_refused_output(protocol, failure):
    from src.plugins.word_pulse.classifiers import AIClassifier
    from src.plugins.word_pulse.errors import WordPulseAIResponseError
    _install(protocol)
    with mock_ai_http(lambda request: httpx2.Response(200, json=_reply(protocol, '{"results": []}', failure))), pytest.raises(WordPulseAIResponseError):
        await AIClassifier(batch_size=50, output_mode="strict", timeout=10).classify(*_inputs())


async def test_missing_route_is_config_error_without_request():
    from src.plugins.ai_provider.config import config
    from src.plugins.word_pulse.classifiers import AIClassifier
    from src.plugins.word_pulse.errors import WordPulseAIConfigError
    config.ai_plugin_models = {"word_pulse.classify": "missing/model"}
    with mock_ai_http(lambda request: pytest.fail("must not send")) as http, pytest.raises(WordPulseAIConfigError):
        await AIClassifier(batch_size=50, output_mode="strict", timeout=10).classify(*_inputs())
    assert not http.requests
