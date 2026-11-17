"""Two admins assigning the same delivery at once: one wins, the other is stale (FR-009, R9)."""

import threading

import pytest
from django.db import connection

from apps.delivery import services
from apps.delivery.models import Delivery, DeliveryEvent


@pytest.mark.django_db(transaction=True)
def test_concurrent_assign_has_one_winner(paid_order, rider, rider2, admin_user):
    delivery = Delivery.objects.get(order=paid_order)
    barrier = threading.Barrier(2)
    outcomes = []

    def attempt(who):
        try:
            barrier.wait()
            services.assign(Delivery.objects.get(pk=delivery.pk), who, admin_user, expect={"status": "waiting"})
            outcomes.append("ok")
        except services.StaleDelivery:
            outcomes.append("stale")
        finally:
            connection.close()

    threads = [threading.Thread(target=attempt, args=(r,)) for r in (rider, rider2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(outcomes) == ["ok", "stale"]
    assert DeliveryEvent.objects.filter(delivery=delivery, status="assigned").count() == 1
