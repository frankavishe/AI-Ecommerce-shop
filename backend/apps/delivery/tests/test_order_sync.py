"""Delivery steps drive the order statuses through orders.services.transition() (FR-004, R4)."""

import pytest

from apps.delivery import services
from apps.delivery.models import Delivery
from apps.orders import services as order_services
from apps.orders.models import OrderEvent

S = Delivery.Status
pytestmark = pytest.mark.django_db


def order_status(delivery):
    delivery.order.refresh_from_db()
    return delivery.order.status


def order_events(delivery):
    return list(OrderEvent.objects.filter(order=delivery.order).order_by("id").values_list("status", flat=True))


def test_assign_moves_paid_to_processing(delivery, rider, admin_user):
    services.assign(delivery, rider, admin_user)
    assert order_status(delivery) == "processing"


def test_assign_leaves_processing_alone(delivery, rider, admin_user):
    order_services.transition(delivery.order, "processing", OrderEvent.Source.ADMIN)
    services.assign(delivery, rider, admin_user)
    assert order_events(delivery).count("processing") == 1


def test_pickup_on_the_way_delivered(delivery, rider, admin_user):
    services.assign(delivery, rider, admin_user)
    services.change(delivery, S.PICKED_UP, rider, actor_type="rider")
    assert order_status(delivery) == "out_for_delivery"
    services.change(delivery, S.ON_THE_WAY, rider, actor_type="rider")
    assert order_status(delivery) == "out_for_delivery"
    services.change(delivery, S.DELIVERED, rider, actor_type="rider")
    assert order_status(delivery) == "delivered"
    assert order_events(delivery)[1:] == ["paid", "processing", "out_for_delivery", "delivered"]


def test_failed_and_retry_leave_the_order(delivery, rider, admin_user):
    services.assign(delivery, rider, admin_user)
    services.change(delivery, S.PICKED_UP, rider, actor_type="rider")
    services.change(delivery, S.FAILED, rider, actor_type="rider", note="no answer")
    assert order_status(delivery) == "out_for_delivery"
    services.retry(delivery, admin_user, rider=rider)
    assert order_status(delivery) == "out_for_delivery"
    services.change(delivery, S.DELIVERED, rider, actor_type="rider")
    assert order_status(delivery) == "delivered"
    assert order_events(delivery).count("out_for_delivery") == 1
