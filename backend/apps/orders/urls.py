from django.urls import path

from . import views

urlpatterns = [
    path("cart/", views.CartView.as_view()),
    path("cart/items/", views.CartItemsView.as_view()),
    path("cart/items/<int:product_id>/", views.CartItemDetailView.as_view()),
    path("checkout/", views.CheckoutView.as_view()),
    path("delivery-regions/", views.DeliveryRegionListView.as_view()),
]
