"""The delivery state machine: services.change() (data-model.md transitions, research R4/R9)."""

import pytest
from django.db import IntegrityError, transaction

from apps.delivery import services
from apps.delivery.models import Delivery, DeliveryEvent

S = Delivery.Status
pytestmark = pytest.mark.django_db


def events(delivery):
    return list(DeliveryEvent.objects.filter(delivery=delivery).values_list("status", flat=True))


def walk(delivery, rider, admin, steps):
    for step in steps:
        if step == "assigned":
            services.assign(delivery, rider, admin)
        else:
            services.change(delivery, step, rider, actor_type="rider", note="x")


def test_create_for_order_is_idempotent(paid_order):
    first, _ = services.create_for_order(paid_order)
    again, created_again = services.create_for_order(paid_order)
    assert first.pk == again.pk and first.status == S.WAITING and not created_again
    assert Delivery.objects.filter(order=paid_order).count() == 1


def test_full_happy_path_writes_one_event_per_step(delivery, rider, admin_user):
    walk(delivery, rider, admin_user, ["assigned", "picked_up", "on_the_way", "delivered"])
    delivery.refresh_from_db()
    assert delivery.status == S.DELIVERED
    assert delivery.assigned_at and delivery.picked_up_at and delivery.delivered_at
    assert events(delivery) == ["assigned", "picked_up", "on_the_way", "delivered"]
    first = DeliveryEvent.objects.filter(delivery=delivery).first()
    assert (first.actor_type, first.actor, first.rider, first.attempt) == ("admin", admin_user, rider, 1)
    last = DeliveryEvent.objects.filter(delivery=delivery).last()
    assert (last.actor_type, last.actor) == ("rider", rider)


def test_reassign_and_unassign(delivery, rider, rider2, admin_user):
    services.assign(delivery, rider, admin_user)
    result = services.assign(delivery, rider2, admin_user, expect={"rider": rider})
    assert result.notices == [("removed", rider), ("assigned", rider2)]
    result = services.unassign(delivery, admin_user, expect={"rider": rider2})
    assert result.notices == [("removed", rider2)]
    delivery.refresh_from_db()
    assert delivery.status == S.WAITING and delivery.rider is None
    assert events(delivery) == ["assigned", "assigned", "waiting"]
    assert "unassigned" in DeliveryEvent.objects.filter(delivery=delivery).last().note


def test_repeat_is_a_no_op(delivery, rider, admin_user):
    walk(delivery, rider, admin_user, ["assigned", "picked_up"])
    result = services.change(delivery, S.PICKED_UP, rider, actor_type="rider")
    assert result.already and result.recorded == [] and result.notices == []
    assert events(delivery) == ["assigned", "picked_up"]


def test_assigning_the_same_rider_again_is_a_repeat(delivery, rider, admin_user):
    services.assign(delivery, rider, admin_user)
    assert services.assign(delivery, rider, admin_user).already
    assert events(delivery) == ["assigned"]


def test_delivered_from_assigned_records_pickup_first(delivery, rider, admin_user):
    services.assign(delivery, rider, admin_user)
    result = services.change(delivery, S.DELIVERED, rider, actor_type="rider")
    assert result.recorded == ["picked_up", "delivered"]
    assert events(delivery) == ["assigned", "picked_up", "delivered"]


def test_on_the_way_from_assigned_records_pickup_first(delivery, rider, admin_user):
    services.assign(delivery, rider, admin_user)
    result = services.change(delivery, S.ON_THE_WAY, rider, actor_type="rider")
    assert result.recorded == ["picked_up", "on_the_way"]


@pytest.mark.parametrize("steps,target", [
    ([], "picked_up"), ([], "delivered"), ([], "failed"),
    (["assigned"], "failed"),
    (["assigned", "delivered"], "picked_up"), (["assigned", "delivered"], "cancelled"),
    (["assigned", "on_the_way"], "picked_up"), (["assigned", "on_the_way"], "assigned"),
    (["assigned", "on_the_way"], "waiting"),
])
def test_invalid_moves_are_refused(delivery, rider, admin_user, steps, target):
    walk(delivery, rider, admin_user, steps)
    current = Delivery.objects.get(pk=delivery.pk).status
    with pytest.raises(services.InvalidDeliveryTransition) as info:
        services.change(delivery, target, admin_user, actor_type="admin", rider=rider, note="x")
    assert info.value.extra["current"] == current


def test_failed_needs_a_reason(delivery, rider, admin_user):
    walk(delivery, rider, admin_user, ["assigned", "picked_up"])
    with pytest.raises(services.ReasonRequired):
        services.change(delivery, S.FAILED, rider, actor_type="rider", note="  ")
    result = services.change(delivery, S.FAILED, rider, actor_type="rider", note="Mteja hapatikani")
    assert result.notices == [("customer_failed", None)]
    delivery.refresh_from_db()
    assert delivery.failure_reason == "Mteja hapatikani" and delivery.failed_at
    assert DeliveryEvent.objects.filter(delivery=delivery).last().note == "Mteja hapatikani"


def test_expect_mismatch_is_stale(delivery, rider, rider2, admin_user):
    services.assign(delivery, rider, admin_user)
    with pytest.raises(services.StaleDelivery) as info:
        services.assign(delivery, rider2, admin_user, expect={"status": "waiting"})
    assert info.value.delivery.rider == rider
    with pytest.raises(services.StaleDelivery):
        services.unassign(delivery, admin_user, expect={"rider": rider2})
    with pytest.raises(services.StaleDelivery):
        services.change(delivery, S.PICKED_UP, rider2, actor_type="rider", expect={"rider": rider2})


def test_unavailable_inactive_or_non_rider_cannot_be_assigned(delivery, make_rider, admin_user):
    for user in (make_rider(available=False), make_rider(active=False), admin_user):
        with pytest.raises(services.RiderUnavailable):
            services.assign(delivery, user, admin_user)


def test_retry_starts_a_new_attempt(delivery, rider, rider2, admin_user):
    walk(delivery, rider, admin_user, ["assigned", "picked_up", "failed"])
    services.retry(delivery, admin_user)
    delivery.refresh_from_db()
    assert (delivery.status, delivery.attempt, delivery.rider, delivery.failure_reason) == (S.WAITING, 2, None, "")
    walk(delivery, rider2, admin_user, ["assigned", "picked_up", "failed"])
    result = services.retry(delivery, admin_user, rider=rider)
    assert result.notices == [("assigned", rider)]
    delivery.refresh_from_db()
    assert (delivery.status, delivery.attempt, delivery.rider) == (S.ASSIGNED, 3, rider)
    assert DeliveryEvent.objects.filter(delivery=delivery, attempt=1).count() == 3
    with pytest.raises(services.InvalidDeliveryTransition):
        services.retry(delivery, admin_user)


def test_cancel_for_order_closes_an_open_delivery(delivery, rider, admin_user):
    services.assign(delivery, rider, admin_user)
    result = services.cancel_for_order(delivery.order)
    assert result.notices == [("cancelled", rider)]
    delivery.refresh_from_db()
    assert delivery.status == S.CANCELLED
    assert services.cancel_for_order(delivery.order) is None  # already closed: nothing to do


def test_cancel_waiting_delivery_tells_nobody(delivery):
    assert services.cancel_for_order(delivery.order).notices == []


def test_active_status_needs_a_rider_in_the_database(delivery):
    with pytest.raises(IntegrityError), transaction.atomic():
        Delivery.objects.filter(pk=delivery.pk).update(status=S.ASSIGNED)
