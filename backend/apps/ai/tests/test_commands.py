import json
from datetime import timedelta
from io import StringIO

import pytest
from django.core.files.base import ContentFile
from django.core.management import CommandError, call_command
from django.utils import timezone

from apps.ai import indexing
from apps.ai.models import ChatMessage, Conversation, KnowledgeDocument, ProductIndex
from apps.ai.tasks import purge_old_conversations
from apps.ai.testing import tool_call
from apps.catalog.models import Product

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def media(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    return tmp_path


def run(*args):
    out = StringIO()
    call_command(*args, stdout=out)
    return out.getvalue()


def add_document(title, text):
    document = KnowledgeDocument(title=title, content_type="text/plain")
    document.file.save(f"{title}.txt", ContentFile(text.encode()), save=True)
    indexing.index_document(document.pk)
    return document


# --- reindex -------------------------------------------------------------------------------------


def test_reindex_force_re_embeds_everything(shoe_catalog, embedder):
    add_document("Returns", "You can return shoes within 7 days.")
    before = embedder.calls
    output = run("reindex", "--products", "--knowledge", "--force")
    assert embedder.calls - before == 5 + 1
    assert "products: 5" in output
    assert "knowledge: 1" in output


def test_reindex_without_force_skips_unchanged_products(shoe_catalog, embedder):
    before = embedder.calls
    run("reindex", "--products")
    assert embedder.calls == before  # content hashes match


def test_reindex_without_flags_does_everything(shoe_catalog, embedder):
    ProductIndex.objects.all().delete()
    run("reindex")
    assert ProductIndex.objects.count() == 5


# --- ai_check ------------------------------------------------------------------------------------


def test_ai_check_reports_every_endpoint(chat_model):
    chat_model.add([tool_call("ping")])
    output = run("ai_check")
    for name in ("chat", "embeddings", "vision", "image"):
        assert name in output
    assert "FAIL" not in output
    assert "1024" in output and "768" in output


def test_ai_check_fails_when_a_model_is_down(chat_model, fake_models):
    chat_model.add([tool_call("ping")])
    fake_models["image"].fail = True
    with pytest.raises(CommandError):
        run("ai_check")


def test_ai_check_flags_a_model_that_does_not_call_tools(chat_model):
    chat_model.add("pong")  # answered in text instead of calling the tool
    with pytest.raises(CommandError, match="tool"):
        run("ai_check")


# --- rag_eval ------------------------------------------------------------------------------------


@pytest.fixture
def cases_file(tmp_path, shoe_catalog):
    add_document("Returns policy", "Returns: you can return shoes within 7 days with the receipt.")
    cases = [
        {"kind": "product", "lang": "sw", "query": "viatu vyekundu", "expect": ["SNK-RED-42"]},
        {"kind": "product", "lang": "en", "query": "phone charger", "expect": ["CHG-USB-C"]},
        {"kind": "product", "lang": "en", "query": "xyzzy", "expect": ["SND-BLU-40"]},  # a miss
        {"kind": "knowledge", "lang": "sw", "query": "kurudisha viatu", "expect_document": "Returns policy"},
    ]
    path = tmp_path / "cases.json"
    path.write_text(json.dumps(cases), encoding="utf-8")
    return path


def test_rag_eval_prints_hit_rate_per_kind_and_language(cases_file):
    output = run("rag_eval", "--cases", str(cases_file))
    lines = {tuple(line.split()[:2]): line for line in output.splitlines() if line.strip()}
    assert "1/1" in lines[("product", "sw")]
    assert "1/2" in lines[("product", "en")]
    assert "1/1" in lines[("knowledge", "sw")]
    assert "MISS" in output and "xyzzy" in output


def test_rag_eval_exits_non_zero_below_the_minimum(cases_file):
    with pytest.raises(CommandError, match="product"):
        run("rag_eval", "--cases", str(cases_file), "--min-product", "0.9")
    run("rag_eval", "--cases", str(cases_file), "--min-product", "0.6", "--min-knowledge", "1.0")


def test_rag_eval_kind_filter(cases_file):
    output = run("rag_eval", "--cases", str(cases_file), "--kind", "knowledge")
    assert "knowledge" in output
    assert "product " not in output


def test_seed_refuses_without_debug(settings):
    settings.DEBUG = False
    with pytest.raises(CommandError, match="DEBUG"):
        run("rag_eval", "--seed")
    assert not Product.objects.exists()


def test_seed_loads_the_eval_catalog_and_knowledge(settings):
    settings.DEBUG = True
    output = run("rag_eval", "--seed", "--kind", "product", "--kind", "knowledge")
    assert Product.objects.count() >= 40
    assert Product.objects.values("category").distinct().count() >= 6
    assert KnowledgeDocument.objects.filter(status="ready").count() >= 3
    assert ProductIndex.objects.filter(status="ready").count() == Product.objects.count()
    assert "product" in output and "knowledge" in output
    # Seeding twice doesn't duplicate anything.
    run("rag_eval", "--seed", "--kind", "knowledge")
    assert KnowledgeDocument.objects.count() == 3


def test_eval_set_has_enough_cases():
    from apps.ai.management.commands.rag_eval import EVAL_DIR

    cases = json.loads((EVAL_DIR / "cases.json").read_text(encoding="utf-8"))
    products = [c for c in cases if c["kind"] == "product"]
    assert len(cases) >= 50
    assert sum(c["lang"] == "sw" for c in products) >= 20
    assert sum(c["lang"] == "en" for c in products) >= 20
    assert sum(c["kind"] == "knowledge" for c in cases) >= 10
    skus = {p["sku"] for p in json.loads((EVAL_DIR / "catalog.json").read_text(encoding="utf-8"))["products"]}
    for case in products:
        assert set(case["expect"]) <= skus, case


# --- purge ---------------------------------------------------------------------------------------


def test_purge_deletes_old_conversations_and_old_photos(png_bytes, media):
    now = timezone.now()
    old = Conversation.objects.create()
    ChatMessage.objects.create(conversation=old, role="user", text="old")
    recent = Conversation.objects.create()
    photo = ChatMessage(conversation=recent, role="user", text="hii?")
    photo.image.save("old.png", ContentFile(png_bytes()), save=True)
    fresh = ChatMessage(conversation=recent, role="user", text="na hii?")
    fresh.image.save("new.png", ContentFile(png_bytes()), save=True)
    old_path = photo.image.path

    Conversation.objects.filter(pk=old.pk).update(updated_at=now - timedelta(days=91))
    ChatMessage.objects.filter(pk=photo.pk).update(created_at=now - timedelta(days=31))

    result = purge_old_conversations()

    assert result == {"conversations": 1, "images": 1}
    assert not Conversation.objects.filter(pk=old.pk).exists()
    photo.refresh_from_db()
    assert photo.image_deleted is True
    assert not photo.image
    import os
    assert not os.path.exists(old_path)
    fresh.refresh_from_db()
    assert fresh.image and not fresh.image_deleted
