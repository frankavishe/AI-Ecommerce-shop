"""Live sends through the real Graph API to a Meta test number. Opt-in: `pytest -m sandbox apps/whatsapp`.

Needs, in the environment or the repo's .env: WHATSAPP_ACCESS_TOKEN, WHATSAPP_PHONE_NUMBER_ID and
WHATSAPP_SANDBOX_TO (the recipient's digits, added as a test recipient in Meta). Free text only
arrives when that phone messaged the business number in the last 24 hours; the follow_up template
must be approved (WHATSAPP_TEMPLATE_FOLLOW_UP, language WHATSAPP_SANDBOX_LANGUAGE, default sw).
"""

import os
from pathlib import Path

import pytest

from apps.whatsapp.graph import GraphClient

pytestmark = pytest.mark.sandbox

ENV_FILE = Path(__file__).resolve().parents[4] / ".env"


def _env(name, default=""):
    if os.environ.get(name):
        return os.environ[name]
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
            if line.startswith(f"{name}="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    return default


@pytest.fixture(autouse=True)
def graph(settings):
    """Shadow the conftest fake: these tests use the real Graph API."""
    for name in ("WHATSAPP_ACCESS_TOKEN", "WHATSAPP_PHONE_NUMBER_ID"):
        setattr(settings, name, _env(name))
    to = _env("WHATSAPP_SANDBOX_TO")
    if not (to and settings.WHATSAPP_ACCESS_TOKEN and settings.WHATSAPP_PHONE_NUMBER_ID):
        pytest.skip("Set WHATSAPP_SANDBOX_TO, WHATSAPP_ACCESS_TOKEN and WHATSAPP_PHONE_NUMBER_ID.")
    settings.WHATSAPP_TEMPLATE_FOLLOW_UP = _env("WHATSAPP_TEMPLATE_FOLLOW_UP", "follow_up")
    return GraphClient(), to


def test_send_text(graph):
    client, to = graph
    wamid = client.send({"messaging_product": "whatsapp", "recipient_type": "individual", "to": to,
                         "type": "text", "text": {"body": "Sandbox test: habari kutoka duka 👋"}})
    assert wamid.startswith("wamid.")


def test_send_follow_up_template(graph, settings):
    client, to = graph
    template = {"name": settings.WHATSAPP_TEMPLATE_FOLLOW_UP,
                "language": {"code": _env("WHATSAPP_SANDBOX_LANGUAGE", "sw")}}
    wamid = client.send({"messaging_product": "whatsapp", "recipient_type": "individual", "to": to,
                         "type": "template", "template": template})
    assert wamid.startswith("wamid.")
