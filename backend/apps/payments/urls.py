from django.urls import path

from .views import StakabaWebhookView

urlpatterns = [
    path("stakaba/webhook/<str:token>/", StakabaWebhookView.as_view()),
]
