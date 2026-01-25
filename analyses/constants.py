"""
analyses 앱 상수 정의 모듈.

카테고리 매핑, 검색 설정, 이미지 처리 설정 등
여러 파일에서 공통으로 사용하는 상수들을 중앙화합니다.
"""

# =============================================================================
# 카테고리 매핑
# =============================================================================

# Vision API 카테고리 → OpenSearch 카테고리 매핑
CATEGORY_MAPPING = {
    'bottom': 'pants',
    'outerwear': 'outer',
}

# LangChain 출력값 → DB 카테고리 alias 매핑
CATEGORY_ALIASES = {
    'pants': ['pants', 'bottom', '하의', '바지'],
    'bottom': ['pants', 'bottom', '하의', '바지'],
    'top': ['top', '상의', '티셔츠', '셔츠'],
    'outer': ['outer', 'outerwear', '아우터', '자켓', '코트'],
    'outerwear': ['outer', 'outerwear', '아우터', '자켓', '코트'],
    'shoes': ['shoes', '신발', '운동화', '스니커즈', '구두', '부츠', '샌들', '슬리퍼', '로퍼'],
    'bag': ['bag', '가방', '백팩', '토트백', '크로스백'],
    'dress': ['dress', '원피스', '드레스'],
    'skirt': ['skirt', '치마', '스커트'],
}

# FashionCLIP 텍스트 임베딩용 카테고리 설명
CATEGORY_DESCRIPTIONS = {
    'top': 'top shirt',
    'pants': 'pants trousers',
    'outer': 'jacket coat outerwear',
    'shoes': 'shoes sneakers boots heels',
    'bag': 'bag backpack',
    'dress': 'dress one-piece',
    'skirt': 'skirt',
}


# =============================================================================
# 검색 설정
# =============================================================================

class SearchConfig:
    """OpenSearch 검색 관련 설정"""
    K = 30                    # 최종 반환할 검색 결과 수
    SEARCH_K = 400            # 초기 벡터 검색 후보 수
    RERANK_TOP_K = 10         # 리랭킹 대상 수
    FINAL_RESULTS = 5         # 최종 매핑 저장 수
    REFINE_SEARCH_K = 50      # 재분석 시 검색 결과 수
    REFINE_CANDIDATES = 100   # 재분석 시 초기 후보 수


class RerankerConfig:
    """하이브리드 리랭킹 가중치 설정"""
    VISUAL_WEIGHT = 0.70      # 시각적 유사도 (코사인)
    OPENSEARCH_WEIGHT = 0.15  # k-NN 점수
    ATTRIBUTE_WEIGHT = 0.15   # 브랜드/색상 매칭
    USE_HYBRID = True         # 하이브리드 리랭킹 사용 여부 (False면 Claude 폴백)


# =============================================================================
# 이미지 처리 설정
# =============================================================================

class ImageConfig:
    """이미지 처리 관련 설정"""
    JPEG_QUALITY = 95         # JPEG 저장 품질
    BBOX_PADDING_RATIO = 0.25 # bbox 크롭 시 패딩 비율
    MAX_FILE_SIZE_MB = 10     # 최대 업로드 파일 크기
    ALLOWED_CONTENT_TYPES = ['image/jpeg', 'image/png', 'image/webp']


# =============================================================================
# 타임아웃 설정
# =============================================================================

class TimeoutConfig:
    """외부 API 호출 타임아웃 설정"""
    HTTP_TIMEOUT = 30         # 일반 HTTP 요청
    CELERY_TASK_TIMEOUT = 60  # Celery 태스크 대기
    LANGCHAIN_TIMEOUT = 30    # LangChain 파싱
    REFINE_TIMEOUT = 300      # 재분석 전체 타임아웃 (5분)


# =============================================================================
# 속성 필터 규칙
# =============================================================================

# (필터키, 결과키, 매칭타입)
ATTRIBUTE_FILTER_RULES = [
    ('color_filter', 'colors', 'list_contains'),
    ('brand_filter', 'brand', 'contains'),
    ('pattern_filter', 'pattern', 'exact'),
    ('style_vibe', 'style_vibe', 'exact'),
    ('sleeve_length', 'sleeve_length', 'exact'),
    ('material_filter', 'materials', 'list_contains'),
]
