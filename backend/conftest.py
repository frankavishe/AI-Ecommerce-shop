import io
import json
from decimal import Decimal
from types import SimpleNamespace

import httpx
import pytest
from django.core.cache import cache
from PIL import Image
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.catalog.models import Category, Product
from config.celery import app as celery_app


@pytest.fixture(autouse=True)
def _isolated_runtime(settings):
    settings.STAKABA_API_KEY = ""
    settings.STAKABA_BASE_URL = "https://api.stakaba.test"
    settings.STAKABA_WEBHOOK_TOKEN = "hook-secret"
    settings.STAKABA_CONFIRM_VIA_API = False
    celery_app.conf.update(CELERY_TASK_ALWAYS_EAGER=True)  # namespaced key wins over task_always_eager
    cache.clear()
    yield
    cache.clear()


@pytest.fixture(autouse=True)
def fake_models():
    """No test ever reaches a real model server (Constitution VI). apps/ai/tests re-use these."""
    from apps.ai import clients
    from apps.ai.testing import FakeChatModel, FakeEmbedder, FakeImageEmbedder, FakeVision

    fakes = {"chat": FakeChatModel(), "embedder": FakeEmbedder(),
             "image": FakeImageEmbedder(), "vision": FakeVision()}
    clients.use_fakes(**fakes)
    yield fakes
    clients.reset_fakes()


@pytest.fixture
def chat_model(fake_models):
    return fake_models["chat"]


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def customer(db):
    return User.objects.create_user("amina", password="pw", phone="+255712000001")


@pytest.fixture
def admin_user(db):
    return User.objects.create_user("boss", password="pw", role=User.Role.ADMIN)


@pytest.fixture
def auth_client():
    def make(user):
        client = APIClient()
        client.force_authenticate(user)
        return client

    return make


@pytest.fixture
def make_product(db):
    counter = iter(range(1, 10_000))

    def make(stock=10, price=45000, **kwargs):
        n = next(counter)
        kwargs.setdefault("name", f"Product {n}")
        return Product.objects.create(stock=stock, price=Decimal(price), **kwargs)

    return make


@pytest.fixture
def product(make_product):
    return make_product(stock=10, price=45000, name="Red Sneakers")


@pytest.fixture
def region(db):
    from apps.orders.models import DeliveryRegion

    return DeliveryRegion.objects.create(name="Dar es Salaam", fee=Decimal("3000"))


class FakeStakaba:
    """In-memory Stakaba API served through httpx.MockTransport.

    Mobile money collections answer with `collection_status` (PENDING by default, like a live
    USSD push waiting for the PIN). `pay()` sets what GET /transactions/{ref} returns.
    """

    def __init__(self):
        self.calls = []
        self.transactions = {}  # internalReference -> transaction record
        self.down = False
        self.collection_status = "PENDING"
        self.error = None  # (status, json body) returned for create calls
        self._n = 0

    def handler(self, request):
        self.calls.append(request)
        if self.down:
            raise httpx.ConnectError("unreachable", request=request)
        path = request.url.path
        if request.method == "POST" and path.endswith(("/payments/card", "/payments/collection")):
            if self.error:
                return httpx.Response(self.error[0], json=self.error[1])
            body = json.loads(request.content)
            self._n += 1
            if path.endswith("/card"):
                ref = f"STKC{self._n}"
                return httpx.Response(201, json={
                    "checkoutUrl": f"https://pay.test/{body['metadata']['orderId']}",
                    "internalReference": ref,
                })
            ref = f"STKM{self._n}"
            return httpx.Response(201, json={"internalReference": ref, "status": self.collection_status})
        if request.method == "GET" and "/transactions/" in path:
            ref = path.rsplit("/", 1)[-1]
            if ref not in self.transactions:
                return httpx.Response(404, json={"error": "NOT_FOUND", "message": "Not found"})
            return httpx.Response(200, json=self.transactions[ref])
        return httpx.Response(404, json={"detail": "Not Found"})

    def record(self, ref, amount, status="SUCCESS", currency="TZS", order_id=None):
        return {
            "event": "transaction.success" if status == "SUCCESS" else "transaction.failed",
            "internalReference": ref,
            "status": status,
            "type": "COLLECTION",
            "grossAmount": amount,
            "stakabaFee": 125,
            "netAmount": amount - 125,
            "currency": currency,
            "mobileNumber": "255712345678",
            "network": "TigoPesa",
            "providerReference": f"MP{ref}",
            "metadata": {"orderId": order_id} if order_id else {},
        }

    def pay(self, ref, amount, **kwargs):
        self.transactions[ref] = self.record(ref, amount, **kwargs)

    def requests_to(self, suffix):
        return [r for r in self.calls if r.url.path.endswith(suffix)]

    def bodies(self, suffix):
        return [json.loads(r.content) for r in self.requests_to(suffix)]


@pytest.fixture
def stakaba(settings, monkeypatch):
    """Configures a sandbox key and routes every client call to a fake Stakaba API."""
    from apps.payments import stakaba as module

    settings.STAKABA_API_KEY = "sk_test_fake"
    fake = FakeStakaba()
    monkeypatch.setattr(
        module, "get_client",
        lambda: module.StakabaClient(transport=httpx.MockTransport(fake.handler)),
    )
    return fake


@pytest.fixture
def make_order(make_product, region):
    """Place an order through the service layer: 2 x 45,000 to Dar es Salaam (total 93,000)."""
    from apps.orders import services
    from apps.orders.models import Cart

    def make(quantity=2, price=45000, stock=10, user=None, phone="+255712345678"):
        cart = Cart.objects.create()
        services.add_item(cart, make_product(stock=stock, price=price).id, quantity)
        return services.place_order(
            cart,
            {"name": "Amina Juma", "phone": phone},
            {"region": "Dar es Salaam", "street": "Mtaa wa Uhuru 12"},
            user=user,
        )

    return make


@pytest.fixture
def shoe_catalog(db):
    """A small indexed catalog. Signals only queue work on commit, so we index explicitly."""
    from apps.ai import indexing

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
    from apps.ai.models import Conversation
    from apps.orders.models import Cart

    return Conversation.objects.create(cart=Cart.objects.create())


@pytest.fixture
def png_bytes():
    def make(color=(255, 0, 0), size=(64, 64), fmt="PNG"):
        buffer = io.BytesIO()
        Image.new("RGB", size, color).save(buffer, fmt)
        return buffer.getvalue()

    return make
