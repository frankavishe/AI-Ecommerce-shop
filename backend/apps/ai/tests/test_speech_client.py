"""clients.transcribe against a mocked OpenAI-compatible /audio/transcriptions endpoint (T041)."""

import httpx
import openai
import pytest

from apps.ai import clients
from apps.ai.testing import FakeSpeech


@pytest.fixture
def endpoint(monkeypatch, settings, fake_models):
    """Routes the real OpenAI SDK to an in-memory handler; returns the list of seen requests."""
    settings.AI_SPEECH_BASE_URL = "http://whisper.test/v1"
    settings.AI_SPEECH_MODEL = "small"
    seen, reply = [], {"status": 200, "body": {"text": " habari ", "language": "swahili", "duration": 3.4}}

    def handler(request):
        seen.append(request)
        if isinstance(reply["body"], Exception):
            raise reply["body"]
        return httpx.Response(reply["status"], json=reply["body"])

    def make(base_url, timeout):
        return openai.OpenAI(base_url=base_url, api_key="none", max_retries=0,
                             http_client=httpx.Client(transport=httpx.MockTransport(handler)))

    monkeypatch.setattr(clients, "_openai", make)
    return seen, reply


def test_transcribe_posts_multipart_and_maps_the_language(endpoint):
    seen, _ = endpoint
    result = clients.transcribe(b"OggS-audio", "voice.ogg")

    assert result == {"text": "habari", "language": "sw", "duration": 3.4}
    request = seen[0]
    assert request.url.path == "/v1/audio/transcriptions"
    body = request.content
    assert b'name="model"' in body and b"small" in body
    assert b'name="response_format"' in body and b"verbose_json" in body
    assert b'filename="voice.ogg"' in body and b"OggS-audio" in body


@pytest.mark.parametrize("given,expected", [
    ("swahili", "sw"), ("sw", "sw"), ("Swahili", "sw"), ("english", "en"), ("en", "en"),
    ("french", None), (None, None),
])
def test_language_mapping(endpoint, given, expected):
    _, reply = endpoint
    reply["body"] = {"text": "x", "language": given, "duration": 1}
    assert clients.transcribe(b"a", "a.ogg")["language"] == expected


def test_http_error_is_model_unavailable(endpoint):
    _, reply = endpoint
    reply["status"], reply["body"] = 500, {"error": "boom"}
    with pytest.raises(clients.ModelUnavailable):
        clients.transcribe(b"a", "a.ogg")


def test_connection_error_is_model_unavailable(endpoint):
    _, reply = endpoint
    reply["body"] = httpx.ConnectError("refused")
    with pytest.raises(clients.ModelUnavailable):
        clients.transcribe(b"a", "a.ogg")


def test_fake_overrides_the_client(endpoint):
    seen, _ = endpoint
    fake = FakeSpeech({"text": "mna simu?", "language": "sw", "duration": 2.0})
    clients.use_fakes(speech=fake)
    assert clients.transcribe(b"a", "a.ogg") == {"text": "mna simu?", "language": "sw", "duration": 2.0}
    assert fake.calls == [(b"a", "a.ogg")] and seen == []
