from decimal import Decimal

import pytest

from apps.ai.search import hybrid_products, rrf
from apps.catalog.models import Product

pytestmark = pytest.mark.django_db


def names(products):
    return [p.name for p in products]


def test_rrf_rewards_items_found_by_both_lists():
    assert rrf(["a", "b", "c"], ["c", "d"]) [0] == "c"
    assert rrf(["a"], ["b"]) == ["a", "b"]  # tie -> earlier list first
    assert rrf([], []) == []


def test_swahili_query_finds_red_sneakers_first(shoe_catalog):
    assert names(hybrid_products("nataka viatu vyekundu"))[0] == "Red Sneakers"


def test_english_query_crosses_to_swahili_tagged_product(shoe_catalog):
    assert names(hybrid_products("red shoes"))[0] == "Red Sneakers"


@pytest.mark.parametrize("query", ["Phone Charger", "chaja ya simu", "CHG-USB-C"])
def test_keyword_and_sku_matches(shoe_catalog, query):
    assert names(hybrid_products(query))[0] == "Phone Charger"


def test_inactive_products_are_never_returned(shoe_catalog):
    assert "Old Boots" not in names(hybrid_products("boots", in_stock_only=False))


def test_out_of_stock_only_when_asked(shoe_catalog):
    assert "Black Heels" not in names(hybrid_products("black heels"))
    assert "Black Heels" in names(hybrid_products("black heels", in_stock_only=False))


def test_price_range(shoe_catalog):
    found = names(hybrid_products("shoes", max_price=40000))
    assert "Blue Sandals" in found
    assert "Red Sneakers" not in found
    assert names(hybrid_products("shoes", min_price=40000)) == ["Red Sneakers"]


def test_category_filter_includes_subcategories(shoe_catalog):
    found = names(hybrid_products("red", category="Viatu"))  # Swahili name of the parent
    assert found[0] == "Red Sneakers"  # lives in the Sneakers subcategory
    assert "Phone Charger" not in names(hybrid_products("charger", category="shoes"))


def test_unknown_category_is_ignored(shoe_catalog):
    assert names(hybrid_products("charger", category="Garden"))[0] == "Phone Charger"


def test_price_is_live_not_indexed(shoe_catalog):
    Product.objects.filter(pk=shoe_catalog.red.pk).update(price=Decimal("39000"))
    result = hybrid_products("red sneakers")[0]
    assert result.price == Decimal("39000")


def test_nonsense_finds_nothing(shoe_catalog):
    assert hybrid_products("xyzzy qwerty") == []


def test_keyword_search_still_works_when_embedder_is_down(shoe_catalog, embedder):
    embedder.fail = True
    assert names(hybrid_products("charger"))[0] == "Phone Charger"


def test_empty_query_lists_newest_sellable(shoe_catalog):
    found = names(hybrid_products(""))
    assert "Old Boots" not in found and "Black Heels" not in found
    assert set(found) == {"Red Sneakers", "Blue Sandals", "Phone Charger"}
