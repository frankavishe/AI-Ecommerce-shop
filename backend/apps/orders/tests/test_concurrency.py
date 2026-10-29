import threading

import pytest
from django.db import connection

from apps.orders import services
from apps.orders.models import Cart, Order

THREADS = 20


@pytest.mark.django_db(transaction=True)
def test_last_unit_is_sold_exactly_once(make_product):
    product = make_product(stock=1)
    carts = []
    for _ in range(THREADS):
        cart = Cart.objects.create()
        services.add_item(cart, product.id, 1)
        carts.append(cart)

    barrier = threading.Barrier(THREADS)
    outcomes = []
    lock = threading.Lock()

    def buy(cart):
        try:
            barrier.wait()
            services.place_order(
                cart, {"name": "Shopper", "phone": "+255712345678"},
                {"region": "Dar es Salaam", "street": "Mtaa 1"},
            )
            result = "ok"
        except services.OutOfStock:
            result = "out_of_stock"
        except Exception as exc:  # noqa: BLE001 - recorded so the assertion shows it
            result = repr(exc)
        finally:
            connection.close()
        with lock:
            outcomes.append(result)

    threads = [threading.Thread(target=buy, args=(c,)) for c in carts]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert sorted(outcomes) == ["ok"] + ["out_of_stock"] * (THREADS - 1)
    assert Order.objects.count() == 1
    product.refresh_from_db()
    assert product.stock == 0
