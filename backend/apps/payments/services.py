"""Payment rules for Stakaba (apps/payments/stakaba.md).

Where a payment's outcome comes from, most trusted first:
1. The response to our own authenticated create call (mobile money returns a status).
2. GET /transactions/{ref}, when STAKABA_CONFIRM_VIA_API is on (Stakaba only accepts a dashboard
   Bearer token there today, so it is off).
3. The webhook, accepted only on the secret-token URL; the amount and currency still have to match.
"""

import logging
from dataclasses import dataclass

from django.db import transaction

from apps.orders import services as orders
from apps.orders.models import Order, OrderEvent

from . import stakaba
from .models import Payment
from .stakaba import MOBILE_MONEY_MINIMUM, NETWORKS, PaymentProviderUnavailable, PaymentRejected

logger = logging.getLogger(__name__)

PAID_STATUSES = {"SUCCESS", "SUCCESSFUL", "COMPLETED", "SETTLED"}
FAILED_STATUSES = {"FAILED", "EXPIRED", "CANCELLED", "CANCELED", "REJECTED"}
PROVIDER = OrderEvent.Source.PROVIDER

UNAVAILABLE = "The payment service is unavailable right now. Please try again shortly."


@dataclass
class PaymentError:
    code: str  # payment_unavailable | payment_rejected | payment_failed
    message: str

    def __str__(self):
        return self.message


def card_email(order, email=None):
    return email or order.contact_email or (order.user.email if order.user_id else "") or ""


def check_payment_options(order, method, network=None, email=None):
    """Return a PaymentError if this method can't be used for the order, else None.

    Also used by serializers before an order is placed (pass an unsaved Order with a total)."""
    if method == Payment.Method.CARD:
        if not card_email(order, email):
            return PaymentError("payment_rejected", "An email address is needed to pay by card.")
        return None
    if order.total < MOBILE_MONEY_MINIMUM:
        return PaymentError(
            "payment_rejected", f"Mobile money needs at least {MOBILE_MONEY_MINIMUM:.0f} TZS. Please pay by card."
        )
    if order.total != order.total.to_integral_value():
        return PaymentError("payment_rejected", "Mobile money needs a whole-shilling total. Please pay by card.")
    chosen = network or stakaba.guess_network(order.contact_phone)
    if chosen not in NETWORKS:
        return PaymentError(
            "payment_rejected", "Please choose your mobile money network (M-Pesa, Airtel Money, Mixx by Yas or HaloPesa)."
        )
    return None


def start_payment(order, method=Payment.Method.MOBILE_MONEY, network=None, email=None):
    """Start a payment attempt with its own reference.

    Card: Stakaba returns a hosted checkout URL (Payment.checkout_link).
    Mobile money: Stakaba pushes a USSD prompt to the order's phone; there is no URL.

    Returns (payment, None) or (None, PaymentError). Failed attempts keep their row so the next
    attempt gets a fresh reference. Creates are never retried automatically: Stakaba has no
    idempotency key, so a retry could send a second prompt or charge twice.
    """
    error = check_payment_options(order, method, network, email)
    if error:
        return None, error
    network = network or stakaba.guess_network(order.contact_phone)
    email = card_email(order, email)

    with transaction.atomic():
        locked = Order.objects.select_for_update().get(pk=order.pk)
        if email and method == Payment.Method.CARD and locked.contact_email != email:
            locked.contact_email = email
            locked.save(update_fields=["contact_email"])
        reference = f"{locked.number}P{locked.payments.count() + 1}"
        payment = Payment.objects.create(
            order=locked, reference=reference, amount=locked.total, method=method,
            channel=network if method == Payment.Method.MOBILE_MONEY else "",
        )

    client = stakaba.get_client()
    try:
        if method == Payment.Method.CARD:
            result = client.create_card_payment(
                reference, locked.total, locked.contact_name, locked.contact_phone, email
            )
        else:
            result = client.create_collection(reference, locked.total, locked.contact_phone, network)
    except (PaymentProviderUnavailable, PaymentRejected) as exc:
        payment.status = Payment.Status.FAILED
        payment.raw_payload = {"error": str(exc)}
        payment.save(update_fields=["status", "raw_payload", "updated_at"])
        if isinstance(exc, PaymentRejected):
            return None, PaymentError("payment_rejected", _rejection_message(exc))
        return None, PaymentError("payment_unavailable", UNAVAILABLE)

    payment.provider_ref = result["internal_reference"][:100]
    payment.checkout_link = result.get("checkout_url", "")
    payment.raw_payload = {"create": result}
    payment.save(update_fields=["provider_ref", "checkout_link", "raw_payload", "updated_at"])

    status = result.get("status", "")
    if status in PAID_STATUSES | FAILED_STATUSES:
        # Our own authenticated call answered: the amount is the one we asked for.
        with transaction.atomic():
            locked_payment = Payment.objects.select_for_update().get(pk=payment.pk)
            apply_provider_status(locked_payment, {
                "status": status, "amount": locked_payment.amount, "currency": "TZS",
                "network": network, "receipt": "",
            })
        payment.refresh_from_db()
        if payment.status == Payment.Status.FAILED:
            return None, PaymentError(
                "payment_failed", "The mobile money payment was declined. Please try again or use another method."
            )
    return payment, None


