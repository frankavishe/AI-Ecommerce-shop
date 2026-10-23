from django.contrib.auth.models import AbstractUser, UserManager
from django.core.validators import RegexValidator
from django.db import models

phone_validator = RegexValidator(
    r"^\+[1-9]\d{7,14}$", "Phone must be in international format, e.g. +255712345678."
)


class User(AbstractUser):
    class Role(models.TextChoices):
        CUSTOMER = "customer", "Customer"
        ADMIN = "admin", "Admin"
        RIDER = "rider", "Rider"

    role = models.CharField(max_length=16, choices=Role.choices, default=Role.CUSTOMER)
    phone = models.CharField(
        max_length=16, unique=True, null=True, blank=True, validators=[phone_validator]
    )
    whatsapp_verified = models.BooleanField(default=False)
    preferred_language = models.CharField(
        max_length=2, choices=[("sw", "Swahili"), ("en", "English")], default="sw"
    )

    objects = UserManager()

    @property
    def is_shop_admin(self):
        return self.role == self.Role.ADMIN or self.is_superuser

    @property
    def is_rider(self):
        return self.role == self.Role.RIDER


class Address(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="addresses")
    label = models.CharField(max_length=50, default="Home")
    region = models.CharField(max_length=80)
    district = models.CharField(max_length=80, blank=True)
    street = models.CharField(max_length=255)
    latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    is_default = models.BooleanField(default=False)

    def __str__(self):
        return f"{self.label}: {self.street}, {self.region}"


class RiderProfile(models.Model):
    class Vehicle(models.TextChoices):
        MOTORBIKE = "motorbike", "Motorbike (bodaboda)"
        BICYCLE = "bicycle", "Bicycle"
        CAR = "car", "Car"
        BAJAJI = "bajaji", "Bajaji"

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="rider_profile")
    vehicle = models.CharField(max_length=16, choices=Vehicle.choices, default=Vehicle.MOTORBIKE)
    plate_number = models.CharField(max_length=20, blank=True)
    zone = models.CharField(max_length=80, blank=True, help_text="Area the rider covers")
    is_available = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Rider {self.user.get_full_name() or self.user.username}"
