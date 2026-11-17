from django.apps import AppConfig


class DeliveryConfig(AppConfig):
    name = "apps.delivery"
    label = "delivery"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self):
        from . import notifications, services, signals  # noqa: F401  (signals: the OrderEvent receiver)

        if notifications.deliver_notices not in services.NOTIFY_HOOKS:
            services.NOTIFY_HOOKS.append(notifications.deliver_notices)
