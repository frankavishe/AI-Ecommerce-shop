from django.apps import AppConfig


class WhatsappConfig(AppConfig):
    name = "apps.whatsapp"
    label = "whatsapp"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self):
        from . import notifications  # noqa: F401  (connects the OrderEvent receiver)
