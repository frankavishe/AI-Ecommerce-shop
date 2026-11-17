from django.apps import AppConfig


class DeliveryConfig(AppConfig):
    name = "apps.delivery"
    label = "delivery"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self):
        from apps.whatsapp import processing

        from . import notifications, rider_commands, rider_tools, riders, services, signals  # noqa: F401  (registrations)

        if notifications.deliver_notices not in services.NOTIFY_HOOKS:
            services.NOTIFY_HOOKS.append(notifications.deliver_notices)
        if riders.resolve_rider not in processing.ROLE_RESOLVERS:
            processing.ROLE_RESOLVERS.append(riders.resolve_rider)
        if riders.rider_stop_control not in processing.CONTROL_HANDLERS:
            processing.CONTROL_HANDLERS.insert(0, riders.rider_stop_control)
        if rider_commands.control not in processing.CONTROL_HANDLERS:
            at = processing.CONTROL_HANDLERS.index(riders.rider_stop_control) + 1
            processing.CONTROL_HANDLERS.insert(at, rider_commands.control)
