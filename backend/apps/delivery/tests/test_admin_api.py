"""Admin delivery API (contracts/admin-api.md, FR-005–FR-007, FR-023, FR-025)."""

from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.delivery import services
from apps.delivery.models import Delivery
from apps.orders.models import DeliveryRegion

pytestmark = pytest.mark.django_db
BASE = "/api/admin/deliveries/"


@pytest.fixture
def admin(auth_client, admin_user):
    return auth_client(admin_user)


def test_list_shape(admin, delivery):
    response = admin.get(BASE)
    assert response.status_code == 200
    item = response.json()["results"][0]
    order = delivery.order
    assert item["id"] == delivery.id and item["status"] == "waiting" and item["attempt"] == 1
    assert item["attention"] is False and item["rider"] is None
    assert item["order"] == {
        "number": order.number, "region": "Dar es Salaam", "street": "Mtaa wa Uhuru 12",
        "contact_name": "Amina Juma", "item_count": 2, "total": "93000.00",
        "paid_at": item["order"]["paid_at"], "status": "paid",
    }


def test_list_filters_and_attention_first(admin, make_order, pay, run_commits, rider, admin_user, settings):
    orders = [make_order() for _ in range(3)]
    for order in orders:
        run_commits(pay, order)
    old, failed, fresh = (Delivery.objects.get(order=o) for o in orders)
    Delivery.objects.filter(pk=old.pk).update(
        created_at=timezone.now() - timedelta(minutes=settings.DELIVERY_WAITING_ALERT_MINUTES + 1))
    services.assign(failed, rider, admin_user)
    services.change(failed, "picked_up", rider, actor_type="rider")
    services.change(failed, "failed", rider, actor_type="rider", note="no one home")
    services.assign(fresh, rider, admin_user)

    ids = [i["id"] for i in admin.get(BASE).json()["results"]]
    assert set(ids[:2]) == {old.id, failed.id} and ids[2] == fresh.id
    assert [i["id"] for i in admin.get(BASE, {"attention": 1}).json()["results"]] == ids[:2]
    assert [i["id"] for i in admin.get(BASE, {"status": "assigned"}).json()["results"]] == [fresh.id]
    both = admin.get(f"{BASE}?status=assigned&status=failed").json()["results"]
    assert {i["id"] for i in both} == {fresh.id, failed.id}
    assert {i["id"] for i in admin.get(BASE, {"rider": rider.id}).json()["results"]} == {fresh.id, failed.id}
    assert len(admin.get(BASE, {"region": "Dar es Salaam"}).json()["results"]) == 3
    assert admin.get(BASE, {"region": "Arusha"}).json()["results"] == []


def test_detail_has_events_and_notifications(admin, delivery, rider, admin_user, run_commits):
    run_commits(services.assign, delivery, rider, admin_user)
    body = admin.get(f"{BASE}{delivery.id}/").json()
    assert body["rider"] == {"id": rider.id, "name": "Juma Mrisho", "phone": "+255700000001", "vehicle": "motorbike"}
    assert body["events"][0]["status"] == "assigned" and body["events"][0]["actor_type"] == "admin"
    assert body["events"][0]["actor_name"] and body["events"][0]["rider"] == "Juma Mrisho"
    assert body["notifications"][0]["kind"] == "rider_assigned"
    assert body["notifications"][0]["outbound_status"] == "sent"
    assert body["failure_reason"] == ""


def test_candidates_region_riders_first(admin, delivery, make_rider, rider, admin_user, make_order, pay, run_commits):
    arusha = DeliveryRegion.objects.create(name="Arusha", fee=Decimal("8000"))
    elsewhere = make_rider(first_name="Baraka", regions=[arusha])
    busy = make_rider(first_name="Zawadi")
    off = make_rider(first_name="Off", available=False)
    make_rider(first_name="Gone", active=False)
    other = make_order()
    run_commits(pay, other)
    services.assign(Delivery.objects.get(order=other), busy, admin_user)

    items = admin.get(f"{BASE}{delivery.id}/candidates/").json()
    names = [i["name"].split()[0] for i in items]
    assert names[:2] == ["Juma", "Zawadi"]  # region riders first, then by open jobs
    assert "Gone" not in names and set(names) == {"Juma", "Zawadi", "Off", "Baraka"}
    by_name = {i["name"].split()[0]: i for i in items}
    assert by_name["Off"]["is_available"] is False
    assert by_name["Baraka"]["covers_region"] is False and by_name["Baraka"]["regions"] == ["Arusha"]
    assert by_name["Zawadi"]["open_jobs"] == 1
    assert names.index("Off") < names.index("Baraka") and elsewhere and off


