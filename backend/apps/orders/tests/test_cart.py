import pytest

from apps.orders.models import Cart

pytestmark = pytest.mark.django_db


def guest_get(client):
    res = client.get("/api/cart/")
    assert res.status_code == 200
    return res.data["token"]


def test_guest_get_creates_cart_and_token(api_client):
    token = guest_get(api_client)
    assert token and Cart.objects.filter(token=token, user=None).exists()
    res = api_client.get("/api/cart/", HTTP_X_CART_TOKEN=token)
    assert res.data["token"] == token
    assert res.data["items"] == [] and res.data["subtotal"] == "0.00"
    assert Cart.objects.count() == 1


def test_add_update_remove_clear(api_client, product, make_product):
    token = guest_get(api_client)
    other = make_product(price=1500)
    headers = {"HTTP_X_CART_TOKEN": token}

    res = api_client.post("/api/cart/items/", {"product_id": product.id, "quantity": 2}, format="json", **headers)
    assert res.status_code == 200, res.data
    res = api_client.post("/api/cart/items/", {"product_id": product.id}, format="json", **headers)
    assert res.data["items"][0]["quantity"] == 3
    api_client.post("/api/cart/items/", {"product_id": other.id, "quantity": 2}, format="json", **headers)

    res = api_client.get("/api/cart/", **headers)
    assert res.data["item_count"] == 5
    assert res.data["subtotal"] == "138000.00"  # 3 x 45,000 + 2 x 1,500
    line = res.data["items"][0]
    assert line["unit_price"] == "45000.00" and line["line_total"] == "135000.00"
    assert line["product"]["slug"] == product.slug

    res = api_client.patch(f"/api/cart/items/{product.id}/", {"quantity": 1}, format="json", **headers)
    assert res.data["items"][0]["quantity"] == 1
    res = api_client.delete(f"/api/cart/items/{other.id}/", **headers)
    assert [i["product"]["id"] for i in res.data["items"]] == [product.id]

    res = api_client.delete("/api/cart/", **headers)
    assert res.status_code == 204
    assert api_client.get("/api/cart/", **headers).data["items"] == []


def test_inactive_product_rejected(api_client, make_product):
    hidden = make_product(is_active=False)
    res = api_client.post("/api/cart/items/", {"product_id": hidden.id}, format="json")
    assert res.status_code == 400
    assert res.data["code"] == "inactive_product"


def test_unknown_product_is_404(api_client):
    res = api_client.post("/api/cart/items/", {"product_id": 999999}, format="json")
    assert res.status_code == 404


def test_quantity_above_stock_rejected_with_available_count(api_client, make_product):
    p = make_product(stock=3)
    token = guest_get(api_client)
    res = api_client.post(
        "/api/cart/items/", {"product_id": p.id, "quantity": 4}, format="json", HTTP_X_CART_TOKEN=token
    )
    assert res.status_code == 400
    assert res.data["code"] == "out_of_stock" and res.data["available"] == 3
    assert "3" in res.data["detail"]

    api_client.post("/api/cart/items/", {"product_id": p.id, "quantity": 2}, format="json", HTTP_X_CART_TOKEN=token)
    res = api_client.patch(f"/api/cart/items/{p.id}/", {"quantity": 5}, format="json", HTTP_X_CART_TOKEN=token)
    assert res.status_code == 400 and res.data["code"] == "out_of_stock"


def test_quantity_zero_removes_and_negative_rejected(api_client, product):
    token = guest_get(api_client)
    headers = {"HTTP_X_CART_TOKEN": token}
    api_client.post("/api/cart/items/", {"product_id": product.id, "quantity": 2}, format="json", **headers)

    assert api_client.patch(f"/api/cart/items/{product.id}/", {"quantity": -1}, format="json", **headers).status_code == 400
    assert api_client.post("/api/cart/items/", {"product_id": product.id, "quantity": 0}, format="json", **headers).status_code == 400

    res = api_client.patch(f"/api/cart/items/{product.id}/", {"quantity": 0}, format="json", **headers)
    assert res.status_code == 200 and res.data["items"] == []


def test_client_price_is_ignored(api_client, product):
    res = api_client.post(
        "/api/cart/items/", {"product_id": product.id, "quantity": 1, "price": "1.00"}, format="json"
    )
    assert res.data["items"][0]["unit_price"] == "45000.00"
    assert res.data["subtotal"] == "45000.00"


def test_price_is_read_live(api_client, product):
    token = guest_get(api_client)
    api_client.post("/api/cart/items/", {"product_id": product.id}, format="json", HTTP_X_CART_TOKEN=token)
    product.price = 40000
    product.save()
    res = api_client.get("/api/cart/", HTTP_X_CART_TOKEN=token)
    assert res.data["subtotal"] == "40000.00"
