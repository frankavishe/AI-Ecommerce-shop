import pytest
from rest_framework.test import APIClient

from apps.accounts.models import RiderProfile, User


@pytest.fixture
def client():
    return APIClient()


@pytest.fixture
def admin_client(client):
    admin = User.objects.create_user("boss", password="pass12345", role=User.Role.ADMIN)
    client.force_authenticate(admin)
    return client


@pytest.mark.django_db
def test_register_and_login_returns_role(client):
    res = client.post(
        "/api/auth/register/",
        {"username": "amina", "password": "s3cretpass!", "phone": "+255712345678"},
        format="json",
    )
    assert res.status_code == 201
    assert User.objects.get(username="amina").role == "customer"

    res = client.post("/api/auth/login/", {"username": "amina", "password": "s3cretpass!"}, format="json")
    assert res.status_code == 200
    assert res.data["user"]["role"] == "customer"
    assert "access" in res.data


@pytest.mark.django_db
def test_customer_cannot_change_own_role(client):
    user = User.objects.create_user("juma", password="pass12345")
    client.force_authenticate(user)
    client.patch("/api/auth/me/", {"role": "admin"}, format="json")
    user.refresh_from_db()
    assert user.role == "customer"


@pytest.mark.django_db
def test_admin_registers_rider(admin_client):
    res = admin_client.post(
        "/api/auth/riders/",
        {"username": "rider1", "first_name": "Baraka", "phone": "+255754000111",
         "vehicle": "motorbike", "zone": "Kinondoni"},
        format="json",
    )
    assert res.status_code == 201, res.data
    rider = RiderProfile.objects.get()
    assert rider.user.role == "rider"
    assert not rider.user.has_usable_password()


@pytest.mark.django_db
def test_rider_phone_must_be_unique(admin_client):
    User.objects.create_user("x", phone="+255754000111")
    res = admin_client.post(
        "/api/auth/riders/",
        {"username": "rider1", "first_name": "B", "phone": "+255754000111"},
        format="json",
    )
    assert res.status_code == 400


@pytest.mark.django_db
def test_non_admin_cannot_register_rider(client):
    client.force_authenticate(User.objects.create_user("c", password="pass12345"))
    res = client.post("/api/auth/riders/", {}, format="json")
    assert res.status_code == 403
