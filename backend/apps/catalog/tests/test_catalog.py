import io

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.catalog.models import Category, Product


def png_file(name="p.png"):
    buf = io.BytesIO()
    Image.new("RGB", (10, 10), "red").save(buf, "PNG")
    return SimpleUploadedFile(name, buf.getvalue(), content_type="image/png")


@pytest.fixture
def admin_client(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    client = APIClient()
    client.force_authenticate(User.objects.create_user("boss", role=User.Role.ADMIN))
    return client


@pytest.mark.django_db
def test_admin_creates_product_with_images(admin_client):
    cat = Category.objects.create(name="Shoes", name_sw="Viatu")
    res = admin_client.post(
        "/api/products/",
        {"name": "Red Sneakers", "price": "45000", "stock": 3, "category": cat.id,
         "uploaded_images": [png_file("a.png"), png_file("b.png")]},
        format="multipart",
    )
    assert res.status_code == 201, res.data
    product = Product.objects.get()
    assert product.slug == "red-sneakers"
    assert product.images.count() == 2


@pytest.mark.django_db
def test_public_sees_only_active_products_without_stock_numbers():
    Product.objects.create(name="Visible", price=1000, stock=2)
    Product.objects.create(name="Hidden", price=1000, is_active=False)
    res = APIClient().get("/api/products/")
    assert res.status_code == 200
    names = [p["name"] for p in res.data["results"]]
    assert names == ["Visible"]
    assert "stock" not in res.data["results"][0]
    assert res.data["results"][0]["in_stock"] is True


@pytest.mark.django_db
def test_customer_cannot_create_product():
    client = APIClient()
    client.force_authenticate(User.objects.create_user("c"))
    res = client.post("/api/products/", {"name": "X", "price": "10"}, format="json")
    assert res.status_code == 403


@pytest.mark.django_db
def test_product_filters_and_search():
    shoes = Category.objects.create(name="Shoes")
    Product.objects.create(name="Red Sneakers", price=45000, stock=1, category=shoes, tags="viatu")
    Product.objects.create(name="Blue Shirt", price=15000, stock=0)
    client = APIClient()
    assert client.get("/api/products/?search=viatu").data["count"] == 1
    assert client.get("/api/products/?max_price=20000").data["count"] == 1
    assert client.get("/api/products/?in_stock=true").data["count"] == 1
    assert client.get("/api/products/?category=shoes").data["count"] == 1


@pytest.mark.django_db
def test_low_stock_report(admin_client):
    Product.objects.create(name="Almost gone", price=100, stock=2, low_stock_threshold=5)
    Product.objects.create(name="Plenty", price=100, stock=50)
    res = admin_client.get("/api/products/low_stock/")
    assert [p["name"] for p in res.data] == ["Almost gone"]
