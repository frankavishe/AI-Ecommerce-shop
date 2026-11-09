"""Model access through env-configured, OpenAI-compatible endpoints (research R1).

Everything else in apps.ai calls these four functions:

    chat(messages, tools, timeout) -> {"content": str | None, "tool_calls": [{"id", "name", "arguments"}]}
    embed_texts(texts) -> list[list[float]]              # AI_TEXT_DIM each
    embed_image(image_bytes) -> list[float]               # AI_IMAGE_DIM
    caption_image(image_bytes) -> str

Any transport, timeout or server error becomes ModelUnavailable. Tests swap in fakes with
use_fakes() (see apps/ai/testing.py), so no test talks to a real model by accident.
"""

import base64

import httpx
import openai
from django.conf import settings


class ModelUnavailable(Exception):
    """A model endpoint could not answer (down, timed out, or returned an error)."""


_overrides = {}


def use_fakes(**fakes):
    """Replace backends: chat=, embedder=, image=, vision=. Pass None to restore the real one."""
    for name, fake in fakes.items():
        if fake is None:
            _overrides.pop(name, None)
        else:
            _overrides[name] = fake


def reset_fakes():
    _overrides.clear()


def _openai(base_url, timeout):
    return openai.OpenAI(base_url=base_url, api_key=settings.AI_API_KEY or "none",
                         timeout=timeout, max_retries=0)


_OPENAI_ERRORS = (openai.APIConnectionError, openai.APITimeoutError, openai.APIStatusError)


def chat(messages, tools=None, timeout=None):
    if "chat" in _overrides:
        return _overrides["chat"].chat(messages, tools)
    timeout = timeout or settings.AI_CHAT_TIMEOUT
    kwargs = {"model": settings.AI_CHAT_MODEL, "messages": messages, "temperature": 0.2}
    if tools:
        kwargs.update(tools=tools, tool_choice="auto")
    try:
        response = _openai(settings.AI_CHAT_BASE_URL, timeout).chat.completions.create(**kwargs)
    except _OPENAI_ERRORS as exc:
        raise ModelUnavailable(str(exc)) from exc
    message = response.choices[0].message
    return {
        "content": message.content,
        "tool_calls": [
            {"id": call.id, "name": call.function.name, "arguments": call.function.arguments or "{}"}
            for call in (message.tool_calls or [])
        ],
    }


def embed_texts(texts):
    texts = list(texts)
    if not texts:
        return []
    if "embedder" in _overrides:
        return _overrides["embedder"].embed_texts(texts)
    client = _openai(settings.AI_EMBED_BASE_URL, 60)
    vectors = []
    try:
        for start in range(0, len(texts), 32):
            batch = texts[start:start + 32]
            response = client.embeddings.create(model=settings.AI_EMBED_MODEL, input=batch)
            vectors.extend(item.embedding for item in sorted(response.data, key=lambda d: d.index))
    except _OPENAI_ERRORS as exc:
        raise ModelUnavailable(str(exc)) from exc
    if any(len(v) != settings.AI_TEXT_DIM for v in vectors):
        raise ModelUnavailable(
            f"Embedding model returned {len(vectors[0])} dims, expected {settings.AI_TEXT_DIM}."
        )
    return vectors


def embed_image(image_bytes):
    if "image" in _overrides:
        return _overrides["image"].embed_image(image_bytes)
    headers = {"Authorization": f"Bearer {settings.AI_API_KEY}"} if settings.AI_API_KEY else {}
    try:
        response = httpx.post(
            f"{settings.AI_IMAGE_EMBED_URL.rstrip('/')}/embed/image",
            files={"file": ("image.jpg", image_bytes, "image/jpeg")}, headers=headers, timeout=60,
        )
        response.raise_for_status()
        vector = response.json()["embedding"]
    except (httpx.HTTPError, KeyError, ValueError) as exc:
        raise ModelUnavailable(str(exc)) from exc
    if len(vector) != settings.AI_IMAGE_DIM:
        raise ModelUnavailable(f"Image model returned {len(vector)} dims, expected {settings.AI_IMAGE_DIM}.")
    return vector


CAPTION_PROMPT = (
    "Describe the main product in this photo for a shop search in at most 12 English words: "
    "product type, colour, material, brand if visible. No sentences, just the words."
)


def caption_image(image_bytes):
    if "vision" in _overrides:
        return _overrides["vision"].caption_image(image_bytes)
    data_uri = "data:image/jpeg;base64," + base64.b64encode(image_bytes).decode()
    try:
        response = _openai(settings.AI_VISION_BASE_URL, settings.AI_CHAT_TIMEOUT).chat.completions.create(
            model=settings.AI_VISION_MODEL, temperature=0,
            messages=[{"role": "user", "content": [
                {"type": "text", "text": CAPTION_PROMPT},
                {"type": "image_url", "image_url": {"url": data_uri}},
            ]}],
        )
    except _OPENAI_ERRORS as exc:
        raise ModelUnavailable(str(exc)) from exc
    return (response.choices[0].message.content or "").strip()
