import pytest

from apps.accounts.models import Address, User
from apps.orders.models import Cart, Order
from apps.payments.models import Payment

pytestmark = pytest.mark.django_db


def add(client, product, quantity=1, token=None):
    headers = {"HTTP_X_CART_TOKEN": token} if token else {}
    return client.post(
        "/api/cart/items/", {"product_id": product.id, "quantity": quantity}, format="json", **headers
    )


def test_user_cart_persists_across_clients(auth_client, customer, product):
    add(auth_client(customer), product, 2)
    res = auth_client(customer).get("/api/cart/")
    assert res.data["items"][0]["quantity"] == 2
    assert Cart.objects.get().user == customer


def test_merge_sums_quantities_capped_at_stock(api_client, auth_client, customer, make_product):
    a, b = make_product(stock=5), make_product(stock=10)
    guest_token = add(api_client, a, 4).data["token"]
    add(api_client, b, 1, token=guest_token)
    client = auth_client(customer)
    add(client, a, 3)

    res = client.post("/api/cart/merge/", {"cart_token": guest_token}, format="json")
    assert res.status_code == 200, res.data
    quantities = {line["product"]["id"]: line["quantity"] for line in res.data["items"]}
    assert quantities == {a.id: 5, b.id: 1}
    assert not Cart.objects.filter(token=guest_token).exists()


def test_merge_requires_login(api_client):
    assert api_client.post("/api/cart/merge/", {"cart_token": "x"}, format="json").status_code == 401


def test_merge_unknown_token_is_404(auth_client, customer):
    res = auth_client(customer).post("/api/cart/merge/", {"cart_token": "nope"}, format="json")
    assert res.status_code == 404


def test_checkout_with_saved_address_copies_it(auth_client, customer, product, region, clickpesa):
    address = Address.objects.create(user=customer, region="Dar es Salaam", district="Ilala", street="Samora Ave 3")
    client = auth_client(customer)
    add(client, product, 1)
    res = client.post("/api/checkout/", {"address_id": address.id}, format="json")
    assert res.status_code == 201, res.data
    assert res.data["street"] == "Samora Ave 3" and res.data["district"] == "Ilala"
    assert res.data["contact_phone"] == customer.phone and res.data["delivery_fee"] == "3000.00"

    address.street = "Changed 99"
    address.save()
    order = Order.objects.get()
    assert order.street == "Samora Ave 3" and order.user == customer


def test_another_users_address_rejected(auth_client, customer, product):
    stranger = User.objects.create_user("juma")
    address = Address.objects.create(user=stranger, region="Arusha", street="X")
    client = auth_client(customer)
    add(client, product)
    res = client.post("/api/checkout/", {"address_id": address.id}, format="json")
    assert res.status_code == 400 and "address_id" in res.data
    assert not Order.objects.exists()


def test_order_list_shows_only_own_orders_newest_first(auth_client, customer, make_order):
    first = make_order(user=customer)
    second = make_order(user=customer)
    make_order()  # a guest order
    res = auth_client(customer).get("/api/orders/")
    assert res.status_code == 200
    assert [o["number"] for o in res.data["results"]] == [second.number, first.number]


def test_order_list_requires_login(api_client):
    assert api_client.get("/api/orders/").status_code == 401


def test_order_detail_owner_only(auth_client, customer, make_order):
    mine = make_order(user=customer)
    other = make_order(user=User.objects.create_user("juma"))
    client = auth_client(customer)
    res = client.get(f"/api/orders/{mine.number}/")
    assert res.status_code == 200 and res.data["items"][0]["quantity"] == 2
    assert client.get(f"/api/orders/{other.number}/").status_code == 404


def test_guest_lookup_needs_matching_phone(api_client, make_order):
    order = make_order(phone="+255712345678")
    res = api_client.post("/api/orders/lookup/", {"number": order.number, "phone": "0712345678"}, format="json")
    assert res.status_code == 200 and res.data["number"] == order.number
    res = api_client.post("/api/orders/lookup/", {"number": order.number, "phone": "+255700000000"}, format="json")
    assert res.status_code == 404
    res = api_client.post("/api/orders/lookup/", {"number": order.number, "phone": "garbage"}, format="json")
    assert res.status_code == 404


def test_pay_issues_a_new_link(api_client, auth_client, customer, make_order, clickpesa):
    from apps.payments.services import start_payment

    order = make_order(user=customer)
    start_payment(order)
    res = auth_client(customer).post(f"/api/orders/{order.number}/pay/", {}, format="json")
    assert res.status_code == 200, res.data
    assert res.data["payment_url"] == f"https://pay.test/{order.number}P2"
    assert Payment.objects.filter(order=order).count() == 2

    guest_order = make_order(phone="+255712345678")
    res = api_client.post(f"/api/orders/{guest_order.number}/pay/", {"phone": "0712345678"}, format="json")
    assert res.status_code == 200 and res.data["payment_url"].endswith("P1")
    res = api_client.post(f"/api/orders/{guest_order.number}/pay/", {"phone": "+255700000000"}, format="json")
    assert res.status_code == 404


def test_pay_refused_when_not_awaiting_payment(auth_client, customer, make_order, clickpesa):
    order = make_order(user=customer)
    order.status = Order.Status.PAID
    order.save()
    res = auth_client(customer).post(f"/api/orders/{order.number}/pay/", {}, format="json")
    assert res.status_code == 400 and res.data["code"] == "not_awaiting_payment"


def test_pay_when_provider_down(auth_client, customer, make_order, clickpesa):
    clickpesa.down = True
    order = make_order(user=customer)
    res = auth_client(customer).post(f"/api/orders/{order.number}/pay/", {}, format="json")
    assert res.status_code == 503 and res.data["code"] == "payment_unavailable"