def _rejection_message(exc):
    message = exc.message.lower()
    if "not registered" in message:
        return "This number is not registered for mobile money on that network. Please check the number or pick another network."
    if exc.code == "invalid_network" or "network" in message:
        return "Please check your mobile money network and number."
    return "The payment was not accepted. Please check your details and try again."


def _flag_for_review(order, note):
    if Order.Status.NEEDS_REVIEW in orders.TRANSITIONS.get(order.status, set()):
        orders.transition(order, Order.Status.NEEDS_REVIEW, PROVIDER, note=note)
    elif order.status != Order.Status.NEEDS_REVIEW:
        # Final states (e.g. cancelled) keep their status; the timeline still shows the money.
        OrderEvent.objects.create(order=order, status=order.status, source=PROVIDER, note=note)


def apply_provider_status(payment, tx):
    """Apply a normalised Stakaba transaction (see stakaba.normalise_transaction) to a payment.

    Call with the payment row locked. Success is final; failed and mismatched attempts can still
    succeed later. Unknown statuses (pending, processing) change nothing.
    """
    fields = ["updated_at"]
    if tx.get("receipt"):
        payment.receipt = tx["receipt"][:100]
        fields.append("receipt")
    if payment.status == Payment.Status.SUCCESS:
        payment.save(update_fields=fields)
        return payment

    status = (tx.get("status") or "").upper()
    if status in PAID_STATUSES:
        if tx.get("currency", "TZS") != "TZS" or tx.get("amount") is None:
            logger.warning("Payment %s: paid status with currency %r / amount %r ignored",
                           payment.reference, tx.get("currency"), tx.get("amount"))
            payment.save(update_fields=fields)
            return payment
        order = Order.objects.select_for_update().get(pk=payment.order_id)
        payment.collected_amount = tx["amount"]
        if tx.get("network"):
            payment.channel = tx["network"][:60]
        fields += ["collected_amount", "channel", "status"]
        if payment.collected_amount >= order.total:
            payment.status = Payment.Status.SUCCESS
            payment.save(update_fields=fields)
            if order.status == Order.Status.AWAITING_PAYMENT:
                orders.transition(order, Order.Status.PAID, PROVIDER, note=f"Payment {payment.reference}")
            else:
                _flag_for_review(order, f"Payment {payment.reference} received while order was {order.status}.")
        else:
            payment.status = Payment.Status.MISMATCH
            payment.save(update_fields=fields)
            _flag_for_review(
                order, f"Payment {payment.reference} collected {payment.collected_amount} of {order.total} TZS."
            )
        return payment

    if status in FAILED_STATUSES and payment.status == Payment.Status.PENDING:
        payment.status = Payment.Status.FAILED
        fields.append("status")
    payment.save(update_fields=fields)
    return payment
