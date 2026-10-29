from datetime import timedelta

import pytest

from apps.orders.models import Order, OrderEvent
from apps.payments.models import Payment

pytestmark = pytest.mark.django_db

GUEST = {
    "contact_name": "Amina Juma",
    "contact_phone": "+255712345678",
    "region": "Dar es Salaam",
    "district": "Kinondoni",
    "street": "Mtaa wa Uhuru 12",
}


@pytest.fixture
def cart_token(api_client, product):
    res = api_client.post("/api/cart/items/", {"product_id": product.id, "quantity": 2}, format="json")
    return res.data["token"]


def checkout(client, token, **overrides):
    return client.post("/api/checkout/", {**GUEST, **overrides}, format="json", HTTP_X_CART_TOKEN=token)


def test_guest_checkout_creates_order_and_payment_link(api_client, cart_token, product, region, clickpesa):
    res = checkout(api_client, cart_token, total="1.00", subtotal="1.00", delivery_fee="0")
    assert res.status_code == 201, res.data

    order = Order.objects.get()
    assert res.data["number"] == order.number and len(order.number) == 8
    assert order.status == Order.Status.AWAITING_PAYMENT
    assert (order.subtotal, order.delivery_fee, order.total) == (90000, 3000, 93000)
    assert res.data["total"] == "93000.00" and res.data["currency"] == "TZS"
    assert order.expires_at - order.placed_at == timedelta(minutes=120)

    item = order.items.get()
    assert (item.product_id, item.product_name, item.unit_price, item.quantity, item.line_total) == (
        product.id, "Red Sneakers", 45000, 2, 90000
    )
    assert [e.status for e in order.events.all()] == ["awaiting_payment"]
    assert order.events.get().source == OrderEvent.Source.CUSTOMER

    product.refresh_from_db()
    assert product.stock == 8
    assert api_client.get("/api/cart/", HTTP_X_CART_TOKEN=cart_token).data["items"] == []

    payment = Payment.objects.get()
    assert payment.reference == f"{order.number}P1" and payment.amount == 93000
    assert res.data["payment_url"] == f"https://pay.test/{order.number}P1"


def test_region_match_is_case_insensitive(api_client, cart_token, region, clickpesa):
    res = checkout(api_client, cart_token, region="dar es salaam")
    assert res.data["delivery_fee"] == "3000.00"


def test_unknown_region_uses_default_fee(api_client, cart_token, region, clickpesa, settings):
    res = checkout(api_client, cart_token, region="Mbeya")
    assert res.status_code == 201
    assert res.data["delivery_fee"] == "5000.00" and res.data["total"] == "95000.00"


def test_empty_cart_rejected(api_client, clickpesa):
    token = api_client.get("/api/cart/").data["token"]
    res = checkout(api_client, token)
    assert res.status_code == 400 and res.data["code"] == "empty_cart"
    assert not Order.objects.exists()


@pytest.mark.parametrize("phone", ["12345", "0712", "+2557123abc", ""])
def test_invalid_phone_rejected(api_client, cart_token, phone):
    res = checkout(api_client, cart_token, contact_phone=phone)
    assert res.status_code == 400 and "contact_phone" in res.data
    assert not Order.objects.exists()


def test_missing_street_rejected(api_client, cart_token):
    res = checkout(api_client, cart_token, street="")
    assert res.status_code == 400 and "street" in res.data


def test_local_phone_is_normalised(api_client, cart_token, clickpesa):
    res = checkout(api_client, cart_token, contact_phone="0712 345 678")
    assert res.status_code == 201
    assert res.data["contact_phone"] == "+255712345678"


def test_provider_down_still_creates_order(api_client, cart_token, clickpesa, product):
    clickpesa.down = True
    res = checkout(api_client, cart_token)
    assert res.status_code == 201
    assert res.data["payment_url"] is None and res.data["payment_error"]
    assert Order.objects.get().status == Order.Status.AWAITING_PAYMENT
    product.refresh_from_db()
    assert product.stock == 8


def test_unconfigured_provider_still_creates_order(api_client, cart_token):
    res = checkout(api_client, cart_token)
    assert res.status_code == 201 and res.data["payment_url"] is None


def test_inactive_product_blocks_checkout(api_client, cart_token, product, clickpesa):
    product.is_active = False
    product.save()
    res = checkout(api_client, cart_token)
    assert res.status_code == 400 and res.data["code"] == "inactive_product"
    assert "Red Sneakers" in res.data["detail"]
    assert not Order.objects.exists()


def test_stock_dropped_after_adding_blocks_checkout(api_client, cart_token, product, make_product, clickpesa):
    other = make_product(stock=5)
    api_client.post("/api/cart/items/", {"product_id": other.id}, format="json", HTTP_X_CART_TOKEN=cart_token)
    product.stock = 1
    product.save()
    res = checkout(api_client, cart_token)
    assert res.status_code == 400 and res.data["code"] == "out_of_stock" and res.data["available"] == 1
    other.refresh_from_db()
    assert other.stock == 5  # the whole order rolled back
    assert not Order.objects.exists()


def test_checkout_uses_current_price(api_client, cart_token, product, clickpesa):
    product.price = 50000
    product.save()
    res = checkout(api_client, cart_token)
    assert res.data["subtotal"] == "100000.00"


def test_delivery_regions_list(api_client, region, settings):
    from apps.orders.models import DeliveryRegion

    DeliveryRegion.objects.create(name="Arusha", fee=8000, is_active=False)
    res = api_client.get("/api/delivery-regions/")
    assert res.status_code == 200
    assert res.data["regions"] == [{"name": "Dar es Salaam", "fee": "3000.00"}]
    assert res.data["default_fee"] == "5000.00"
