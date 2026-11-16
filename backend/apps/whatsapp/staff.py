"""Staff tools for WhatsApp conversations (US4, contracts/admin-api.md).

A conversation's number is its contact's current conversation, or, after a 7-day reset, the contact
whose inbound messages were stored in it.
"""

from django.db.models import BigIntegerField, OuterRef, Subquery
from django.db.models.functions import Coalesce

from .models import WhatsAppContact, WhatsAppInboundMessage


def _contact_id(conversation_ref):
    current = WhatsAppContact.objects.filter(conversation=conversation_ref).values("pk")[:1]
    earlier = (WhatsAppInboundMessage.objects.filter(chat_message__conversation=conversation_ref)
               .order_by("-id").values("contact_id")[:1])
    return Coalesce(Subquery(current), Subquery(earlier), output_field=BigIntegerField())


def annotate_contacts(conversations):
    """Add wa_number, wa_profile_name and wa_last_inbound_at to a Conversation queryset (one query,
    no N+1). They are None for conversations that are not WhatsApp ones."""
    contact = WhatsAppContact.objects.filter(pk=OuterRef("wa_contact_id"))
    return conversations.annotate(wa_contact_id=_contact_id(OuterRef("pk"))).annotate(
        wa_number=Subquery(contact.values("phone")[:1]),
        wa_profile_name=Subquery(contact.values("profile_name")[:1]),
        wa_last_inbound_at=Subquery(contact.values("last_inbound_at")[:1]),
    )


def contact_for(conversation):
    """The WhatsAppContact behind a conversation, or None."""
    return (WhatsAppContact.objects.filter(conversation=conversation).first()
            or WhatsAppContact.objects.filter(inbound__chat_message__conversation=conversation).first())
