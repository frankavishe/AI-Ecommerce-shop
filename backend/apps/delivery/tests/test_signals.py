"""A paid order gets one delivery; a cancelled order closes it (research R3, FR-001, FR-004)."""

import pytest

from apps.delivery import services
from apps.delivery.models import Delivery, DeliveryEvent
from apps.orders import services as order_services
from apps.orders.models import OrderEvent

pytestmark = pytest.mark.django_db


def test_paying_an_order_creates_one_waiting_delivery(paid_order):
    delivery = Delivery.objects.get(order=paid_order)
    assert delivery.status == "waiting" and delivery.rider is None and delivery.attempt == 1


def test_a_replayed_paid_event_still_leaves_one_delivery(paid_order, run_commits):
    run_commits(OrderEvent.objects.create, order=paid_order, status="paid", source="provider")
    assert Delivery.objects.filter(order=paid_order).count() == 1


def test_unpaid_orders_get_no_delivery(make_order):
    order = make_order()
    assert not Delivery.objects.filter(order=order).exists()


@pytest.mark.parametrize("assigned", [False, True])
def test_cancelling_the_order_cancels_the_delivery(paid_order, rider, admin_user, run_commits, assigned):
    delivery = paid_order.delivery
    if assigned:
        services.assign(delivery, rider, admin_user)
        paid_order.refresh_from_db()
    run_commits(order_services.transition, paid_order, "cancelled", OrderEvent.Source.ADMIN, actor=admin_user)
    delivery.refresh_from_db()
    assert delivery.status == "cancelled"
    last = DeliveryEvent.objects.filter(delivery=delivery).last()
    assert (last.status, last.actor_type) == ("cancelled", "system")


def test_statuses_produced_by_delivery_do_not_loop(paid_order, rider, admin_user, run_commits):
    delivery = paid_order.delivery
    run_commits(services.assign, delivery, rider, admin_user)
    run_commits(services.change, delivery, "delivered", rider, actor_type="rider")
    assert list(DeliveryEvent.objects.filter(delivery=delivery).values_list("status", flat=True)) == [
        "assigned", "picked_up", "delivered"]