def test_assign_reassign_unassign(admin, delivery, rider, rider2, run_commits):
    url = f"{BASE}{delivery.id}/"
    response = run_commits(admin.post, url + "assign/", {"rider": rider.id, "expected_status": "waiting"}, format="json")
    assert response.status_code == 200 and response.json()["rider"]["id"] == rider.id
    response = admin.post(url + "assign/", {"rider": rider2.id, "expected_status": "assigned",
                                            "expected_rider": rider.id}, format="json")
    assert response.status_code == 200 and response.json()["rider"]["id"] == rider2.id
    response = admin.post(url + "unassign/", {"expected_rider": rider2.id}, format="json")
    assert response.status_code == 200 and response.json()["status"] == "waiting"


def test_assign_errors(admin, delivery, rider, rider2, make_rider, admin_user):
    url = f"{BASE}{delivery.id}/assign/"
    response = admin.post(url, {"rider": make_rider(available=False).id}, format="json")
    assert response.status_code == 400 and response.json()["code"] == "rider_unavailable"
    services.assign(delivery, rider, admin_user)
    response = admin.post(url, {"rider": rider2.id, "expected_status": "waiting"}, format="json")
    assert response.status_code == 409 and response.json()["code"] == "stale"
    assert response.json()["delivery"]["rider"]["id"] == rider.id
    services.change(delivery, "picked_up", rider, actor_type="rider")
    response = admin.post(url, {"rider": rider2.id}, format="json")
    assert response.status_code == 409 and response.json()["code"] == "invalid_transition"
    assert admin.post(url, {"rider": 999999}, format="json").status_code == 400


def test_status_override(admin, delivery, rider, admin_user):
    services.assign(delivery, rider, admin_user)
    url = f"{BASE}{delivery.id}/status/"
    assert admin.post(url, {"status": "picked_up"}, format="json").json()["status"] == "picked_up"
    response = admin.post(url, {"status": "failed"}, format="json")
    assert response.status_code == 400 and response.json()["code"] == "reason_required"
    response = admin.post(url, {"status": "failed", "note": "rider phone dead", "expected_status": "picked_up"},
                          format="json")
    assert response.status_code == 200 and response.json()["failure_reason"] == "rider phone dead"
    assert response.json()["events"][-1]["actor_type"] == "admin"


def test_create_delivery_from_order(admin, make_order, paid_order):
    url = f"/api/admin/orders/{paid_order.number}/delivery/"
    assert admin.post(url).json()["code"] == "exists"
    paid_order.delivery.delete()
    response = admin.post(url)
    assert response.status_code == 201 and response.json()["status"] == "waiting"
    unpaid = make_order()
    response = admin.post(f"/api/admin/orders/{unpaid.number}/delivery/")
    assert response.status_code == 400 and response.json()["code"] == "not_deliverable"


@pytest.mark.parametrize("who", ["anonymous", "customer", "rider"])
def test_non_admins_are_refused(api_client, auth_client, customer, rider, delivery, who):
    client = {"anonymous": api_client, "customer": auth_client(customer) if who == "customer" else None,
              "rider": auth_client(rider) if who == "rider" else None}[who]
    expected = {401, 403}
    assert client.get(BASE).status_code in expected
    assert client.get(f"{BASE}{delivery.id}/").status_code in expected
    assert client.post(f"{BASE}{delivery.id}/assign/", {"rider": rider.id}, format="json").status_code in expected
    assert client.post(f"/api/admin/orders/{delivery.order.number}/delivery/").status_code in expected
