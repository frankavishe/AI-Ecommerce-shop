import io

import pytest
from django.core.files.base import ContentFile
from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image

from apps.ai import indexing, search
from apps.ai.images import prepare_image
from apps.ai.models import IndexStatus, ProductImageIndex
from apps.ai.testing import tool_call
from apps.ai.tools import GUEST, ToolContext, run_tool
from apps.catalog.models import ProductImage

pytestmark = pytest.mark.django_db

RED, BLUE, GREEN, BLACK = (230, 20, 20), (20, 40, 220), (20, 200, 40), (10, 10, 10)


@pytest.fixture
def media(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    return tmp_path


def add_image(product, data, name="photo.png"):
    image = ProductImage(product=product)
    image.image.save(name, ContentFile(data), save=True)
    return image


@pytest.fixture
def photo_catalog(media, shoe_catalog, png_bytes):
    """Red Sneakers has a red photo, Blue Sandals a blue one, the out-of-stock heels a black one."""
    for product, colour in ((shoe_catalog.red, RED), (shoe_catalog.blue, BLUE), (shoe_catalog.heels, BLACK),
                            (shoe_catalog.boots, RED)):
        image = add_image(product, png_bytes(colour))
        indexing.index_product_image(image.pk)
    return shoe_catalog


# --- indexing -----------------------------------------------------------------------------------


def test_saving_a_product_image_indexes_it_on_commit(media, shoe_catalog, png_bytes,
                                                      django_capture_on_commit_callbacks):
    with django_capture_on_commit_callbacks(execute=True):
        image = add_image(shoe_catalog.red, png_bytes(RED))
    entry = ProductImageIndex.objects.get(image=image)
    assert entry.status == IndexStatus.READY
    assert entry.product_id == shoe_catalog.red.pk
    assert len(entry.image_vec) == 768
    assert entry.indexed_at is not None


def test_image_embed_failure_marks_the_entry_failed(media, shoe_catalog, png_bytes, fake_models):
    fake_models["image"].fail = True
    image = add_image(shoe_catalog.red, png_bytes(RED))
    entry = indexing.index_product_image(image.pk)
    assert entry.status == IndexStatus.FAILED
    assert "down" in entry.error


def test_unreadable_image_file_is_marked_failed(media, shoe_catalog):
    image = add_image(shoe_catalog.red, b"not an image", name="broken.png")
    assert indexing.index_product_image(image.pk).status == IndexStatus.FAILED


def test_deleting_the_image_removes_its_index(photo_catalog):
    image = photo_catalog.red.images.get()
    image.delete()
    assert not ProductImageIndex.objects.filter(image_id=image.pk).exists()


# --- downsizing ---------------------------------------------------------------------------------


def test_prepare_image_downsizes_to_1024_px(png_bytes):
    big = png_bytes(RED, size=(3000, 2000))
    out = Image.open(io.BytesIO(prepare_image(big)))
    assert max(out.size) == 1024
    assert out.format == "JPEG"
    small = Image.open(io.BytesIO(prepare_image(png_bytes(RED, size=(200, 100)))))
    assert small.size == (200, 100)


def test_models_receive_downsized_images(photo_catalog, png_bytes, fake_models, monkeypatch):
    seen = []
    for key, method in (("image", "embed_image"), ("vision", "caption_image")):
        fake = fake_models[key]
        original = getattr(fake, method)
        monkeypatch.setattr(fake, method, lambda data, original=original: seen.append(data) or original(data))
    search.by_image(png_bytes(RED, size=(2500, 2500)))
    assert len(seen) == 2
    assert all(max(Image.open(io.BytesIO(data)).size) <= 1024 for data in seen)


# --- by_image -----------------------------------------------------------------------------------


def test_photo_finds_the_matching_product_first(photo_catalog, png_bytes):
    result = search.by_image(png_bytes((240, 30, 25)))
    assert result.used_image_search is True
    assert result.products[0] == photo_catalog.red


def test_photo_results_skip_inactive_and_out_of_stock_products(photo_catalog, png_bytes):
    ids = [p.pk for p in search.by_image(png_bytes(BLACK)).products]
    assert photo_catalog.heels.pk not in ids
    assert photo_catalog.boots.pk not in [p.pk for p in search.by_image(png_bytes(RED)).products]


def test_a_product_with_several_photos_appears_once(photo_catalog, png_bytes):
    indexing.index_product_image(add_image(photo_catalog.red, png_bytes((200, 10, 10))).pk)
    ids = [p.pk for p in search.by_image(png_bytes(RED)).products]
    assert ids.count(photo_catalog.red.pk) == 1


def test_caption_and_note_are_merged_into_the_search(photo_catalog, png_bytes, fake_models):
    fake_models["vision"].caption = "phone charger usb"
    result = search.by_image(png_bytes(GREEN))  # no photo in the shop looks like this
    assert result.caption == "phone charger usb"
    assert result.products[0] == photo_catalog.charger


def test_note_is_used_with_the_caption(photo_catalog, png_bytes, fake_models):
    fake_models["vision"].caption = "something"
    assert search.by_image(png_bytes(GREEN), note="chaja ya simu").products[0] == photo_catalog.charger


def test_image_embed_failure_falls_back_to_caption_and_note(photo_catalog, png_bytes, fake_models):
    fake_models["image"].fail = True
    fake_models["vision"].caption = "blue sandals"
    result = search.by_image(png_bytes(RED))
    assert result.used_image_search is False
    assert result.products[0] == photo_catalog.blue


def test_everything_down_and_no_note_returns_nothing(photo_catalog, png_bytes, fake_models):
    fake_models["image"].fail = True
    fake_models["vision"].fail = True
    result = search.by_image(png_bytes(RED))
    assert result.products == []
    assert result.used_image_search is False


# --- the tool and the chat API ------------------------------------------------------------------


def test_search_by_image_needs_a_photo(conversation):
    ok, result, _ = run_tool(ToolContext(conversation=conversation, role=GUEST), "search_by_image", {})
    assert not ok
    assert "photo" in result["error"]


def test_search_by_image_tool_shows_products(photo_catalog, conversation, png_bytes):
    ctx = ToolContext(conversation=conversation, role=GUEST, image_bytes=png_bytes(RED))
    ok, result, _ = run_tool(ctx, "search_by_image", {"note": "size 42"})
    assert ok
    assert result["used_image_search"] is True
    assert result["products"][0]["name"] == "Red Sneakers"
    assert ctx.payload()["products"][0]["price"] == "45000.00"


def test_chat_with_a_photo_runs_image_search(api_client, photo_catalog, png_bytes, chat_model):
    chat_model.add([tool_call("search_by_image")], "Hizi ni Red Sneakers.")
    photo = SimpleUploadedFile("shot.png", png_bytes(RED, size=(1600, 1200)), content_type="image/png")
    res = api_client.post("/api/ai/chat/", {"image": photo, "message": "mnayo hii?"}, format="multipart")
    assert res.status_code == 200, res.data
    assert res.json()["products"][0]["name"] == "Red Sneakers"
    assert "search_by_image" in chat_model.requests[0]["messages"][-1]["content"]  # the hint names the tool
