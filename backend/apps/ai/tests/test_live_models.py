"""Smoke tests against the real model servers in the AI_* settings (Ollama + SigLIP in dev).

Skipped by default (pytest.ini excludes the marker). Run with:  pytest -m live_models apps/ai
"""

import json
from decimal import Decimal

import pytest
from django.conf import settings
from django.core.management import call_command

from apps.ai import agent, clients, indexing, signals
from apps.ai.management.commands.rag_eval import EVAL_DIR
from apps.ai.models import Conversation
from apps.catalog.models import Category, Product
from apps.orders.models import Cart

pytestmark = [pytest.mark.live_models, pytest.mark.django_db]


@pytest.fixture(autouse=True)
def fake_models():
    """Shadow the root autouse fixture so these tests reach the real endpoints."""
    clients.reset_fakes()
    yield None


@pytest.fixture
def eval_catalog():
    """The products from the labelled eval catalog (apps/ai/eval/catalog.json), indexed with the real embedder."""
    catalog = json.loads((EVAL_DIR / "catalog.json").read_text(encoding="utf-8"))
    with signals.paused():
        categories = {}
        for row in catalog["categories"]:
            categories[row["key"]] = Category.objects.create(
                name=row["name"], name_sw=row.get("name_sw", ""), parent=categories.get(row.get("parent")))
        products = [
            Product.objects.create(
                sku=row["sku"], name=row["name"], category=categories[row["category"]],
                price=Decimal(str(row["price"])), stock=row.get("stock", 10), tags=row.get("tags", ""),
                attributes=row.get("attributes", {}), description=row.get("description", ""),
                description_sw=row.get("description_sw", ""))
            for row in catalog["products"]
        ]
    for product in products:
        indexing.index_product(product.pk)
    return products


def test_ai_check_passes(capsys):
    call_command("ai_check")
    output = capsys.readouterr().out
    assert "FAIL" not in output
    assert f"{settings.AI_TEXT_DIM} dims" in output
    assert f"{settings.AI_IMAGE_DIM} dims" in output


def test_embed_texts_returns_1024_dims():
    vectors = clients.embed_texts(["viatu vyekundu", "red sneakers"])
    assert [len(v) for v in vectors] == [1024, 1024]


def test_swahili_product_question_calls_search_products(eval_catalog):
    conversation = Conversation.objects.create(cart=Cart.objects.create())
    reply = agent.handle_message(conversation, "nataka viatu vyekundu")
    names = [call["name"] for call in reply.message.tool_calls]
    assert "search_products" in names, f"tool calls: {names}, reply: {reply.text!r}"
    assert not reply.error and reply.text.strip()
