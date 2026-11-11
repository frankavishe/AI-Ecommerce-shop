from types import SimpleNamespace

from apps.ai import clients


def test_chat_caps_the_completion_length(monkeypatch, settings):
    clients.reset_fakes()
    settings.AI_CHAT_MAX_TOKENS = 123
    seen = {}

    def create(**kwargs):
        seen.update(kwargs)
        message = SimpleNamespace(content="Habari", tool_calls=None)
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])

    fake = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    monkeypatch.setattr(clients, "_openai", lambda base_url, timeout: fake)

    assert clients.chat([{"role": "user", "content": "hi"}])["content"] == "Habari"
    assert seen["max_tokens"] == 123
