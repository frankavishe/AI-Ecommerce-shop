import pytest

from apps.accounts.models import RiderProfile, User
from apps.orders import services as order_services
from apps.orders.models import OrderEvent
from apps.whatsapp.testing import FakeGraph


@pytest.fixture(autouse=True)
def graph(settings):
    """Every delivery test runs against FakeGraph (rider templates, customer messages)."""
    settings.WHATSAPP_PHONE_NUMBER_ID = "test-number"
    settings.WHATSAPP_ACCESS_TOKEN = "test-token"
    settings.WHATSAPP_APP_SECRET = "test-secret"
    settings.WHATSAPP_FAKE_GRAPH = False
    fake = FakeGraph()
    from apps.whatsapp import graph as module

    module.use_fake(fake)
    yield fake
    module.reset_fake()


@pytest.fixture
def make_rider(db, region):
    counter = iter(range(1, 1000))

    def make(first_name=None, phone=None, regions=None, available=True, active=True, vehicle="motorbike",
             language="sw"):
        n = next(counter)
        user = User.objects.create_user(
            f"rider{n}", password="pw", role=User.Role.RIDER, first_name=first_name or f"Rider{n}",
            last_name="Mrisho", phone=phone or f"+2557001000{n:02d}", is_active=active,
            preferred_language=language,
        )
        profile = RiderProfile.objects.create(user=user, vehicle=vehicle, is_available=available)
        profile.regions.set([region] if regions is None else regions)
        return user

    return make


@pytest.fixture
def rider(make_rider):
    return make_rider(first_name="Juma", phone="+255700000001")


@pytest.fixture
def rider2(make_rider):
    return make_rider(first_name="Neema", phone="+255700000002")


@pytest.fixture
def pay():
    def move(order):
        return order_services.transition(order, "paid", OrderEvent.Source.PROVIDER)

    return move


@pytest.fixture
def run_commits(django_capture_on_commit_callbacks):
    """Run a callable together with the on_commit callbacks it queued (deliveries, sends)."""

    def run(fn, *args, **kwargs):
        with django_capture_on_commit_callbacks(execute=True):
            return fn(*args, **kwargs)

    return run


@pytest.fixture
def paid_order(make_order, pay, run_commits):
    order = make_order()
    run_commits(pay, order)
    return order


@pytest.fixture
def delivery(paid_order):
    from apps.delivery.services import create_for_order

    return create_for_order(paid_order)[0]
