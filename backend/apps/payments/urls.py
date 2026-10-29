from django.urls import path

from .views import ClickPesaWebhookView

urlpatterns = [
    path("clickpesa/webhook/", ClickPesaWebhookView.as_view()),
]
