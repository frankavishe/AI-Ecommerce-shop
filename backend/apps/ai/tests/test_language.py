import pytest

from apps.ai.language import detect_language


@pytest.mark.parametrize("text", [
    "nataka viatu vyekundu chini ya 50000",
    "Habari, bei ya simu hii ni kiasi gani?",
    "naomba kujua kama mnasafirisha Arusha",
    "Je, ninaweza kurudisha viatu?",
])
def test_swahili(text):
    assert detect_language(text, previous="en") == "sw"


@pytest.mark.parametrize("text", [
    "Do you have red shoes under 50000?",
    "How much is delivery to Arusha?",
    "I want to return my order please",
    "show me the second one",
])
def test_english(text):
    assert detect_language(text, previous="sw") == "en"


@pytest.mark.parametrize("text", ["ok", "👍", "45000", "", "Samsung A15"])
def test_short_or_neutral_keeps_previous(text):
    assert detect_language(text, previous="en") == "en"
    assert detect_language(text, previous="sw") == "sw"


def test_default_is_swahili():
    assert detect_language("ok") == "sw"


def test_mixed_follows_majority():
    assert detect_language("nataka kununua red shoes hizi leo", previous="en") == "sw"
    assert detect_language("I want the viatu in size 42 please", previous="sw") == "en"
