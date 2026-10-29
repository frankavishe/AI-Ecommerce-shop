import json
from decimal import Decimal

import httpx
import pytest
from django.core.cache import cache
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.catalog.models import Product
from config.celery import app as celery_app


@pytest.fixture(autouse=True)
def _isolated_runtime(settings):
    settings.CLICKPESA_CLIENT_ID = ""
    settings.CLICKPESA_API_KEY = ""
    settings.CLICKPESA_CHECKSUM_KEY = ""
    celery_app.conf.update(CELERY_TASK_ALWAYS_EAGER=True)  # namespaced key wins over task_always_eager
    cache.clear()
    yield
    cache.clear()


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


class FakeClickPesa:
    """In-memory ClickPesa API served through httpx.MockTransport."""

    def __init__(self):
        self.calls = []
        self.records = {}  # orderReference -> list of payment records
        self.down = False

    def handler(self, request):
        self.calls.append(request)
        if self.down:
            raise httpx.ConnectError("unreachable", request=request)
        path = request.url.path
        if path.endswith("/generate-token"):
            return httpx.Response(200, json={"success": True, "token": "Bearer test-token"})
        if path.endswith("/checkout-link/generate-checkout-url"):
            body = json.loads(request.content)
            return httpx.Response(
                200, json={"checkoutLink": f"https://pay.test/{body['orderReference']}"}
            )
        if "/payments/" in path:
            reference = path.rsplit("/", 1)[-1]
            if reference not in self.records:
                return httpx.Response(404, json={"message": "Not found"})
            return httpx.Response(200, json=self.records[reference])
        return httpx.Response(404)

    def pay(self, reference, amount, status="SUCCESS", currency="TZS"):
        self.records[reference] = [{
            "id": f"ID{reference}",
            "status": status,
            "paymentReference": f"PR{reference}",
            "orderReference": reference,
            "collectedAmount": str(amount),
            "collectedCurrency": currency,
            "channel": "TIGO-PESA",
            "message": "",
        }]

    def requests_to(self, suffix):
        return [r for r in self.calls if r.url.path.endswith(suffix)]


@pytest.fixture
def clickpesa(settings, monkeypatch):
    """Configures ClickPesa credentials and routes every client call to a fake API."""
    from apps.payments import clickpesa as module

    settings.CLICKPESA_CLIENT_ID = "cid"
    settings.CLICKPESA_API_KEY = "key"
    fake = FakeClickPesa()
    monkeypatch.setattr(
        module, "get_client",
        lambda: module.ClickPesaClient(transport=httpx.MockTransport(fake.handler)),
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
