"""The rider's assistant tools (contracts/rider-tools.md, research R5).

The caller is always ctx.user, an active rider: no tool takes a rider id from the model. A job is
found only among the rider's own deliveries, and any miss (no such order, someone else's order, a
closed job) gets the same `not_found`, so nothing leaks about other orders (FR-016, SC-005). The
agent loop wraps every result in <data>, so customer notes stay data (FR-026).
"""

from apps.accounts.models import RiderProfile
from apps.ai.tools import RIDER, register

from . import services
from .models import ACTIVE, Delivery

S = Delivery.Status
NOT_FOUND = {"ok": False, "error": "not_found"}
RIDER_STATUSES = [S.PICKED_UP, S.ON_THE_WAY, S.DELIVERED, S.FAILED]
JOB_LIMIT = 10


def _jobs(ctx, statuses=ACTIVE):
    return Delivery.objects.filter(rider=ctx.user, status__in=statuses).select_related("order")


def _find(ctx, order_number, statuses=ACTIVE):
    number = (order_number or "").strip().upper().lstrip("#")
    if not number:
        return None
    return _jobs(ctx, statuses).filter(order__number=number).first()


@register(
    "my_jobs",
    "List this rider's active delivery jobs (assigned, picked up, on the way), oldest first.",
    {}, roles=(RIDER,),
)
def my_jobs(ctx):
    jobs = _jobs(ctx).order_by("assigned_at", "id")[:JOB_LIMIT]
    return {"jobs": [
        {"order_number": d.order.number, "status": d.status, "region": d.order.region,
         "street": d.order.street, "contact_name": d.order.contact_name,
         "assigned_at": d.assigned_at.isoformat() if d.assigned_at else None}
        for d in jobs
    ]}


@register(
    "job_details",
    "Details of one of this rider's active jobs: customer name and phone, address, items.",
    {"order_number": {"type": "string", "description": "The order number, e.g. K7P2QX"}},
    required=("order_number",), roles=(RIDER,),
)
def job_details(ctx, order_number):
    delivery = _find(ctx, order_number)
    if delivery is None:
        return NOT_FOUND
    order = delivery.order
    return {
        "order_number": order.number, "status": delivery.status,
        "contact_name": order.contact_name, "contact_phone": order.contact_phone,
        "region": order.region, "district": order.district, "street": order.street, "notes": order.notes,
        "items": [{"name": item.product_name, "quantity": item.quantity} for item in order.items.all()],
        "paid": order.paid_at is not None,
    }


@register(
    "update_delivery",
    "Record progress on one of this rider's jobs. Use failed (with the reason) when it can't be delivered.",
    {
        "order_number": {"type": "string", "description": "The order number"},
        "status": {"type": "string", "enum": [str(s) for s in RIDER_STATUSES]},
        "reason": {"type": "string", "maxLength": 255, "description": "Why it failed (only for failed)"},
    },
    required=("order_number", "status"), roles=(RIDER,), mutates=True,
    label={"sw": "hali ya usafirishaji imesasishwa", "en": "delivery status updated"},
)
def update_delivery(ctx, order_number, status, reason=""):
    # a repeat on a just-closed job (delivered twice) must answer "already", not "not found" (FR-017)
    delivery = _find(ctx, order_number, ACTIVE | {status})
    if delivery is None:
        return NOT_FOUND
    if status == S.FAILED and not (reason or "").strip():
        return {"ok": False, "error": "reason_required"}
    try:
        result = services.change(delivery, status, ctx.user, actor_type="rider", note=reason,
                                 expect={"rider": ctx.user})
    except services.StaleDelivery:
        return {"ok": False, "error": "not_yours_anymore"}
    except services.InvalidDeliveryTransition as exc:
        return {"ok": False, "error": "invalid_transition", "current": exc.extra["current"]}
    if result.already:
        return {"status": result.status, "already": True}
    return {"status": result.status, "recorded": [str(s) for s in result.recorded]}


@register(
    "set_availability",
    "Mark this rider available or unavailable for new jobs. Current jobs stay with the rider.",
    {"available": {"type": "boolean"}},
    required=("available",), roles=(RIDER,), mutates=True,
    label={"sw": "upatikanaji umebadilishwa", "en": "availability changed"},
)
def set_availability(ctx, available):
    RiderProfile.objects.filter(user=ctx.user).update(is_available=available)
    return {"available": available, "active_jobs": _jobs(ctx).count()}
