"""Idempotent e2e seed. Run from backend/:  python manage.py shell -c "exec(open('../web/e2e/seed.py').read())"

Resets stock/prices on every run so tests start from the same state.
"""
from decimal import Decimal
from io import BytesIO

from django.core.files.base import ContentFile
from PIL import Image

from apps.accounts.models import User
from apps.catalog.models import Category, Product, ProductImage
from apps.orders.models import DeliveryRegion

PASSWORD = "e2e-pass-123"


def png(color):
    buf = BytesIO()
    Image.new("RGB", (600, 600), color).save(buf, "PNG")
    return ContentFile(buf.getvalue())


shoes, _ = Category.objects.update_or_create(slug="e2e-shoes", defaults={"name": "Shoes", "name_sw": "Viatu", "is_active": True})
kitchen, _ = Category.objects.update_or_create(slug="e2e-kitchen", defaults={"name": "Kitchen", "name_sw": "Jikoni", "is_active": True})

PRODUCTS = [
    # slug, name, category, price, compare_at, stock, colour, description_sw
    ("e2e-red-sneakers", "Red Sneakers", shoes, "45000", "52000", 20, (200, 40, 40), "Viatu vyekundu vya michezo."),
    ("e2e-leather-sandals", "Leather Sandals", shoes, "28000", None, 15, (140, 90, 50), "Ndala za ngozi."),
    ("e2e-running-shoes", "Running Shoes", shoes, "60000", None, 10, (40, 90, 200), ""),
    ("e2e-cooking-pot", "Cooking Pot", kitchen, "35000", None, 12, (90, 90, 90), "Sufuria ya kupikia."),
    ("e2e-thermos-flask", "Thermos Flask", kitchen, "18000", "21000", 25, (30, 140, 110), "Chupa ya chai."),
    ("e2e-wooden-spoons", "Wooden Spoons", kitchen, "6000", None, 2, (180, 150, 90), "Miiko ya mbao."),
    ("e2e-sold-out-kettle", "Sold Out Kettle", kitchen, "40000", None, 0, (220, 200, 40), ""),
]

for slug, name, category, price, compare_at, stock, colour, desc_sw in PRODUCTS:
    product, created = Product.objects.update_or_create(
        slug=slug,
        defaults={
            "name": name,
            "category": category,
            "price": Decimal(price),
            "compare_at_price": Decimal(compare_at) if compare_at else None,
            "stock": stock,
            "low_stock_threshold": 3,
            "description": f"{name} for everyday use.",
            "description_sw": desc_sw,
            "tags": "e2e",
            "is_active": True,
        },
    )
    if not product.images.exists():
        image = ProductImage(product=product, position=0, alt_text=name)
        image.image.save(f"{slug}.png", png(colour), save=True)

for name, fee in [("Dar es Salaam", "3000"), ("Arusha", "8000")]:
    DeliveryRegion.objects.update_or_create(name=name, defaults={"fee": Decimal(fee), "is_active": True})


def user(username, role, **extra):
    u, _ = User.objects.get_or_create(username=username, defaults={"role": role, **extra})
    u.role = role
    for key, value in extra.items():
        setattr(u, key, value)
    u.set_password(PASSWORD)
    u.save()
    return u


user("e2e_customer", User.Role.CUSTOMER, first_name="Amina", last_name="Juma", phone="+255754000111", email="amina@example.com")
user("e2e_admin", User.Role.ADMIN, first_name="Admin", is_staff=True)
user("e2e_rider", User.Role.RIDER, first_name="Rider")
print("e2e seed ok")
