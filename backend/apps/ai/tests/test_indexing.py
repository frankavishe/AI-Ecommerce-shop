from decimal import Decimal

import pytest

from apps.ai import indexing
from apps.ai.models import IndexStatus, ProductIndex
from apps.catalog.models import Category, Product

pytestmark = pytest.mark.django_db


def test_index_text_has_names_categories_keywords_and_both_descriptions(shoe_catalog):
    text = indexing.build_product_text(shoe_catalog.red)
    for expected in ["Red Sneakers", "Sneakers", "Raba", "Shoes", "Viatu", "viatu vyekundu",
                     "SNK-RED-42", "color: red", "Comfortable red", "Raba nyekundu"]:
        assert expected in text
    assert "45000" not in text  # price and stock are read live, never from the index


def test_saving_a_product_indexes_it_after_commit(django_capture_on_commit_callbacks):
    with django_capture_on_commit_callbacks(execute=True):
        product = Product.objects.create(name="Green Kanga", price=Decimal("12000"), stock=4)
    entry = ProductIndex.objects.get(product=product)
    assert entry.status == IndexStatus.READY
    assert entry.text_vec is not None
    assert entry.tsv is not None
    assert entry.indexed_at is not None


def test_editing_the_name_refreshes_the_index(shoe_catalog, django_capture_on_commit_callbacks):
    red = shoe_catalog.red
    old_hash = ProductIndex.objects.get(product=red).content_hash
    red.name = "Crimson Runners"
    with django_capture_on_commit_callbacks(execute=True):
        red.save()
    entry = ProductIndex.objects.get(product=red)
    assert entry.content_hash != old_hash
    assert "Crimson Runners" in entry.text


def test_renaming_a_parent_category_reindexes_its_products(shoe_catalog, django_capture_on_commit_callbacks):
    shoes = Category.objects.get(pk=shoe_catalog.shoes.pk)
    shoes.name_sw = "Viatu Bora"
    with django_capture_on_commit_callbacks(execute=True):
        shoes.save()
    assert "Viatu Bora" in ProductIndex.objects.get(product=shoe_catalog.red).text  # via Sneakers
    assert "Viatu Bora" in ProductIndex.objects.get(product=shoe_catalog.blue).text


def test_stock_or_price_change_does_not_call_the_embedder(shoe_catalog, embedder, django_capture_on_commit_callbacks):
    calls = embedder.calls
    old_hash = ProductIndex.objects.get(product=shoe_catalog.red).content_hash
    red = shoe_catalog.red
    red.stock, red.price = 1, Decimal("40000")
    with django_capture_on_commit_callbacks(execute=True):
        red.save()
    assert embedder.calls == calls
    assert ProductIndex.objects.get(product=red).content_hash == old_hash


def test_embedder_failure_marks_the_entry_failed(db, embedder, make_product):
    product = make_product(name="Solar Lamp")
    embedder.fail = True
    entry = indexing.index_product(product.pk)
    assert entry.status == IndexStatus.FAILED
    assert "down" in entry.error
    embedder.fail = False
    entry = indexing.index_product(product.pk)
    assert entry.status == IndexStatus.READY
    assert entry.error == ""


def test_deleting_a_product_removes_its_index(shoe_catalog):
    pk = shoe_catalog.blue.pk
    shoe_catalog.blue.delete()
    assert not ProductIndex.objects.filter(product_id=pk).exists()
    assert indexing.index_product(pk) is None
