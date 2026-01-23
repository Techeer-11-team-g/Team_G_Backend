"""
Celery Tasks for Image Analysis Pipeline.

비동기 처리:
- RabbitMQ: 메시지 브로커로 태스크 큐잉
- Celery Group: 여러 객체를 병렬로 처리
- Redis: 진행 상태 및 결과 캐싱

모듈 구조 (리팩토링 완료):
- storage.py: GCS 업로드/다운로드 유틸리티
- image_processing.py: 이미지 크롭/변환 유틸리티
- db_operations.py: DB 저장/조회 유틸리티
- analysis.py: 메인 분석 파이프라인
- refine.py: 자연어 기반 재분석
- fitting.py: 가상 피팅
- upload.py: 이미지 업로드
"""

# Upload tasks
from .upload import upload_image_to_gcs_task

# Analysis tasks
from .analysis import (
    process_image_analysis,
    process_single_item,
    analysis_complete_callback,
    process_detected_item_task,
    extract_style_tags_task,
)

# Refine tasks
from .refine import (
    parse_refine_query_task,
    process_refine_analysis,
    refine_single_object,
    refine_analysis_complete,
)

# Fitting tasks
from .fitting import process_virtual_fitting

# Utility modules (for internal use)
from .storage import (
    download_image,
    upload_cropped_image,
    upload_cropped_image_with_span,
)
from .image_processing import (
    crop_image,
    crop_image_from_dict,
    normalize_result_bbox,
    resize_image_if_needed,
)
from .db_operations import (
    update_analysis_status_db,
    save_analysis_results,
    update_metrics_on_success,
    update_metrics_on_failure,
)

__all__ = [
    # Upload
    'upload_image_to_gcs_task',
    # Analysis
    'process_image_analysis',
    'process_single_item',
    'analysis_complete_callback',
    'process_detected_item_task',
    'extract_style_tags_task',
    # Refine
    'parse_refine_query_task',
    'process_refine_analysis',
    'refine_single_object',
    'refine_analysis_complete',
    # Fitting
    'process_virtual_fitting',
    # Storage utilities
    'download_image',
    'upload_cropped_image',
    'upload_cropped_image_with_span',
    # Image processing utilities
    'crop_image',
    'crop_image_from_dict',
    'normalize_result_bbox',
    'resize_image_if_needed',
    # DB operations
    'update_analysis_status_db',
    'save_analysis_results',
    'update_metrics_on_success',
    'update_metrics_on_failure',
]
