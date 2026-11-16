"""Smoke test against the real speech endpoint (AI_SPEECH_BASE_URL, the ai/whisper sidecar).

Skipped by default. Run with:  pytest -m live_models apps/whatsapp/tests/test_live_speech.py
It needs a short Swahili clip at apps/whatsapp/eval/voice/sample_sw.ogg (not committed by default).
"""

from pathlib import Path

import pytest

from apps.ai import clients

pytestmark = pytest.mark.live_models

SAMPLE = Path(__file__).resolve().parents[1] / "eval" / "voice" / "sample_sw.ogg"


@pytest.fixture(autouse=True)
def fake_models():
    """Shadow the root autouse fixture so this test reaches the real endpoint."""
    clients.reset_fakes()
    yield None


def test_transcribes_a_swahili_clip():
    if not SAMPLE.is_file():
        pytest.skip(f"Add a short Swahili voice note at {SAMPLE}.")
    heard = clients.transcribe(SAMPLE.read_bytes(), SAMPLE.name)
    assert heard["text"].strip()
    assert heard["duration"] > 0
