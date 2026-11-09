import io
from decimal import Decimal
from types import SimpleNamespace

import pytest
from PIL import Image

from apps.ai import indexing
from apps.ai.models import Conversation
from apps.catalog.models import Category, Product
from apps.orders.models import Cart


@pytest.fixture
def embedder(fake_models):
    return fake_models["embedder"]


@pytest.fixture
def shoe_catalog(db):
    """A small indexed catalog. Signals only queue work on commit, so we index explicitly."""
    shoes = Category.objects.create(name="Shoes", name_sw="Viatu")
    sneakers = Category.objects.create(name="Sneakers", name_sw="Raba", parent=shoes)
    electronics = Category.objects.create(name="Electronics", name_sw="Elektroniki")

    def make(name, category, price, stock=5, **extra):
        return Product.objects.create(name=name, category=category, price=Decimal(price), stock=stock, **extra)

    catalog = SimpleNamespace(
        shoes=shoes, sneakers=sneakers, electronics=electronics,
        red=make("Red Sneakers", sneakers, 45000, tags="viatu vyekundu, raba", sku="SNK-RED-42",
                 attributes={"color": "red", "size": "42"},
                 description="Comfortable red running sneakers.",
                 description_sw="Raba nyekundu nzuri za kukimbia."),
        blue=make("Blue Sandals", shoes, 30000, stock=3, tags="sandals bluu", sku="SND-BLU-40",
                  description="Light blue beach sandals."),
        boots=make("Old Boots", shoes, 60000, is_active=False, description="Brown leather boots."),
        heels=make("Black Heels", shoes, 55000, stock=0, tags="viatu vyeusi",
                   description="Black evening heels."),
        charger=make("Phone Charger", electronics, 15000, stock=20, tags="chaja simu", sku="CHG-USB-C",
                     description="Fast USB-C phone charger.", description_sw="Chaja ya simu ya USB-C."),
    )
    for product in (catalog.red, catalog.blue, catalog.boots, catalog.heels, catalog.charger):
        indexing.index_product(product.pk)
    return catalog


@pytest.fixture
def conversation(db):
    return Conversation.objects.create(cart=Cart.objects.create())


@pytest.fixture
def png_bytes():
    def make(color=(255, 0, 0), size=(64, 64), fmt="PNG"):
        buffer = io.BytesIO()
        Image.new("RGB", size, color).save(buffer, fmt)
        return buffer.getvalue()

    return make
