"""Deterministic stand-ins for the model servers (research R12). Used by tests and local demos."""

import copy
import hashlib
import io
import json
import math
import re

from PIL import Image

from .clients import ModelUnavailable
from .models import IMAGE_DIM, TEXT_DIM

# Swahili/English words mapped onto one shared token, so the fake "understands" both languages.
SYNONYMS = {
    "viatu": "shoe", "kiatu": "shoe", "shoes": "shoe", "sneaker": "shoe", "sneakers": "shoe",
    "sandal": "shoe", "sandals": "shoe", "heels": "shoe", "boots": "shoe",
    "vyekundu": "red", "nyekundu": "red", "mwekundu": "red", "chekundu": "red", "wekundu": "red",
    "bluu": "blue", "samawati": "blue",
    "vyeusi": "black", "nyeusi": "black", "cheusi": "black", "mweusi": "black",
    "simu": "phone", "phones": "phone", "chaja": "charger", "chargers": "charger",
    "kurudisha": "return", "kurejesha": "return", "rudisha": "return", "returns": "return",
    "usafirishaji": "delivery", "kusafirisha": "delivery", "shipping": "delivery",
    "bei": "price", "gharama": "price", "cost": "price",
}


def _tokens(text):
    for raw in re.findall(r"[a-z0-9]+", (text or "").lower()):
        token = SYNONYMS.get(raw, raw)
        if len(token) > 3 and token.endswith("s") and token not in SYNONYMS.values():
            token = SYNONYMS.get(token[:-1], token[:-1])
        yield token


def _bucket(token, dim):
    digest = hashlib.md5(token.encode()).digest()
    return 1 + int.from_bytes(digest[:4], "big") % (dim - 1), 1.0 if digest[4] % 2 else -1.0


def _normalise(vec):
    norm = math.sqrt(sum(x * x for x in vec)) or 1.0
    return [x / norm for x in vec]


class FakeEmbedder:
    """Hashed bag of words. Texts sharing words (after synonym mapping) end up close."""

    def __init__(self, dim=TEXT_DIM):
        self.dim = dim
        self.calls = 0
        self.fail = False

    def vector(self, text):
        vec = [0.0] * self.dim
        vec[0] = 0.05  # never a zero vector (cosine distance would be undefined)
        for token in _tokens(text):
            index, sign = _bucket(token, self.dim)
            vec[index] += sign
        return _normalise(vec)

    def embed_texts(self, texts):
        self.calls += 1
        if self.fail:
            raise ModelUnavailable("fake embedder is down")
        return [self.vector(t) for t in texts]


class FakeImageEmbedder:
    """Colour histogram: two shots of the same coloured picture are nearest neighbours."""

    def __init__(self, dim=IMAGE_DIM):
        self.dim = dim
        self.calls = 0
        self.fail = False

    def embed_image(self, image_bytes):
        self.calls += 1
        if self.fail:
            raise ModelUnavailable("fake image embedder is down")
        image = Image.open(io.BytesIO(image_bytes)).convert("RGB").resize((16, 16))
        vec = [0.0] * self.dim
        vec[0] = 0.05
        for r, g, b in image.getdata():
            vec[1 + (r // 32) * 64 + (g // 32) * 8 + (b // 32)] += 1.0
        return _normalise(vec)


class FakeVision:
    def __init__(self, caption="product photo"):
        self.caption = caption
        self.fail = False
        self.calls = 0

    def caption_image(self, image_bytes):
        self.calls += 1
        if self.fail:
            raise ModelUnavailable("fake vision model is down")
        return self.caption


def tool_call(tool_name, /, **arguments):
    return {"name": tool_name, "arguments": arguments}


class FakeChatModel:
    """Plays back scripted turns and records what it was sent.

    Each scripted item is one model response:
      "some text"                      -> a final answer
      [tool_call("search_products", query="x"), ...] -> tool calls
      an Exception instance            -> raised (e.g. ModelUnavailable("down"))
      a callable(messages, tools)      -> computed response (str or list as above)
    When the script runs out, the model answers "OK".
    """

    def __init__(self, *script):
        self.script = list(script)
        self.requests = []  # [{"messages": [...], "tools": [...]}]
        self._n = 0

    def add(self, *items):
        self.script.extend(items)

    def chat(self, messages, tools=None):
        self.requests.append({"messages": copy.deepcopy(messages), "tools": copy.deepcopy(tools or [])})
        item = self.script.pop(0) if self.script else "OK"
        if callable(item) and not isinstance(item, Exception):
            item = item(messages, tools)
        if isinstance(item, Exception):
            raise item
        if isinstance(item, str):
            return {"content": item, "tool_calls": []}
        calls = []
        for call in item:
            self._n += 1
            arguments = call["arguments"]
            calls.append({
                "id": f"call_{self._n}",
                "name": call["name"],
                "arguments": arguments if isinstance(arguments, str) else json.dumps(arguments),
            })
        return {"content": None, "tool_calls": calls}

    @property
    def last_messages(self):
        return self.requests[-1]["messages"] if self.requests else []

    def system_prompt(self, request=-1):
        return self.requests[request]["messages"][0]["content"]
