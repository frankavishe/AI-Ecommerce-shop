from django.urls import path

from . import views

urlpatterns = [
    path("cart/", views.CartView.as_view()),
    path("cart/items/", views.CartItemsView.as_view()),
    path("cart/items/<int:product_id>/", views.CartItemDetailView.as_view()),
    path("cart/merge/", views.CartMergeView.as_view()),
    path("checkout/", views.CheckoutView.as_view()),
    path("orders/", views.OrderListView.as_view()),
    path("orders/lookup/", views.OrderLookupView.as_view()),
    path("orders/<str:number>/", views.OrderDetailView.as_view()),
    path("orders/<str:number>/pay/", views.OrderPayView.as_view()),
    path("delivery-regions/", views.DeliveryRegionListView.as_view()),
]
