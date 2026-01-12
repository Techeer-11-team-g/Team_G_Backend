from rest_framework import viewsets, status, permissions
from rest_framework.response import Response
from .models import Order
from .serializers import OrderCreateSerializer, OrderSerializer

class OrderViewSet(viewsets.GenericViewSet):
    permission_classes = [permissions.IsAuthenticated]
    
    def get_queryset(self):
        return Order.objects.filter(user=self.request.user, is_deleted=False)

    def get_serializer_class(self):
        if self.action == 'create':
            return OrderCreateSerializer
        return OrderSerializer

    def create(self, request, *args, **kwargs):
        """
        주문 생성 API
        """
        serializer = self.get_serializer(data=request.data, context={'request': request})
        serializer.is_valid(raise_exception=True)
        order = serializer.save()
        
        # Response(201 Created) body construction handled by serializer.to_representation
        return Response(serializer.data, status=status.HTTP_201_CREATED)
