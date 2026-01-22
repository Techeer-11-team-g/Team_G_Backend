"""
OpenSearch 검색 유틸리티 및 상수 정의.

색상, 카테고리, 아이템 타입 매핑 등 검색에 필요한 공통 상수를 정의합니다.
"""


# Related categories that can be matched together
# 정확도를 위해 각 카테고리는 자기 자신만 매칭
RELATED_CATEGORIES = {
    'top': ['top'],
    'outer': ['outer'],
    'pants': ['pants'],
    'bottom': ['pants'],  # bottom은 pants로 매핑
    'dress': ['dress'],
    'skirt': ['dress'],  # skirt는 dress로 매핑
    'shoes': ['shoes'],
    'bag': ['bag'],
    'hat': ['hat'],
}


# 충돌 색상 매핑 (black 검색 시 white 제외 등)
CONFLICTING_COLORS = {
    'black': ['화이트', 'white', '흰'],
    'white': ['블랙', 'black', '검정'],
    'navy': ['화이트', 'white'],
    'navy blue': ['화이트', 'white'],
    'blue': ['레드', 'red', '핑크', 'pink'],
    'red': ['블루', 'blue', '그린', 'green'],
}


# 색상 키워드 매핑 (GPT-4V 출력 → 한글/영문 검색어)
COLOR_KEYWORDS = {
    'black': ['블랙', 'black', '검정', '검은'],
    'white': ['화이트', 'white', '흰', '백색', '아이보리', 'ivory'],
    'navy': ['네이비', 'navy', '남색'],
    'navy blue': ['네이비', 'navy', '남색', '인디고', 'indigo', '블루', 'blue', '로얄', 'royal'],
    'blue': ['블루', 'blue', '파랑', '파란'],
    'red': ['레드', 'red', '빨강', '빨간'],
    'green': ['그린', 'green', '녹색', '초록'],
    'yellow': ['옐로우', 'yellow', '노랑', '노란'],
    'pink': ['핑크', 'pink', '분홍'],
    'orange': ['오렌지', 'orange', '주황'],
    'purple': ['퍼플', 'purple', '보라'],
    'brown': ['브라운', 'brown', '갈색'],
    'gray': ['그레이', 'gray', 'grey', '회색'],
    'grey': ['그레이', 'gray', 'grey', '회색'],
    'beige': ['베이지', 'beige', '크림', 'cream'],
    'khaki': ['카키', 'khaki', '올리브', 'olive'],
    'dark brown': ['다크브라운', 'dark brown', '진갈색', '브라운'],
    'light blue': ['라이트블루', 'light blue', '스카이', 'sky', '연청'],
}


# 아이템 타입별 검색 키워드 및 제외 키워드
ITEM_TYPE_KEYWORDS = {
    'sneakers': {
        'include': ['스니커즈', 'sneaker', '운동화'],
        'exclude': ['슬리퍼', '슬라이드', 'slide', '샌들', 'sandal', '로퍼', 'loafer',
                   '아딜렛', 'adilette', '뮬', 'mule', '클로그', 'clog', '슈퍼노바',
                   '아디폼', 'adiform', '아디케인', 'adikane']
    },
    'shoes': {  # Haiku가 반환하는 일반적인 값 - sneakers와 동일하게 처리
        'include': ['스니커즈', 'sneaker', '운동화'],
        'exclude': ['슬리퍼', '슬라이드', 'slide', '샌들', 'sandal', '로퍼', 'loafer',
                   '아딜렛', 'adilette', '뮬', 'mule', '클로그', 'clog', '슈퍼노바',
                   '아디폼', 'adiform', '아디케인', 'adikane']
    },
    'slides': {
        'include': ['슬라이드', 'slide', '슬리퍼'],
        'exclude': ['스니커즈', 'sneaker', '운동화', '부츠']
    },
    'boots': {
        'include': ['부츠', 'boots', '워커'],
        'exclude': ['스니커즈', '슬리퍼', '샌들']
    },
    'loafers': {
        'include': ['로퍼', 'loafer'],
        'exclude': ['스니커즈', '슬리퍼', '부츠']
    },
    'track jacket': {
        'include': ['트랙', 'track', '져지', 'jersey'],
        'exclude': ['셔츠', '티셔츠']
    },
    'jacket': {  # Haiku가 반환하는 일반적인 값
        'include': ['자켓', 'jacket', '트랙', 'track'],
        'exclude': ['셔츠', '티셔츠', '팬츠', 'pants']
    },
    'hoodie': {
        'include': ['후드', 'hoodie', '후디'],
        'exclude': ['셔츠', '자켓']
    },
}


# Default k-NN settings for index creation
KNN_INDEX_SETTINGS = {
    'settings': {
        'index': {
            'knn': True,
            'knn.algo_param.ef_search': 100,
        },
        'number_of_shards': 1,
        'number_of_replicas': 0,
    },
    'mappings': {
        'properties': {
            'product_id': {'type': 'keyword'},
            'embedding': {
                'type': 'knn_vector',
                'dimension': 512,  # CLIP clip-vit-base-patch32
                'method': {
                    'name': 'hnsw',
                    'space_type': 'cosinesimil',
                    'engine': 'nmslib',
                    'parameters': {
                        'ef_construction': 128,
                        'm': 16,
                    }
                }
            },
            'category': {'type': 'keyword'},
            'brand': {'type': 'keyword'},
            'created_at': {'type': 'date'},
        }
    }
}


def get_related_categories(category: str) -> list:
    """카테고리에 대한 관련 카테고리 목록 반환."""
    return RELATED_CATEGORIES.get(category, [category])


def get_conflicting_colors(color: str) -> list:
    """특정 색상 검색 시 제외할 색상 목록 반환."""
    if not color:
        return []
    return CONFLICTING_COLORS.get(color.lower(), [])


def get_color_keywords(color: str) -> list:
    """색상에 대한 검색 키워드 목록 반환."""
    if not color:
        return []
    return COLOR_KEYWORDS.get(color.lower(), [color])


def get_item_type_config(item_type: str) -> dict:
    """아이템 타입에 대한 포함/제외 키워드 설정 반환."""
    if not item_type:
        return {'include': [], 'exclude': []}
    return ITEM_TYPE_KEYWORDS.get(item_type.lower(), {'include': [], 'exclude': []})


def parse_search_result(hit: dict) -> dict:
    """
    OpenSearch 검색 결과 hit을 표준 형식으로 변환.

    Args:
        hit: OpenSearch hit 객체

    Returns:
        표준화된 상품 정보 dict
    """
    src = hit['_source']
    attributes = src.get('attributes', {})

    return {
        'product_id': src.get('itemId'),
        'score': hit.get('_score', 0.0),
        'category': src.get('category'),
        'brand': src.get('brand'),
        'name': src.get('productName'),
        'image_url': src.get('imageUrl'),
        'price': src.get('price'),
        'product_url': src.get('productUrl'),
        'colors': attributes.get('colors', []),
        'pattern': attributes.get('pattern'),
        'style_vibe': attributes.get('style_vibe'),
        'sleeve_length': attributes.get('sleeve_length'),
        'pants_length': attributes.get('pants_length'),
        'outer_length': attributes.get('outer_length'),
        'materials': attributes.get('materials', []),
    }
