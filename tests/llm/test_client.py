import io
import json
import tempfile
import time
from pathlib import Path
from unittest.mock import MagicMock, patch
import urllib.error

import pytest

from harness.contracts import UsageLog
from harness.llm.client import GigaChatAuth, LlmClient, LlmError, load_env


class FakeResponse:
    def __init__(self, data: dict, status: int = 200) -> None:
        self._content = json.dumps(data).encode("utf-8")
        self.status = status

    def read(self) -> bytes:
        return self._content

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        pass


def test_load_env_sets_variables() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        env_file = Path(tmp) / ".env"
        env_file.write_text(
            "# Comment line\n"
            "TEST_CUSTOM_KEY_123=test_val_456\n"
            "TEST_QUOTED_KEY='quoted_value'\n",
            encoding="utf-8",
        )
        import os
        os.environ.pop("TEST_CUSTOM_KEY_123", None)
        os.environ.pop("TEST_QUOTED_KEY", None)

        load_env(env_file)
        assert os.environ.get("TEST_CUSTOM_KEY_123") == "test_val_456"
        assert os.environ.get("TEST_QUOTED_KEY") == "quoted_value"

        os.environ.pop("TEST_CUSTOM_KEY_123", None)
        os.environ.pop("TEST_QUOTED_KEY", None)


def test_client_complete_with_bearer_token() -> None:
    usage = UsageLog()
    client = LlmClient(
        model="GigaChat-3-Ultra",
        usage=usage,
        access_token="test_bearer_token_xyz",
        prefer_sdk=False,
    )

    mock_chat_data = {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": "Generated test specification content",
                },
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": 125,
            "completion_tokens": 340,
            "total_tokens": 465,
        },
        "model": "GigaChat-3-Ultra",
    }

    with patch("urllib.request.urlopen", return_value=FakeResponse(mock_chat_data)) as mock_urlopen:
        resp = client.complete(
            system="You are an expert tester.",
            user="Generate test cases.",
            purpose="spec",
        )

        assert resp.text == "Generated test specification content"
        assert resp.model == "GigaChat-3-Ultra"
        assert resp.input_tokens == 125
        assert resp.output_tokens == 340
        assert resp.duration_sec >= 0.0

        # Проверка записи в usage
        assert len(usage.calls) == 1
        call = usage.calls[0]
        assert call.model == "GigaChat-3-Ultra"
        assert call.input_tokens == 125
        assert call.output_tokens == 340
        assert call.purpose == "spec"

        # Проверка сформированного запроса
        req = mock_urlopen.call_args[0][0]
        assert req.get_full_url() == "https://api.giga.chat/v1/chat/completions"
        assert req.headers["Authorization"] == "Bearer test_bearer_token_xyz"
        body = json.loads(req.data.decode("utf-8"))
        assert body["model"] == "GigaChat-3-Ultra"
        assert body["temperature"] == 0.0
        assert len(body["messages"]) == 2


def test_client_oauth_token_exchange_and_caching() -> None:
    usage = UsageLog()
    client = LlmClient(
        model="GigaChat-3-Ultra",
        usage=usage,
        credentials="mock_base64_credentials",
        prefer_sdk=False,
    )

    mock_oauth_data = {
        "access_token": "exchanged_jwt_token_999",
        "expires_at": int((time.time() + 1800) * 1000),
    }

    mock_chat_data = {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": "Response text",
                }
            }
        ],
        "usage": {
            "prompt_tokens": 50,
            "completion_tokens": 50,
        },
        "model": "GigaChat-3-Ultra",
    }

    call_count = {"oauth": 0, "chat": 0}

    def fake_urlopen(req, *args, **kwargs):
        url = req.get_full_url()
        if "oauth" in url:
            call_count["oauth"] += 1
            assert "Basic mock_base64_credentials" in req.headers["Authorization"]
            return FakeResponse(mock_oauth_data)
        elif "chat/completions" in url:
            call_count["chat"] += 1
            assert req.headers["Authorization"] == "Bearer exchanged_jwt_token_999"
            return FakeResponse(mock_chat_data)
        raise ValueError(f"Unexpected URL: {url}")

    with patch("urllib.request.urlopen", side_effect=fake_urlopen):
        # Первый вызов: должен дернуть OAuth и Chat
        resp1 = client.complete("sys", "user1", purpose="call1")
        assert resp1.text == "Response text"
        assert call_count["oauth"] == 1
        assert call_count["chat"] == 1

        # Второй вызов: должен использовать закешированный токен без повторного OAuth
        resp2 = client.complete("sys", "user2", purpose="call2")
        assert resp2.text == "Response text"
        assert call_count["oauth"] == 1  # НЕ увеличился
        assert call_count["chat"] == 2

    assert len(usage.calls) == 2


def test_client_missing_credentials_raises() -> None:
    auth = GigaChatAuth(access_token=None, credentials=None)
    with pytest.raises(LlmError, match="GigaChat credentials not configured"):
        auth.get_token()


def test_client_embeddings() -> None:
    client = LlmClient(
        model="GigaChat-3-Ultra",
        access_token="test_bearer_token",
        prefer_sdk=False,
    )

    mock_embeddings_data = {
        "data": [
            {"embedding": [0.1, 0.2, 0.3], "index": 0},
            {"embedding": [0.4, 0.5, 0.6], "index": 1},
        ],
        "model": "Embeddings",
    }

    with patch("urllib.request.urlopen", return_value=FakeResponse(mock_embeddings_data)) as mock_urlopen:
        res = client.embed(["test 1", "test 2"])
        assert len(res) == 2
        assert res[0] == [0.1, 0.2, 0.3]
        assert res[1] == [0.4, 0.5, 0.6]

        req = mock_urlopen.call_args[0][0]
        assert req.get_full_url() == "https://api.giga.chat/v1/embeddings"


def test_client_handles_http_error() -> None:
    usage = UsageLog()
    client = LlmClient(
        model="GigaChat-3-Ultra",
        usage=usage,
        access_token="test_bearer_token",
        prefer_sdk=False,
    )

    error_fp = io.BytesIO(b'{"error": "Quota exceeded"}')
    http_err = urllib.error.HTTPError(
        url="https://api.giga.chat/v1/chat/completions",
        code=429,
        msg="Too Many Requests",
        hdrs=MagicMock(),
        fp=error_fp,
    )

    with patch("urllib.request.urlopen", side_effect=http_err):
        with pytest.raises(LlmError, match="HTTP 429"):
            client.complete("sys", "user", purpose="spec")

    # Упавший вызов записался в usage с суффиксом :error
    assert len(usage.calls) == 1
    assert usage.calls[0].purpose == "spec:error"

