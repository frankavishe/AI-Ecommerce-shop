"""Delivery business rules (research R2â€“R4, R8, R9).

Every delivery write goes through `change()`: it locks the delivery row, checks the move against the
transition table, records the timeline, moves the order forward through orders.services.transition()
and hands the notices (who must hear about it) to NOTIFY_HOOKS inside the same transaction.
"""

from dataclasses import dataclass, field

from django.db import transaction
from django.utils import timezone

from apps.accounts.models import RiderProfile, User
from apps.orders import services as order_services
from apps.orders.models import Order, OrderEvent
from apps.orders.services import ShopError

from .models import ACTIVE, OPEN, Delivery, DeliveryEvent

S = Delivery.Status
OS = Order.Status


class DeliveryError(ShopError):
    code = "delivery_error"


class InvalidDeliveryTransition(DeliveryError):
    code = "invalid_transition"
    status_code = 409


class StaleDelivery(DeliveryError):
    code = "stale"
    status_code = 409

    def __init__(self, detail, delivery):
        super().__init__(detail)
        self.delivery = delivery


class ReasonRequired(DeliveryError):
    code = "reason_required"


class RiderUnavailable(DeliveryError):
    code = "rider_unavailable"


# Direct moves (data-model.md). assigned -> on_the_way / delivered pass through picked_up (US2-7).
TRANSITIONS = {
    S.WAITING: {S.ASSIGNED, S.CANCELLED},
    S.ASSIGNED: {S.ASSIGNED, S.WAITING, S.PICKED_UP, S.CANCELLED},
    S.PICKED_UP: {S.ON_THE_WAY, S.DELIVERED, S.FAILED, S.CANCELLED},
    S.ON_THE_WAY: {S.DELIVERED, S.FAILED, S.CANCELLED},
    S.FAILED: {S.WAITING, S.ASSIGNED, S.CANCELLED},
    S.DELIVERED: set(),
    S.CANCELLED: set(),
}
THROUGH_PICKUP = {S.ON_THE_WAY, S.DELIVERED}

# The order status each delivery step needs (R4); the order is walked forward along ORDER_PATH.
ORDER_TARGET = {S.ASSIGNED: OS.PROCESSING, S.PICKED_UP: OS.OUT_FOR_DELIVERY,
                S.ON_THE_WAY: OS.OUT_FOR_DELIVERY, S.DELIVERED: OS.DELIVERED}
ORDER_PATH = [OS.PAID, OS.PROCESSING, OS.OUT_FOR_DELIVERY, OS.DELIVERED]

TIMESTAMP = {S.ASSIGNED: "assigned_at", S.PICKED_UP: "picked_up_at", S.DELIVERED: "delivered_at",
             S.FAILED: "failed_at"}

# Called inside change()'s transaction as hook(delivery, notices); senders queue on_commit themselves.
NOTIFY_HOOKS = []


@dataclass
class Result:
    delivery: Delivery
    status: str
    recorded: list = field(default_factory=list)
    already: bool = False
    notices: list = field(default_factory=list)  # [(kind, rider or None)]


# --- Riders -------------------------------------------------------------------------------------


def is_assignable(user):
    if user is None or user.role != User.Role.RIDER or not user.is_active:
        return False
    profile = RiderProfile.objects.filter(user=user).first()
    return profile is not None and profile.is_available


# --- The one write path -------------------------------------------------------------------------


def _path(current, to):
    if to in TRANSITIONS[current]:
        return [to]
    if current == S.ASSIGNED and to in THROUGH_PICKUP:
        return [S.PICKED_UP, to]
    return None


def _check_expect(d, expect):
    if not expect:
        return
    if "status" in expect and expect["status"] is not None and d.status != expect["status"]:
        raise StaleDelivery("This delivery has changed meanwhile.", d)
    if "rider" in expect:
        wanted = expect["rider"]
        wanted_id = getattr(wanted, "pk", wanted)
        if d.rider_id != wanted_id:
            raise StaleDelivery("This delivery has changed meanwhile.", d)


def _advance_order(order, target, actor, note):
    if order.status not in ORDER_PATH:
        return
    start, end = ORDER_PATH.index(order.status), ORDER_PATH.index(target)
    for status in ORDER_PATH[start + 1:end + 1]:
        order_services.transition(order, status, OrderEvent.Source.SYSTEM, actor=actor, note=note)


