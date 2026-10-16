"""Classification error mapping, invalid replies, and batch-local indices."""

import json

import httpx2
import pytest

from tests.ai_mock_transport import mock_ai_http, transport_failure
from tests.test_word_pulse_ai_provider import _inputs, _reply


async def classify(mode="strict"):
    from src.plugins.word_pulse.classifiers import AIClassifier
    return await AIClassifier(batch_size=50, output_mode=mode, timeout=10).classify(*_inputs())


@pytest.mark.parametrize("status,error", [(401, "WordPulseAIAuthError"), (403, "WordPulseAIAuthError"), (404, "WordPulseAIServiceError"), (429, "WordPulseAIServiceError"), (500, "WordPulseAIServiceError")])
async def test_http_error_mapping(app, status, error):
    from src.plugins.word_pulse import errors
    with mock_ai_http(lambda request: httpx2.Response(status, json={"error": {"message": str(status)}})), pytest.raises(getattr(errors, error)):
        await classify()


@pytest.mark.parametrize("failure,error", [(httpx2.TimeoutException("timeout"), "WordPulseAITimeoutError"), (httpx2.ConnectError("dns"), "WordPulseAIServiceError"), (httpx2.ReadError("reset"), "WordPulseAIServiceError")])
async def test_transport_error_mapping(app, failure, error):
    from src.plugins.word_pulse import errors
    with mock_ai_http(transport_failure(failure)), pytest.raises(getattr(errors, error)):
        await classify()


@pytest.mark.parametrize("mode", ["strict", "json"])
@pytest.mark.parametrize("content", ["not json", '{"wrong": []}', '{"results": [{"i": 0}]}'])
async def test_invalid_response_is_rejected(app, mode, content):
    from src.plugins.word_pulse.errors import WordPulseAIResponseError
    with mock_ai_http(lambda request: httpx2.Response(200, json=_reply("openai_chat", content))), pytest.raises(WordPulseAIResponseError):
        await classify(mode)


async def test_unknown_names_duplicate_indices_and_missing_results(app):
    from src.plugins.word_pulse.classifiers import AIClassifier
    from src.plugins.word_pulse.core.types import Msg
    _, themes = _inputs()
    msgs = [Msg(i, 100, "u", "闲聊") for i in range(1, 5)]
    payload = {"results": [
        {"i": 0, "hits": [{"theme": "炒股", "clusters": ["茅子", "unknown"]}, {"theme": "unknown", "clusters": []}]},
        {"i": 1, "hits": []}, {"i": 1, "hits": []},
        {"i": 2, "hits": [{"theme": "炒股", "clusters": []}]},
        {"i": 100, "hits": []},
    ]}
    with mock_ai_http(lambda request: httpx2.Response(200, json=_reply("openai_chat", json.dumps(payload)))):
        result = await AIClassifier(batch_size=50, output_mode="strict", timeout=10).classify(msgs, themes)
    assert {(label.archive_id, label.cluster_id) for label in result.labels} == {(1, 10), (3, 0)}
    assert sum(result.unclassified.values()) == 2


async def test_batch_indices_restart_and_input_text_is_truncated(app):
    from src.plugins.word_pulse.classifiers import AIClassifier
    from src.plugins.word_pulse.core.types import Msg
    _, themes = _inputs()
    msgs = [Msg(i, 100, "private-id", "长" * 400) for i in range(5)]
    sizes = []
    def handler(request):
        body = json.loads(request.content)
        payload = json.loads(next(item["content"] for item in body["messages"] if item["role"] == "user"))
        rows = payload["messages"]
        sizes.append(len(rows))
        assert [row["i"] for row in rows] == list(range(len(rows)))
        assert all(len(row["text"]) == 300 for row in rows)
        return httpx2.Response(200, json=_reply("openai_chat", json.dumps({"results": [{"i": row["i"], "hits": []} for row in rows]})))
    with mock_ai_http(handler):
        result = await AIClassifier(batch_size=2, output_mode="strict", timeout=10).classify(msgs, themes)
    assert sizes == [2, 2, 1]
    assert not result.labels and not result.unclassified
