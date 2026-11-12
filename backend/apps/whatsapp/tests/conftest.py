import pytest
from django.utils import timezone

from apps.whatsapp.models import WhatsAppContact
from apps.whatsapp.testing import FakeGraph, signed_post


@pytest.fixture(autouse=True)
def graph(settings):
    settings.WHATSAPP_APP_SECRET = "test-secret"
    settings.WHATSAPP_VERIFY_TOKEN = "test-verify"
    settings.WHATSAPP_PHONE_NUMBER_ID = "test-number"
    settings.WHATSAPP_ACCESS_TOKEN = "test-token"
    settings.WHATSAPP_BUSINESS_NUMBER = "+255700000000"
    settings.WHATSAPP_FAKE_GRAPH = False
    fake = FakeGraph()
    from apps.whatsapp import graph as module

    module.use_fake(fake)
    yield fake
    module.reset_fake()


@pytest.fixture
def contact_factory(db):
    def make(wa_id="255742000331", **kw):
        kw.setdefault("phone", "+" + wa_id)
        kw.setdefault("last_inbound_at", timezone.now())
        return WhatsAppContact.objects.create(wa_id=wa_id, **kw)

    return make


@pytest.fixture
def deliver_inbound(client, django_capture_on_commit_callbacks):
    """POST a signed payload and run the queued work (drain + deliver) like a worker would."""

    def post(payload, secret=None):
        with django_capture_on_commit_callbacks(execute=True):
            response = signed_post(client, payload, secret=secret)
        return response

    return post

