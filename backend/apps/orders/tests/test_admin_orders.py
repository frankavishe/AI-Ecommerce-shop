from datetime import timedelta

import pytest
from django.utils import timezone

from apps.orders.models import DeliveryRegion, Order
from apps.payments.services import start_payment

pytestmark = pytest.mark.django_db


@pytest.fixture
def admin(auth_client, admin_user):
    return auth_client(admin_user)


def numbers(res):
    return [o["number"] for o in res.data["results"]]


def test_filters_by_status_paid_and_date(admin, make_order):
    old, paid, waiting = make_order(), make_order(), make_order()
    Order.objects.filter(pk=old.pk).update(placed_at=timezone.now() - timedelta(days=10))
    paid.status, paid.paid_at = Order.Status.PAID, timezone.now()
    paid.save()

    assert numbers(admin.get("/api/admin/orders/")) == [waiting.number, paid.number, old.number]
    assert numbers(admin.get("/api/admin/orders/?status=paid")) == [paid.number]
    assert numbers(admin.get("/api/admin/orders/?paid=true")) == [paid.number]
    assert numbers(admin.get("/api/admin/orders/?paid=false")) == [waiting.number, old.number]
    after = (timezone.now() - timedelta(days=1)).date().isoformat()
    assert old.number not in numbers(admin.get(f"/api/admin/orders/?placed_after={after}"))
    assert numbers(admin.get(f"/api/admin/orders/?placed_before={after}")) == [old.number]


def test_search_by_number_phone_and_name(admin, make_order):
    a = make_order(phone="+255712111111")
    b = make_order(phone="+255713222222")
    Order.objects.filter(pk=b.pk).update(contact_name="Baraka Mushi")
    assert numbers(admin.get(f"/api/admin/orders/?search={a.number.lower()}")) == [a.number]
    assert numbers(admin.get("/api/admin/orders/?search=0713222222")) == [b.number]
    assert numbers(admin.get("/api/admin/orders/?search=%2B255712111111")) == [a.number]
    assert numbers(admin.get("/api/admin/orders/?search=baraka")) == [b.number]


def test_detail_includes_payments(admin, make_order, clickpesa):
    order = make_order()
    start_payment(order)
    res = admin.get(f"/api/admin/orders/{order.number}/")
    assert res.status_code == 200
    assert [p["reference"] for p in res.data["payments"]] == [f"{order.number}P1"]
    assert res.data["items"] and res.data["events"]


def test_status_change_writes_event_with_actor(admin, admin_user, make_order):
    order = make_order()
    order.status = Order.Status.PAID
    order.save()
    res = admin.post(f"/api/admin/orders/{order.number}/status/", {"status": "processing", "note": "Packing"}, format="json")
    assert res.status_code == 200, res.data
    assert res.data["status"] == "processing"
    event = order.events.last()
    assert (event.status, event.actor, event.source, event.note) == ("processing", admin_user, "admin", "Packing")


def test_cancelling_awaiting_order_returns_stock_once(admin, make_order):
    order = make_order(stock=10, quantity=2)
    product = order.items.get().product
    product.refresh_from_db()
    assert product.stock == 8

    res = admin.post(f"/api/admin/orders/{order.number}/status/", {"status": "cancelled"}, format="json")
    assert res.status_code == 200
    product.refresh_from_db()
    assert product.stock == 10

    res = admin.post(f"/api/admin/orders/{order.number}/status/", {"status": "cancelled"}, format="json")
    assert res.status_code == 400
    product.refresh_from_db()
    assert product.stock == 10


def test_invalid_transition_rejected(admin, make_order):
    order = make_order()
    admin.post(f"/api/admin/orders/{order.number}/status/", {"status": "cancelled"}, format="json")
    res = admin.post(f"/api/admin/orders/{order.number}/status/", {"status": "paid"}, format="json")
    assert res.status_code == 400 and res.data["code"] == "invalid_transition"
    order.refresh_from_db()
    assert order.status == Order.Status.CANCELLED


def test_unknown_status_rejected(admin, make_order):
    order = make_order()
    res = admin.post(f"/api/admin/orders/{order.number}/status/", {"status": "teleported"}, format="json")
    assert res.status_code == 400 and "status" in res.data


@pytest.mark.parametrize("who", ["guest", "customer"])
def test_admin_endpoints_refused_for_non_admins(who, api_client, auth_client, customer, make_order, region):
    client = api_client if who == "guest" else auth_client(customer)
    expected = 401 if who == "guest" else 403
    number = make_order().number
    calls = [
        ("get", "/api/admin/orders/", None),
        ("get", f"/api/admin/orders/{number}/", None),
        ("post", f"/api/admin/orders/{number}/status/", {"status": "cancelled"}),
        ("get", "/api/admin/delivery-regions/", None),
        ("post", "/api/admin/delivery-regions/", {"name": "Mwanza", "fee": "7000"}),
        ("patch", f"/api/admin/delivery-regions/{region.id}/", {"fee": "1"}),
        ("delete", f"/api/admin/delivery-regions/{region.id}/", None),
    ]
    for method, url, body in calls:
        res = getattr(client, method)(url, body, format="json")
        assert res.status_code == expected, (method, url, res.status_code)
    assert Order.objects.get(number=number).status == Order.Status.AWAITING_PAYMENT


def test_region_crud(admin, region):
    res = admin.post("/api/admin/delivery-regions/", {"name": "Mwanza", "fee": "7000"}, format="json")
    assert res.status_code == 201, res.data
    assert admin.post("/api/admin/delivery-regions/", {"name": "Mbeya", "fee": "-1"}, format="json").status_code == 400
    res = admin.patch(f"/api/admin/delivery-regions/{region.id}/", {"is_active": False}, format="json")
    assert res.status_code == 200 and res.data["is_active"] is False
    names = [r["name"] for r in admin.get("/api/admin/delivery-regions/").data["results"]]
    assert names == ["Dar es Salaam", "Mwanza"]
    assert admin.delete(f"/api/admin/delivery-regions/{region.id}/").status_code == 204
    assert list(DeliveryRegion.objects.values_list("name", flat=True)) == ["Mwanza"]
