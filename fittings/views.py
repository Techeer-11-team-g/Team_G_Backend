from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from .models import FittingImage
from .tasks import process_fitting_task

class FittingRequestView(APIView):
    """
    사용자의 가상 피팅 요청을 처리하여 Celery 비동기 작업을 시작합니다.
    """
    def post(self, request):
        # 1. 프론트엔드에서 보낸 ID 값들을 가져옵니다.
        user_image_id = request.data.get('user_image_id')
        product_id = request.data.get('product_id')
        category = request.data.get('category', 'top') # 기본값은 top

        # 데이터 유효성 검사
        if not user_image_id or not product_id:
            return Response(
                {"error": "user_image_id와 product_id가 모두 필요합니다."},
                status=status.HTTP_400_BAD_REQUEST
            )

        # 2. FittingImage 레코드를 생성합니다. (상태는 자동으로 'pending'이 됩니다)
        # 실제 모델의 필드명이 user_image, product 인지 확인이 필요할 수 있습니다.
        try:
            fitting = FittingImage.objects.create(
                user_image_id=user_image_id,
                product_id=product_id,
                category=category,
                fitting_image_status='pending'
            )

            # 3. Celery 태스크를 호출합니다 (.delay를 써야 비동기로 넘어갑니다)
            process_fitting_task.delay(fitting.id)

            # 4. 성공 응답을 보냅니다 (202 Accepted: 접수는 됐지만 처리는 나중에 됨)
            return Response({
                "message": "가상 피팅 요청이 성공적으로 접수되었습니다.",
                "fitting_id": fitting.id,
                "status": fitting.fitting_image_status
            }, status=status.HTTP_202_ACCEPTED)

        except Exception as e:
            return Response(
                {"error": f"요청 처리 중 오류가 발생했습니다: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )