import json

import pytest

from apps.ai import agent, prompts
from apps.ai.clients import ModelUnavailable
from apps.ai.models import ChatMessage
from apps.ai.testing import tool_call
from apps.ai.tools import REGISTRY, register

pytestmark = pytest.mark.django_db


def tool_message(chat_model, request=1):
    """The last tool result the model saw on its `request`-th call."""
    return [m for m in chat_model.requests[request]["messages"] if m["role"] == "tool"][-1]["content"]


def test_search_reply_uses_database_prices(shoe_catalog, conversation, chat_model):
    chat_model.add([tool_call("search_products", query="viatu vyekundu")],
                   "Nimepata Red Sneakers kwa TZS 1,000 tu!")  # the model gets the price wrong
    reply = agent.handle_message(conversation, "nataka viatu vyekundu")

    assert reply.error == ""
    assert reply.text == "Nimepata Red Sneakers kwa TZS 1,000 tu!"
    first = reply.payload["products"][0]
    assert first["name"] == "Red Sneakers"
    assert first["price"] == "45000.00"  # the client renders this, not the model's text
    assert "45000" in tool_message(chat_model)


def test_tool_calls_are_audited(shoe_catalog, conversation, chat_model):
    chat_model.add([tool_call("search_products", query="charger")], "Here you go")
    reply = agent.handle_message(conversation, "Do you have a phone charger?")
    [call] = reply.message.tool_calls
    assert call["name"] == "search_products"
    assert call["arguments"] == {"query": "charger"}
    assert call["ok"] is True
    assert isinstance(call["ms"], int)
    assert reply.message.steps == 2
    assert reply.message.latency_ms is not None


def test_tool_results_are_wrapped_as_data(shoe_catalog, conversation, chat_model):
    chat_model.add([tool_call("search_products", query="charger")], "ok")
    agent.handle_message(conversation, "charger")
    content = tool_message(chat_model)
    assert content.startswith('<data source="tool:search_products">')
    assert content.rstrip().endswith("</data>")
    assert "untrusted" in chat_model.system_prompt()


@pytest.mark.parametrize("text, language, marker", [
    ("nataka viatu vyekundu", "sw", "Kiswahili"),
    ("Do you have red shoes?", "en", "English"),
])
def test_reply_language_follows_the_shopper(conversation, chat_model, text, language, marker):
    agent.handle_message(conversation, text)
    conversation.refresh_from_db()
    assert conversation.language == language
    assert f"Reply in {marker}" in chat_model.system_prompt()


def test_no_think_flag(conversation, chat_model, settings):
    settings.AI_CHAT_NO_THINK = True
    agent.handle_message(conversation, "habari")
    assert chat_model.system_prompt().endswith("/no_think")


def test_think_blocks_are_stripped(conversation, chat_model):
    chat_model.add("<think>The user greets me.</think>\nHabari! Nikusaidie nini?")
    reply = agent.handle_message(conversation, "habari yako")
    assert reply.text == "Habari! Nikusaidie nini?"


def test_step_limit_stops_the_loop(shoe_catalog, conversation, chat_model, settings):
    settings.AI_MAX_STEPS = 6
    chat_model.add(*[[tool_call("search_products", query=f"q{i}")] for i in range(7)])
    reply = agent.handle_message(conversation, "nataka viatu")
    assert len(chat_model.requests) == 6
    assert reply.error == "step_limit"
    assert reply.text == prompts.FALLBACK["step_limit"]["sw"]
    assert reply.message.steps == 6


def test_model_unavailable_gives_localised_fallback(conversation, chat_model):
    chat_model.add(ModelUnavailable("connection refused"))
    reply = agent.handle_message(conversation, "How much is delivery?")
    assert reply.error == "model_unavailable"
    assert reply.text == prompts.FALLBACK["model_unavailable"]["en"]
    assert ChatMessage.objects.filter(conversation=conversation, role="user").count() == 1


