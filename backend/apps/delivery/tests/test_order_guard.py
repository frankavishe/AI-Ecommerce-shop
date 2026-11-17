"""Once an order has a delivery, the admin order action can't jump its delivery statuses (R4)."""

import pytest

from apps.orders import services as order_services
from apps.orders.models import OrderEvent

pytestmark = pytest.mark.django_db


def post_status(client, order, status):
    return client.post(f"/api/admin/orders/{order.number}/status/", {"status": status}, format="json")


@pytest.mark.parametrize("status", ["out_for_delivery", "delivered"])
def test_delivery_statuses_are_refused(paid_order, admin_user, auth_client, status):
    order_services.transition(paid_order, "processing", OrderEvent.Source.ADMIN)
    response = post_status(auth_client(admin_user), paid_order, status)
    assert response.status_code == 409
    assert response.json()["code"] == "use_deliveries"


@pytest.mark.parametrize("status", ["processing", "cancelled"])
def test_processing_and_cancel_still_work(paid_order, admin_user, auth_client, status):
    assert post_status(auth_client(admin_user), paid_order, status).status_code == 200


def test_orders_without_a_delivery_behave_as_before(paid_order, admin_user, auth_client):
    paid_order.delivery.delete()
    client = auth_client(admin_user)
    assert post_status(client, paid_order, "processing").status_code == 200
    assert post_status(client, paid_order, "out_for_delivery").status_code == 200
