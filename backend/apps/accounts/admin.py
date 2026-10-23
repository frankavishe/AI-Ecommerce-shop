from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from .models import Address, RiderProfile, User


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    list_display = ["username", "phone", "role", "whatsapp_verified", "is_active"]
    list_filter = ["role", "whatsapp_verified", "is_active"]
    search_fields = ["username", "phone", "email", "first_name", "last_name"]
    fieldsets = BaseUserAdmin.fieldsets + (
        ("Shop", {"fields": ("role", "phone", "whatsapp_verified", "preferred_language")}),
    )


admin.site.register(Address)
admin.site.register(RiderProfile)