def change(delivery, to, actor=None, *, actor_type, rider=None, note="", expect=None):
    """Move a delivery to `to`. Returns a Result; repeating the current status is a no-op
    (`already=True`). Raises InvalidDeliveryTransition, StaleDelivery, ReasonRequired, RiderUnavailable."""
    note = (note or "").strip()[:255]
    with transaction.atomic():
        d = Delivery.objects.select_for_update(of=("self",)).select_related("order", "rider").get(pk=delivery.pk)
        _check_expect(d, expect)
        if to == d.status and (to != S.ASSIGNED or rider is None or rider.pk == d.rider_id):
            _sync(delivery, d)
            return Result(d, d.status, already=True)
        path = _path(d.status, to)
        if path is None:
            raise InvalidDeliveryTransition(
                f"A delivery can't move from {d.status} to {to}.", current=d.status)
        if to == S.FAILED and not note:
            raise ReasonRequired("Say why the delivery failed.")
        if to == S.ASSIGNED and not is_assignable(rider):
            raise RiderUnavailable("This rider can't take deliveries right now.")

        result = Result(d, to)
        previous_rider = d.rider
        now = timezone.now()
        for step in path:
            event_note = note
            if d.status == S.FAILED and step in (S.WAITING, S.ASSIGNED):  # a new attempt (R2)
                d.attempt += 1
                d.rider = None
                d.failure_reason = ""
                d.assigned_at = d.picked_up_at = d.delivered_at = d.failed_at = None
                previous_rider = None
            if step == S.ASSIGNED:
                if previous_rider is not None and previous_rider.pk != rider.pk:
                    result.notices.append(("removed", previous_rider))
                result.notices.append(("assigned", rider))
                d.rider = rider
                RiderProfile.objects.filter(user=rider).update(last_assigned_at=now)
            elif step == S.WAITING and d.status == S.ASSIGNED:
                result.notices.append(("removed", previous_rider))
                event_note = event_note or f"unassigned from {previous_rider.get_full_name() or previous_rider}"
                d.rider = None
            elif step == S.CANCELLED:
                if d.status in ACTIVE and d.rider is not None:
                    result.notices.append(("cancelled", d.rider))
            elif step == S.FAILED:
                d.failure_reason = note
                result.notices.append(("customer_failed", None))
            if step in TIMESTAMP:
                setattr(d, TIMESTAMP[step], now)
            d.status = step
            d.save()
            DeliveryEvent.objects.create(delivery=d, status=step, attempt=d.attempt, rider=d.rider,
                                         actor_type=actor_type, actor=actor, note=event_note)
            result.recorded.append(step)
            if step in ORDER_TARGET:
                _advance_order(d.order, ORDER_TARGET[step], actor, note=f"delivery: {step}")
        for hook in NOTIFY_HOOKS:
            hook(d, result.notices)
    _sync(delivery, d)
    return result


def _sync(target, source):
    """Refresh the caller's instance with the saved row (callers keep using their object)."""
    if target is not source:
        for name in ("status", "rider_id", "attempt", "failure_reason", "assigned_at", "picked_up_at",
                     "delivered_at", "failed_at", "updated_at"):
            setattr(target, name, getattr(source, name))
        target._state.fields_cache.pop("rider", None)


# --- Helpers used by views, signals and rider tools ------------------------------------------------


def assign(delivery, rider, actor, expect=None, actor_type=DeliveryEvent.Actor.ADMIN):
    return change(delivery, S.ASSIGNED, actor, actor_type=actor_type, rider=rider, expect=expect)


def unassign(delivery, actor, expect=None):
    return change(delivery, S.WAITING, actor, actor_type=DeliveryEvent.Actor.ADMIN,
                  expect={"status": S.ASSIGNED, **(expect or {})})


def retry(delivery, actor, rider=None):
    """A new attempt after a failure (US5): back to waiting, or straight to the chosen rider."""
    target = S.ASSIGNED if rider is not None else S.WAITING
    try:
        return change(delivery, target, actor, actor_type=DeliveryEvent.Actor.ADMIN, rider=rider,
                      expect={"status": S.FAILED})
    except StaleDelivery as exc:
        raise InvalidDeliveryTransition("Only a failed delivery can be tried again.",
                                        current=exc.delivery.status) from None


DELIVERABLE = {OS.PAID, OS.PROCESSING}


def create_for_order(order):
    """The one delivery of an order (FR-001, FR-005); replays find the existing row."""
    return Delivery.objects.get_or_create(order=order)


def cancel_for_order(order, actor=None):
    """The order was cancelled: close its open delivery (FR-004). None when there is nothing open."""
    delivery = Delivery.objects.filter(order=order, status__in=OPEN | {S.FAILED}).first()
    if delivery is None:
        return None
    try:
        return change(delivery, S.CANCELLED, actor, actor_type=DeliveryEvent.Actor.SYSTEM,
                      note="order cancelled")
    except InvalidDeliveryTransition:  # closed meanwhile
        return None
