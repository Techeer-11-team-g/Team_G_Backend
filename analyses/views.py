from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import AllowAny
from rest_framework.parsers import MultiPartParser, FormParser

from .models import UploadedImage
from .serializers import (
    UploadedImageCreateSerializer,
    UploadedImageResponseSerializer,
    UploadedImageListSerializer,
)


class UploadedImageView(APIView):
    """
    이미지 업로드 API
    
    POST /api/v1/uploaded-images - 이미지 업로드
    GET /api/v1/uploaded-images - 업로드 이력 조회
    """
    parser_classes = [MultiPartParser, FormParser]
    permission_classes = [AllowAny]  # 일단 누구나 접근 가능하게

    def post(self, request):
        """
        이미지 업로드
        Request: multipart/form-data { file: 이미지 }
        Response 201: { uploaded_image_id, uploaded_image_url, created_at }
        """
        serializer = UploadedImageCreateSerializer(
            data=request.data,
            context={'request': request}
        )

        if not serializer.is_valid():
            return Response(
                {'error': serializer.errors},
                status=status.HTTP_400_BAD_REQUEST
            )

        uploaded_image = serializer.save()

        response_serializer = UploadedImageResponseSerializer(uploaded_image)
        return Response(
            response_serializer.data,
            status=status.HTTP_201_CREATED
        )

    def get(self, request):
        """
        업로드 이미지 이력 조회
        Query Params: cursor (페이지네이션), limit (기본 10)
        Response 200: { items: [...], next_cursor }
        """
        # Query parameters
        cursor = request.query_params.get('cursor')
        limit = int(request.query_params.get('limit', 10))

        # 삭제되지 않은 이미지만 조회
        queryset = UploadedImage.objects.filter(is_deleted=False)

        # cursor가 있으면 그 이후부터 조회
        if cursor:
            queryset = queryset.filter(id__lt=cursor)

        # limit + 1개 조회 (다음 페이지 있는지 확인용)
        images = queryset.order_by('-id')[:limit + 1]
        images = list(images)

        # 다음 페이지 존재 여부 확인
        has_next = len(images) > limit
        if has_next:
            images = images[:limit]  # 실제로는 limit개만 반환

        # 다음 cursor 계산
        next_cursor = None
        if has_next and images:
            next_cursor = images[-1].id

        serializer = UploadedImageListSerializer(images, many=True)

        return Response({
            'items': serializer.data,
            'next_cursor': next_cursor
        })