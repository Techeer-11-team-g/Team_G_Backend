"""
Celery Tasks for Image Analysis Pipeline.

비동기 처리:
- RabbitMQ: 메시지 브로커로 태스크 큐잉
- Celery Group: 여러 객체를 병렬로 처리
- Redis: 진행 상태 및 결과 캐싱
"""

# Upload tasks
from .upload import upload_image_to_gcs_task

# Analysis tasks
from .analysis import (
    process_image_analysis,
    process_single_item,
    analysis_complete_callback,
    process_detected_item_task,
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

__all__ = [
    # Upload
    'upload_image_to_gcs_task',
    # Analysis
    'process_image_analysis',
    'process_single_item',
    'analysis_complete_callback',
    'process_detected_item_task',
    # Refine
    'parse_refine_query_task',
    'process_refine_analysis',
    'refine_single_object',
    'refine_analysis_complete',
    # Fitting
    'process_virtual_fitting',
]