@pytest.fixture
def mutating_tool():
    @register("test_action", "A test action.", {}, mutates=True,
              label={"sw": "nimeweka kitu kwenye kikapu", "en": "added an item to your cart"})
    def test_action(ctx):
        return {"done": True}

    yield
    REGISTRY.pop("test_action")


def test_fallback_lists_actions_already_done(conversation, chat_model, mutating_tool):
    chat_model.add([tool_call("test_action")], ModelUnavailable("down"))
    reply = agent.handle_message(conversation, "Please add it to my cart")
    assert reply.error == "model_unavailable"
    assert "Already done: added an item to your cart" in reply.text


def test_overall_timeout(conversation, chat_model, settings, monkeypatch):
    settings.AI_CHAT_TIMEOUT = 20
    clock = [1000.0]
    monkeypatch.setattr(agent, "_now", lambda: clock[0])

    def slow_model(messages, tools):
        clock[0] += 25  # the model took longer than the whole turn may take
        return "too late"

    chat_model.add(slow_model)
    reply = agent.handle_message(conversation, "nataka simu")
    assert reply.error == "timeout"
    assert reply.text == prompts.FALLBACK["timeout"]["sw"]


def test_unknown_tool_and_extra_arguments_are_refused(shoe_catalog, conversation, chat_model):
    chat_model.add(
        [tool_call("delete_everything"), tool_call("search_products", query="shoes", price=1)],
        "Sawa",
    )
    reply = agent.handle_message(conversation, "nataka viatu")
    unknown, extra = reply.message.tool_calls
    assert unknown["ok"] is False and "no tool" in unknown["error"]
    assert extra["ok"] is False and "price" in extra["error"]
    assert reply.payload["products"] == []
    assert reply.text == "Sawa"


def test_malformed_json_arguments_are_refused(conversation, chat_model):
    chat_model.add([{"name": "search_products", "arguments": "{not json"}], "Sawa")
    reply = agent.handle_message(conversation, "nataka viatu")
    assert reply.message.tool_calls[0]["ok"] is False


def test_get_product_uses_swahili_description(shoe_catalog, conversation, chat_model):
    chat_model.add([tool_call("get_product", product_id=shoe_catalog.red.pk)], "Hizi hapa")
    agent.handle_message(conversation, "nionyeshe raba hizo tafadhali")
    result = json.loads(tool_message(chat_model).split("\n", 1)[1].rsplit("\n", 1)[0])
    assert result["description"] == "Raba nyekundu nzuri za kukimbia."
    assert result["category"] == "Raba"
    assert result["price_tzs"] == "45000"


def test_get_product_in_english(shoe_catalog, conversation, chat_model):
    chat_model.add([tool_call("get_product", product_id=shoe_catalog.red.pk)], "Here")
    agent.handle_message(conversation, "Show me the details of the red sneakers please")
    assert "Comfortable red running sneakers." in tool_message(chat_model)


def test_get_product_refuses_inactive(shoe_catalog, conversation, chat_model):
    chat_model.add([tool_call("get_product", product_id=shoe_catalog.boots.pk)], "Haipo")
    reply = agent.handle_message(conversation, "nionyeshe buti hizo")
    assert reply.message.tool_calls[0]["ok"] is False
    assert reply.payload["products"] == []


def test_history_is_sent_on_the_next_turn(shoe_catalog, conversation, chat_model):
    chat_model.add([tool_call("search_products", query="viatu")], "Nina Red Sneakers na Blue Sandals.")
    agent.handle_message(conversation, "nataka viatu")
    agent.handle_message(conversation, "nionyeshe cha pili")
    messages = chat_model.last_messages
    assert messages[1] == {"role": "user", "content": "nataka viatu"}
    assert messages[2]["role"] == "assistant"
    assert "Nina Red Sneakers na Blue Sandals." in messages[2]["content"]
    note = messages[2]["content"]  # ids let the model follow up on "the second one"
    assert "Products shown:" in note
    assert f"Red Sneakers (id {shoe_catalog.red.pk})" in note
    assert f"Blue Sandals (id {shoe_catalog.blue.pk})" in note
    assert messages[-1] == {"role": "user", "content": "nionyeshe cha pili"}
