import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.throttling import SimpleRateThrottle

from apps.ai.models import ChatMessage, Conversation
from apps.ai.testing import tool_call
from apps.orders import services
from apps.orders.models import Cart

pytestmark = pytest.mark.django_db

URL = "/api/ai/chat/"


def post(client, **data):
    return client.post(URL, data, format="json")


def test_first_message_starts_a_guest_conversation_with_a_cart(api_client, chat_model):
    chat_model.add("Karibu!")
    res = post(api_client, message="habari, nataka viatu")
    assert res.status_code == 200, res.data
    body = res.json()
    assert body["reply"] == "Karibu!"
    assert body["language"] == "sw"
    assert body["state"] == "active"
    assert body["error"] is None
    conversation = Conversation.objects.get(token=body["conversation_token"])
    assert conversation.user is None
    assert body["cart_token"] == conversation.cart.token
    # The same cart works in the regular shop API.
    assert api_client.get("/api/cart/", HTTP_X_CART_TOKEN=body["cart_token"]).json()["token"] == body["cart_token"]


def test_reply_products_come_from_the_database(api_client, chat_model, shoe_catalog):
    chat_model.add([tool_call("search_products", query="red sneakers")], "Red Sneakers: TZS 5")
    body = post(api_client, message="Do you have red sneakers?").json()
    assert body["products"][0]["name"] == "Red Sneakers"
    assert body["products"][0]["price"] == "45000.00"
    assert body["products"][0]["in_stock"] is True


def test_continuing_a_conversation_keeps_history(api_client, chat_model):
    first = post(api_client, message="nataka viatu").json()
    post(api_client, message="vyekundu", conversation=first["conversation_token"])
    assert {"role": "user", "content": "nataka viatu"} in chat_model.last_messages
    assert Conversation.objects.count() == 1


def test_unknown_token_is_404(api_client):
    assert post(api_client, message="hi there", conversation="nope").status_code == 404


def test_customer_conversation_is_private(api_client, auth_client, customer, chat_model, django_user_model):
    mine = post(auth_client(customer), message="hello there friend").json()
    assert mine["cart_token"] is None
    token = mine["conversation_token"]
    assert post(api_client, message="hi", conversation=token).status_code == 404
    other = django_user_model.objects.create_user("juma", password="pw", phone="+255712000002")
    assert post(auth_client(other), message="hi", conversation=token).status_code == 404
    assert post(auth_client(customer), message="still me", conversation=token).status_code == 200


def test_guest_conversation_is_claimed_on_login_and_cart_merged(api_client, auth_client, customer, product):
    guest = post(api_client, message="nataka viatu").json()
    conversation = Conversation.objects.get(token=guest["conversation_token"])
    services.add_item(conversation.cart, product.pk, 2)

    res = post(auth_client(customer), message="nimeingia sasa", conversation=guest["conversation_token"])
    assert res.status_code == 200
    conversation.refresh_from_db()
    assert conversation.user == customer
    assert conversation.cart is None
    assert Cart.objects.get(user=customer).items.get().quantity == 2
    assert res.json()["cart_token"] is None


def test_validation(api_client, png_bytes, settings):
    assert post(api_client, message="").status_code == 400
    assert post(api_client, message="x" * (settings.AI_MESSAGE_MAX_CHARS + 1)).status_code == 400
    fake = SimpleUploadedFile("photo.jpg", b"not really an image", content_type="image/jpeg")
    assert api_client.post(URL, {"image": fake}, format="multipart").status_code == 400
    gif = SimpleUploadedFile("photo.gif", png_bytes(fmt="GIF"), content_type="image/gif")
    assert api_client.post(URL, {"image": gif}, format="multipart").status_code == 400


def test_oversize_photo_is_rejected(api_client, png_bytes, settings):
    settings.AI_UPLOAD_MAX_BYTES = 100
    photo = SimpleUploadedFile("p.png", png_bytes(), content_type="image/png")
    res = api_client.post(URL, {"image": photo}, format="multipart")
    assert res.status_code == 400
    assert "too large" in str(res.data)


def test_photo_is_stored_and_flagged_to_the_model(api_client, png_bytes, chat_model, settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    photo = SimpleUploadedFile("p.png", png_bytes(), content_type="image/png")
    res = api_client.post(URL, {"image": photo, "message": "hii mnayo?"}, format="multipart")
    assert res.status_code == 200, res.data
    message = ChatMessage.objects.get(role="user")
    assert message.image.name.startswith("ai/chat/")
    assert "[The shopper attached a photo" in chat_model.last_messages[-1]["content"]


@pytest.fixture
def low_rates(monkeypatch):
    monkeypatch.setattr(SimpleRateThrottle, "THROTTLE_RATES", {"ai_chat": "3/min", "ai_conversation": "2/min"})


def test_per_conversation_rate_limit(api_client, low_rates):
    token = post(api_client, message="habari yako").json()["conversation_token"]  # no token yet: not counted
    assert post(api_client, message="moja", conversation=token).status_code == 200
    assert post(api_client, message="mbili", conversation=token).status_code == 200
    assert post(api_client, message="tatu", conversation=token).status_code == 429


def test_per_client_rate_limit(api_client, low_rates):
    for _ in range(3):
        assert post(api_client, message="habari yako").status_code == 200
    assert post(api_client, message="habari yako").status_code == 429
