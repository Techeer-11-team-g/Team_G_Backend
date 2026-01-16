from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import OrderViewSet, CartItemListCreateView, CartItemDeleteView

router = DefaultRouter()
router.register('orders', OrderViewSet, basename='order')

urlpatterns = [
    path('', include(router.urls)),
    path('cart-items', CartItemListCreateView.as_view(), name='cart-item-list-create'),
    path('cart-items/<int:cart_item_id>', CartItemDeleteView.as_view(), name='cart-item-delete'),
] 