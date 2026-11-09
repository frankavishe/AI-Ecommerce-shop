from django.urls import path
from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter(trailing_slash=True)
router.include_root_view = False
router.register("admin/orders", views.AdminOrderViewSet, basename="admin-order")
router.register("admin/delivery-regions", views.AdminDeliveryRegionViewSet, basename="admin-region")

urlpatterns = router.urls + [
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
