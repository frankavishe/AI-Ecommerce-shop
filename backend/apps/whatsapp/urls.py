from django.urls import path

from . import views

app_name = "whatsapp"

urlpatterns = [
    path("webhook/", views.WebhookView.as_view(), name="webhook"),
    path("link/", views.LinkView.as_view(), name="link"),
    path("link/code/", views.LinkCodeView.as_view(), name="link-code"),
    path("admin/conversations/<uuid:pk>/reply/", views.StaffReplyView.as_view(), name="staff-reply"),
    path("admin/outbound/", views.OutboundListView.as_view(), name="outbound-list"),
]
