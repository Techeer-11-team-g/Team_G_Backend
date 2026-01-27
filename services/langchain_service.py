"""
LangChain service configuration.

LangChain 네이티브 리팩토링:
- Pydantic 스키마 → Function Calling JSON Schema 자동 생성
- Chain 합성 (prompt | llm | parser) 파이프라인
- 모델 교체 용이 (ChatOpenAI → ChatAnthropic 한 줄 변경)
"""

import json
import logging
from typing import Optional, List, Literal

from django.conf import settings
from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers.openai_functions import PydanticOutputFunctionsParser
from langchain_core.utils.function_calling import convert_pydantic_to_openai_function
from langchain.schema import AIMessage, HumanMessage, SystemMessage
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


# =============================================================================
# Pydantic 스키마 정의 (Function Calling JSON Schema 자동 생성)
# =============================================================================

class FashionIntent(BaseModel):
    """사용자 메시지의 의도를 분류합니다"""

    intent: Literal["search", "fitting", "commerce", "general"] = Field(
        description="주요 의도"
    )
    sub_intent: Literal[
        "new_search", "retry_search", "refine", "similar", "cross_recommend",
        "single_fit", "batch_fit", "compare_fit",
        "add_cart", "direct_purchase", "view_cart", "remove_cart", "size_recommend", "checkout",
        "greeting", "help", "feedback", "unknown"
    ] = Field(description="세부 의도")
    target_categories: Optional[List[str]] = Field(
        default=None, description="대상 카테고리 목록 (shoes, top, bottom, outer, bag 등)"
    )
    item_type: Optional[Literal[
        "coat", "padding", "jacket", "cardigan", "jumper",
        "sneakers", "loafers", "boots", "sandals", "slippers",
        "tshirt", "shirt", "knit", "hoodie", "sweatshirt",
        "jeans", "slacks", "jogger", "shorts"
    ]] = Field(default=None, description="세부 아이템 타입")
    reference_type: Optional[Literal["index", "temporal", "none"]] = Field(
        default=None, description="참조 표현 유형"
    )
    reference_indices: Optional[List[int]] = Field(
        default=None, description="번호 참조 시 인덱스 목록"
    )
    reference_temporal: Optional[Literal["current", "last", "previous", "first"]] = Field(
        default=None, description="시간 참조 유형"
    )
    size: Optional[str] = Field(default=None, description="사이즈 정보 (S, M, L, XL, 95, 100 등)")
    color: Optional[str] = Field(default=None, description="색상 정보")
    brand: Optional[str] = Field(default=None, description="브랜드명 (영문 소문자)")
    pattern: Optional[Literal[
        "stripe", "polka_dot", "check", "solid", "floral", "paisley", "camo", "animal", "graphic", "argyle"
    ]] = Field(default=None, description="패턴/문양")
    style: Optional[Literal[
        "casual", "formal", "sporty", "vintage", "minimal", "street", "classic", "overfit", "slim"
    ]] = Field(default=None, description="스타일")
    material: Optional[Literal[
        "denim", "leather", "wool", "cotton", "linen", "velvet", "corduroy", "fur", "suede", "polyester", "silk"
    ]] = Field(default=None, description="소재")
    confidence: float = Field(description="분류 확신도 (0-1)")


class RefineRequest(BaseModel):
    """단일 패션 검색 요청"""

    target_categories: List[Literal[
        "top", "outer", "pants", "shoes", "bag", "dress", "skirt", "accessory"
    ]] = Field(description="대상 카테고리 (영문 소문자)")
    action: Literal["research", "filter", "change_style"] = Field(
        description="수행할 액션 유형"
    )
    color_filter: Optional[Literal[
        "black", "white", "navy", "blue", "red", "green", "gray", "beige", "brown",
        "pink", "yellow", "orange", "purple", "cream", "khaki"
    ]] = Field(default=None, description="색상 필터")
    pattern_filter: Optional[Literal[
        "solid", "stripe", "check", "floral", "graphic", "dot", "camo", "animal", "logo"
    ]] = Field(default=None, description="패턴 필터")
    style_vibe: Optional[Literal[
        "casual", "formal", "sporty", "vintage", "minimal", "streetwear", "luxury", "cute", "basic", "trendy"
    ]] = Field(default=None, description="스타일 분위기")
    sleeve_length: Optional[Literal["long_sleeve", "short_sleeve", "sleeveless"]] = Field(
        default=None, description="소매 길이 (top/outer용)"
    )
    pants_length: Optional[Literal["long", "shorts", "cropped"]] = Field(
        default=None, description="바지 길이"
    )
    outer_length: Optional[Literal["long", "regular", "cropped"]] = Field(
        default=None, description="아우터 길이"
    )
    material_filter: Optional[Literal[
        "leather", "denim", "cotton", "wool", "linen", "silk", "nylon", "polyester", "knit", "fleece"
    ]] = Field(default=None, description="소재 필터")
    brand_filter: Optional[str] = Field(default=None, description="브랜드명 (영문 소문자)")
    price_sort: Optional[Literal["lowest", "highest"]] = Field(
        default=None, description="가격 정렬"
    )
    fit_filter: Optional[Literal["slim", "regular", "oversized", "loose"]] = Field(
        default=None, description="핏 필터"
    )
    search_keywords: Optional[str] = Field(default=None, description="추가 검색 키워드")


class FashionQueryParsed(BaseModel):
    """사용자의 패션 검색 요청을 파싱한 결과"""

    requests: List[RefineRequest] = Field(description="파싱된 요청 리스트")
    understood_intent: str = Field(description="사용자 의도를 한 문장으로 요약")
    clarification_needed: bool = Field(default=False, description="추가 확인 필요 여부")
    clarification_question: Optional[str] = Field(default=None, description="필요시 사용자에게 물어볼 질문")


# =============================================================================
# 프롬프트 템플릿 (Chain 파이프라인용)
# =============================================================================

INTENT_SYSTEM_PROMPT = """당신은 한국어 패션 쇼핑 어시스턴트입니다.
사용자 메시지의 의도를 정확하게 분류하세요.

## 의도 분류 기준

### search (상품 검색)
- new_search: 새로운 검색 ("니트 찾아줘", "검은색 자켓 보여줘")
- retry_search: 이전 검색 반복 ("다시 검색해줘", "한번 더 찾아줘")
- refine: 검색 결과 조건 변경 또는 이미지 분석 결과 필터 변경
  예1: "더 싼 거", "다른 색으로", "브랜드 바꿔줘" (텍스트 검색 조건 변경)
  예2: "신발만 보여줘", "코트만 찾아줘", "상의만 볼래" (이미지 분석 필터 변경)
- similar: 비슷한 상품 찾기 ("비슷한 거 더 보여줘")

### fitting (가상 피팅)
- single_fit: 단일 상품 피팅 ("1번 입어볼래", "이거 피팅해줘")
- batch_fit: 여러 상품 피팅 ("다 입어봐", "전부 피팅")
- compare_fit: 피팅 비교 ("1번이랑 2번 비교해줘")

### commerce (구매/장바구니)
- add_cart: 장바구니에만 담기 (결제 안함)
  예: "1번 담아줘", "3번 장바구니에 넣어", "이거 담아", "저장해둬"
- direct_purchase: 바로 구매 (사이즈 선택 → 결제) - "구매", "살래", "살게" 표현!
  예: "1번 구매할래", "1번 살래", "이거 살게", "3번 구매", "1번 바로 주문"
- view_cart: 장바구니 보기 ("장바구니 보여줘", "뭐 담았어?")
- remove_cart: 장바구니 삭제 ("1번 빼줘", "장바구니 비워")
- size_recommend: 사이즈 추천 ("사이즈 추천해줘", "내 사이즈 뭐야?")
- checkout: 장바구니 전체 결제 - 번호 참조 없이!
  예: "결제해줘", "장바구니 결제", "전부 주문해줘"

### general (일반 대화)
- greeting: 인사 ("안녕", "하이")
- help: 도움 요청 ("뭐 할 수 있어?", "도와줘")
- feedback: 피드백 ("고마워", "좋아")
- unknown: 분류 불가

## 참조 표현 파싱
- index: 번호 참조 ("1번", "3번") → indices: [1], [3]
- temporal: 시간 참조 ("이거", "아까 그거") → temporal: "current", "previous"
- none: 참조 없음

## 카테고리 추출
- shoes: 신발, 구두, 운동화, 스니커즈, 부츠, 로퍼, 샌들, 슬리퍼
- top: 상의, 티셔츠, 셔츠, 니트, 맨투맨, 후드, 블라우스
- bottom/pants: 하의, 바지, 청바지, 슬랙스, 조거팬츠
- outer: 아우터, 자켓, 코트, 패딩, 가디건, 점퍼, 바람막이
- bag: 가방, 백팩, 토트백, 크로스백
- dress: 원피스, 드레스
- skirt: 치마, 스커트

## 아이템 타입 추출 (세부 분류)
카테고리 내 세부 아이템 타입은 **구체적인 아이템명이 있을 때만** 추출하세요.
"신발", "상의", "아우터" 같은 **일반적인 카테고리명은 item_type을 추출하지 마세요**.
- outer 세부: coat(코트/트렌치), padding(패딩/다운), jacket(자켓/재킷/블레이저), cardigan(가디건), jumper(점퍼/바람막이)
- shoes 세부: sneakers(운동화/스니커즈), loafers(구두/로퍼/옥스퍼드), boots(부츠/워커), sandals(샌들), slippers(슬리퍼)
- top 세부: tshirt(티셔츠), shirt(셔츠), knit(니트/스웨터), hoodie(후드/후드티), sweatshirt(맨투맨)
- bottom 세부: jeans(청바지/데님), slacks(슬랙스), jogger(조거팬츠), shorts(반바지)

## 브랜드 추출 (영문 소문자로)
나이키/nike → nike, 아디다스/adidas → adidas, 뉴발란스/new balance → newbalance,
자라/zara → zara, 유니클로/uniqlo → uniqlo, 커버낫/covernat → covernat,
디스이즈네버댓/thisisneverthat → thisisneverthat, 기타 브랜드도 영문 소문자로 변환

## 패턴/문양 추출
스트라이프/줄무늬 → stripe, 점박이/도트 → polka_dot, 체크/격자 → check,
무지/솔리드 → solid, 꽃무늬/플로럴 → floral, 카모/밀리터리 → camo,
호피/레오파드 → animal, 로고/그래픽 → graphic, 아가일/마름모 → argyle

## 스타일 추출
캐주얼/편한 → casual, 포멀/정장 → formal, 스포티/운동 → sporty,
빈티지/레트로 → vintage, 미니멀/심플 → minimal, 스트릿/힙합 → street,
클래식/정통 → classic, 오버핏/루즈 → overfit, 슬림핏/타이트 → slim

## 소재 추출
데님/청 → denim, 가죽/레더 → leather, 니트/울 → wool, 면/코튼 → cotton,
린넨/마 → linen, 벨벳 → velvet, 코듀로이 → corduroy, 퍼/털 → fur,
스웨이드 → suede, 폴리에스터 → polyester, 실크/비단 → silk"""

INTENT_USER_TEMPLATE = """사용자 메시지: "{message}"

현재 상태:
- 검색 결과 있음: {has_search_results}
- 사용자 이미지 있음: {has_user_image}
- 장바구니 아이템: {cart_count}개

분류 가이드:
- "나이키 신발 찾아줘", "아디다스 운동화 보여줘" 처럼 브랜드+아이템을 검색하는 건 new_search입니다.
- "신발만 보여줘", "상의만" 처럼 이전 결과에서 필터만 바꾸는 건 refine입니다.
- 브랜드가 있으면 반드시 brand 필드에 추출하세요 (나이키→nike, 아디다스→adidas, 뉴발란스→newbalance)

이 메시지의 의도를 분류해주세요."""

REFINE_SYSTEM_PROMPT = """당신은 한국어 패션 검색 어시스턴트입니다.
사용자의 패션 검색 요청을 정확하게 파싱합니다.

중요 규칙:
1. 사용자가 여러 요청을 한 번에 하면, 각각을 별도의 request로 파싱하세요.
   예: "상의는 검은색으로, 바지는 흰색으로" → 2개의 request
2. 이전 대화 문맥이 있으면 참고하세요. "아까 그거에서 색만 바꿔줘" 같은 요청 처리.
3. 모호한 요청은 clarification_needed=true로 설정하고 질문을 제안하세요.
4. 한국어를 영문 필터값으로 정확히 매핑하세요.

카테고리 매핑:
- 상의/티셔츠/셔츠/블라우스/맨투맨/후드티 → top
- 아우터/자켓/코트/가디건/점퍼/패딩/집업 → outer
- 하의/바지/청바지/슬랙스/조거팬츠/반바지 → pants
- 신발/운동화/스니커즈/부츠/샌들/슬리퍼/로퍼 → shoes
- 가방/백팩/토트백/크로스백/숄더백/클러치 → bag
- 원피스/드레스 → dress | 치마/스커트 → skirt

색상: 검은/블랙→black, 흰/화이트→white, 파란/블루→blue, 남색/네이비→navy,
빨간/레드→red, 회색/그레이→gray, 베이지→beige, 갈색/브라운→brown,
핑크→pink, 노란/옐로우→yellow, 초록/그린→green, 보라/퍼플→purple

패턴: 무지→solid, 줄무늬→stripe, 체크→check, 꽃무늬→floral,
그래픽→graphic, 도트→dot, 카모→camo, 애니멀→animal, 로고→logo

스타일: 캐주얼→casual, 포멀→formal, 스포티→sporty, 빈티지→vintage,
미니멀→minimal, 스트릿→streetwear, 럭셔리→luxury, 귀여운→cute

핏: 슬림→slim, 레귤러→regular, 오버사이즈→oversized, 루즈→loose

소재: 가죽→leather, 데님→denim, 면→cotton, 울→wool, 린넨→linen,
실크→silk, 나일론→nylon, 폴리에스터→polyester, 니트→knit, 플리스→fleece"""

REFINE_USER_TEMPLATE = """사용자 요청: "{query}"

현재 이미지에서 검출된 카테고리: {available_categories}

이 요청을 파싱해주세요."""


class LangChainService:
    """LangChain service for LLM operations."""

    def __init__(self, model: str = 'gpt-4o-mini', temperature: float = 0.7):
        """
        Initialize LangChain service.

        Args:
            model: OpenAI model name
            temperature: Sampling temperature
        """
        self.llm = ChatOpenAI(
            api_key=settings.OPENAI_API_KEY,
            model=model,
            temperature=temperature,
        )
        self.embeddings = OpenAIEmbeddings(
            api_key=settings.OPENAI_API_KEY,
        )

        # ── LangChain Chain 파이프라인 구성 ──
        # 분류/파싱용 LLM (낮은 temperature로 일관된 출력)
        self._structured_llm = ChatOpenAI(
            api_key=settings.OPENAI_API_KEY,
            model=model,
            temperature=0.1,
        )

        # Intent Classification Chain: prompt | llm | parser
        intent_fn = convert_pydantic_to_openai_function(FashionIntent)
        self._intent_parser = PydanticOutputFunctionsParser(pydantic_schema=FashionIntent)
        self._intent_llm = self._structured_llm.bind(
            functions=[intent_fn],
            function_call={"name": "FashionIntent"},
        )

        # Refine Query Parsing Chain: prompt | llm | parser
        refine_fn = convert_pydantic_to_openai_function(FashionQueryParsed)
        self._refine_parser = PydanticOutputFunctionsParser(pydantic_schema=FashionQueryParsed)
        self._refine_llm = self._structured_llm.bind(
            functions=[refine_fn],
            function_call={"name": "FashionQueryParsed"},
        )

    def chat(self, user_message: str, system_message: str = None) -> str:
        """
        Send a chat message and get response.

        Args:
            user_message: User's message
            system_message: Optional system prompt

        Returns:
            Assistant's response
        """
        messages = []
        if system_message:
            messages.append(SystemMessage(content=system_message))
        messages.append(HumanMessage(content=user_message))

        response = self.llm.invoke(messages)
        return response.content

    def chat_with_template(self, template: str, **kwargs) -> str:
        """
        Chat using a prompt template.

        Args:
            template: Prompt template string
            **kwargs: Template variables

        Returns:
            Assistant's response
        """
        prompt = ChatPromptTemplate.from_template(template)
        chain = prompt | self.llm
        response = chain.invoke(kwargs)
        return response.content

    def get_embedding(self, text: str) -> list[float]:
        """
        Get embedding vector for text.

        Args:
            text: Input text

        Returns:
            Embedding vector
        """
        return self.embeddings.embed_query(text)

    def get_embeddings(self, texts: list[str]) -> list[list[float]]:
        """
        Get embedding vectors for multiple texts.

        Args:
            texts: List of input texts

        Returns:
            List of embedding vectors
        """
        return self.embeddings.embed_documents(texts)

    def evaluate_search_result(
        self,
        category: str,
        confidence: float,
        match_score: float,
        product_id: str,
    ) -> dict:
        """
        Evaluate search result quality using LLM.

        Args:
            category: Detected item category
            confidence: Detection confidence
            match_score: k-NN search match score
            product_id: Matched product ID

        Returns:
            Evaluation result with quality and reason
        """
        prompt = f"""Evaluate this product search result quality:

Category: {category}
Detection Confidence: {confidence:.2f}
Match Score: {match_score:.4f}
Product ID: {product_id}

Based on these metrics, rate the match quality as:
- "high" if match_score > 0.85 and confidence > 0.7
- "medium" if match_score > 0.7 or confidence > 0.6
- "low" otherwise

Respond in JSON format:
{{"quality": "high/medium/low", "reason": "brief explanation"}}"""

        try:
            response = self.chat(prompt)
            # Try to extract JSON from response
            start = response.find('{')
            end = response.rfind('}') + 1
            if start >= 0 and end > start:
                return json.loads(response[start:end])
            return {'quality': 'unknown', 'reason': 'Could not parse response'}
        except Exception as e:
            return {'quality': 'unknown', 'reason': str(e)}

    def parse_refine_query(
        self,
        query: str,
        available_categories: list[str],
    ) -> dict:
        """
        Parse natural language query for result refinement.

        Args:
            query: User's natural language query (e.g., "바지를 검은 바지로 다시 찾아줘")
            available_categories: List of available categories from detected objects

        Returns:
            Parsed action with filters including color, brand, price
        """
        prompt = f"""다음 사용자 요청을 분석하여 이미지 분석 결과 재검색에 필요한 정보를 추출하세요.

사용자 요청: "{query}"

현재 검출된 객체 카테고리: {available_categories}

다음 JSON 형식으로 응답하세요:
{{
    "action": "research" | "filter" | "change_style",
    "target_categories": ["top", "pants" 등 대상 카테고리 - 영문 소문자 사용],
    "color_filter": "black" | "white" | "navy" | "blue" | "red" | "green" | "gray" | "beige" | "brown" | "pink" | "yellow" | "orange" | "purple" 등 (없으면 null),
    "pattern_filter": "solid" | "stripe" | "check" | "floral" | "graphic" | "dot" | "camo" | "animal" (없으면 null),
    "style_vibe": "casual" | "formal" | "sporty" | "vintage" | "minimal" | "streetwear" | "luxury" | "cute" (없으면 null),
    "sleeve_length": "long_sleeve" | "short_sleeve" | "sleeveless" (top/outer 카테고리용, 없으면 null),
    "pants_length": "long" | "shorts" | "cropped" (pants 카테고리용, 없으면 null),
    "outer_length": "long" | "regular" | "cropped" (outer 카테고리용, 없으면 null),
    "material_filter": "leather" | "denim" | "cotton" | "wool" 등 (없으면 null),
    "brand_filter": "nike" | "adidas" 등 브랜드명 영문 소문자 (없으면 null),
    "price_sort": "lowest" | "highest" (가격 정렬 요청시, 없으면 null)
}}

카테고리 매핑:
- "상의", "top", "티셔츠", "셔츠", "나시", "반팔", "긴팔" → "top"
- "아우터", "outer", "자켓", "코트", "가디건", "점퍼", "패딩", "집업" → "outer"
- "하의", "bottom", "바지", "pants", "청바지", "슬랙스", "반바지" → "pants"
- "신발", "shoes", "운동화", "스니커즈", "부츠", "샌들", "슬리퍼" → "shoes"
- "가방", "bag", "백팩", "토트백", "크로스백" → "bag"

색상 매핑:
- "검은", "검정", "블랙" → "black"
- "흰", "하얀", "화이트" → "white"
- "파란", "블루" → "blue"
- "빨간", "레드" → "red"
- "네이비", "남색" → "navy"
- "회색", "그레이" → "gray"
- "베이지" → "beige"

패턴 매핑:
- "무지", "단색" → "solid"
- "줄무늬", "스트라이프" → "stripe"
- "체크", "격자" → "check"
- "꽃무늬", "플로럴" → "floral"
- "그래픽", "프린트" → "graphic"
- "도트", "물방울" → "dot"
- "카모", "밀리터리" → "camo"

스타일 매핑:
- "캐주얼", "편한" → "casual"
- "포멀", "정장" → "formal"
- "스포티", "운동" → "sporty"
- "빈티지", "레트로" → "vintage"
- "미니멀", "심플" → "minimal"
- "스트릿", "힙한" → "streetwear"
- "럭셔리", "고급" → "luxury"
- "귀여운", "큐트" → "cute"

소매 길이 매핑:
- "긴팔" → "long_sleeve"
- "반팔" → "short_sleeve"
- "나시", "민소매", "슬리브리스" → "sleeveless"

바지 길이 매핑:
- "긴바지", "롱팬츠" → "long"
- "반바지", "숏팬츠", "숏츠" → "shorts"
- "크롭", "7부", "8부" → "cropped"

소재 매핑:
- "가죽", "레더" → "leather"
- "데님", "청" → "denim"
- "면", "코튼" → "cotton"
- "울", "모직" → "wool"
- "니트" → "wool"

예시:
- "바지를 검은 바지로 다시 찾아줘" → {{"action": "research", "target_categories": ["pants"], "color_filter": "black", ...}}
- "줄무늬 셔츠로 바꿔줘" → {{"action": "research", "target_categories": ["top"], "pattern_filter": "stripe", ...}}
- "캐주얼한 느낌으로" → {{"action": "change_style", "style_vibe": "casual", ...}}

JSON만 응답하세요."""

        try:
            response = self.chat(prompt, system_message="You are a Korean fashion search assistant. Always respond in valid JSON format only.")
            start = response.find('{')
            end = response.rfind('}') + 1
            if start >= 0 and end > start:
                result = json.loads(response[start:end])
                # 필수 필드 기본값 설정
                if 'target_categories' not in result or not result['target_categories']:
                    result['target_categories'] = available_categories
                if 'action' not in result:
                    result['action'] = 'research'
                # 새 필드 기본값
                result.setdefault('color_filter', None)
                result.setdefault('pattern_filter', None)
                result.setdefault('style_vibe', None)
                result.setdefault('sleeve_length', None)
                result.setdefault('pants_length', None)
                result.setdefault('outer_length', None)
                result.setdefault('material_filter', None)
                result.setdefault('brand_filter', None)
                result.setdefault('price_sort', None)
                logger.info(f"Parsed refine query: {result}")
                return result
        except Exception as e:
            logger.warning(f"Failed to parse refine query: {e}")

        return {
            'action': 'research',
            'target_categories': available_categories,
            'color_filter': None,
            'pattern_filter': None,
            'style_vibe': None,
            'sleeve_length': None,
            'pants_length': None,
            'outer_length': None,
            'material_filter': None,
            'brand_filter': None,
            'price_sort': None,
        }

    def refine_search_filters(
        self,
        category: str,
        initial_results: list[dict],
        user_preferences: dict = None,
    ) -> dict:
        """
        Use LLM to suggest refined search filters based on initial results.

        Args:
            category: Product category
            initial_results: Initial search results
            user_preferences: User's preferences (brand, price range, etc.)

        Returns:
            Suggested filter adjustments
        """
        prompt = f"""Analyze these product search results and suggest filter adjustments:

Category: {category}
Number of results: {len(initial_results)}
Top match score: {initial_results[0]['score'] if initial_results else 'N/A'}
User preferences: {user_preferences or 'None specified'}

If results quality is poor, suggest:
1. Should we broaden or narrow the category?
2. Should we adjust the number of results?
3. Any specific brand or style filters to add?

Respond in JSON format:
{{"adjust_category": true/false, "suggested_category": "...", "adjust_k": true/false, "suggested_k": 10, "filters": {{"brand": "...", "style": "..."}}}}"""

        try:
            response = self.chat(prompt)
            start = response.find('{')
            end = response.rfind('}') + 1
            if start >= 0 and end > start:
                return json.loads(response[start:end])
            return {}
        except Exception as e:
            return {'error': str(e)}


    def parse_refine_query_v2(
        self,
        query: str,
        available_categories: list[str],
        conversation_history: list[dict] = None,
        analysis_id: int = None,
    ) -> dict:
        """
        LangChain Chain 파이프라인을 사용한 향상된 쿼리 파싱.

        Pydantic 스키마 → JSON Schema 자동 변환 → Function Calling → 구조화된 출력

        주요 개선점:
        - 구조화된 출력 보장 (Pydantic + Function Calling)
        - 다중 요청 파싱 지원
        - 대화 히스토리 문맥 유지
        - 사용자 의도 피드백 제공

        Args:
            query: 사용자 자연어 쿼리
            available_categories: 가용 카테고리 목록
            conversation_history: 이전 대화 히스토리 (Redis에서 로드)
            analysis_id: 분석 ID (대화 문맥 저장용)

        Returns:
            {
                'requests': [...],  # 다중 요청 리스트
                'understood_intent': str,  # 이해한 의도 요약
                'clarification_needed': bool,
                'clarification_question': str | None
            }
        """
        try:
            # 메시지 구성 (대화 히스토리 포함)
            messages = [SystemMessage(content=REFINE_SYSTEM_PROMPT)]

            if conversation_history:
                for hist in conversation_history[-5:]:  # 최근 5개만
                    role = hist.get("role", "user")
                    content = hist.get("content", "")
                    if role == "assistant":
                        messages.append(AIMessage(content=content))
                    else:
                        messages.append(HumanMessage(content=content))

            # 현재 요청 추가
            user_content = REFINE_USER_TEMPLATE.format(
                query=query,
                available_categories=available_categories,
            )
            messages.append(HumanMessage(content=user_content))

            # LangChain Chain 실행: llm (bound) → parser
            ai_message = self._refine_llm.invoke(messages)
            result: FashionQueryParsed = self._refine_parser.invoke(ai_message)

            # Pydantic 객체 → dict 변환 (기존 인터페이스 유지)
            result_dict = result.model_dump()

            # requests 내 Pydantic 객체도 dict로 변환
            result_dict['requests'] = [
                req.model_dump(exclude_none=True) for req in result.requests
            ]

            # 대화 히스토리 저장 (Redis)
            if analysis_id:
                self._save_conversation_history(
                    analysis_id,
                    query,
                    result.understood_intent,
                )

            # 기본값 설정
            if not result_dict.get('requests'):
                result_dict['requests'] = [{
                    'action': 'research',
                    'target_categories': available_categories,
                }]

            logger.info(f"LangChain parsed: {len(result_dict['requests'])} requests")
            logger.info(f"Understood intent: {result_dict.get('understood_intent')}")

            return result_dict

        except Exception as e:
            logger.error(f"LangChain refine parsing failed: {e}")

        # 폴백: 기존 parse_refine_query 사용
        logger.info("Falling back to legacy parse_refine_query")
        legacy_result = self.parse_refine_query(query, available_categories)
        return {
            'requests': [legacy_result],
            'understood_intent': f"'{query}' 요청 처리",
            'clarification_needed': False,
        }

    def _save_conversation_history(
        self,
        analysis_id: int,
        user_query: str,
        assistant_response: str,
    ):
        """대화 히스토리를 Redis에 저장."""
        try:
            from services.redis_service import get_redis_service
            redis = get_redis_service()

            key = f"conversation:{analysis_id}"
            history = redis.get(key)

            if history:
                history = json.loads(history)
            else:
                history = []

            # 새 대화 추가
            history.append({"role": "user", "content": user_query})
            history.append({"role": "assistant", "content": assistant_response})

            # 최대 20개 유지
            if len(history) > 20:
                history = history[-20:]

            # 2시간 TTL로 저장 (연속 재분석 세션 유지용)
            from services.redis_service import RedisService
            redis.set(key, json.dumps(history, ensure_ascii=False), ttl=RedisService.TTL_CONVERSATION)
            logger.info(f"Saved conversation history for analysis {analysis_id}")

        except Exception as e:
            logger.warning(f"Failed to save conversation history: {e}")

    def get_conversation_history(self, analysis_id: int) -> list[dict]:
        """Redis에서 대화 히스토리 로드."""
        try:
            from services.redis_service import get_redis_service
            redis = get_redis_service()

            key = f"conversation:{analysis_id}"
            history = redis.get(key)

            if history:
                return json.loads(history)
        except Exception as e:
            logger.warning(f"Failed to load conversation history: {e}")

        return []

    def classify_intent(
        self,
        message: str,
        context: dict = None,
    ) -> dict:
        """
        사용자 메시지의 의도를 분류 (LangChain Chain 파이프라인).

        Pydantic 스키마 → JSON Schema 자동 변환 → Function Calling → 구조화된 출력

        Args:
            message: 사용자 메시지
            context: 세션 컨텍스트 (has_search_results, has_user_image 등)

        Returns:
            {
                'intent': 'search' | 'fitting' | 'commerce' | 'general',
                'sub_intent': str,
                'search_params': {...},
                'commerce_params': {...},
                'references': {...},
                'confidence': float
            }
        """
        try:
            # 컨텍스트 정보 정리
            ctx = context or {}
            has_search_results = ctx.get('has_search_results', False)
            has_user_image = ctx.get('has_user_image', False)
            cart_count = ctx.get('cart_item_count', 0)

            # LangChain Chain 구성: prompt | llm (bound) | parser
            prompt = ChatPromptTemplate.from_messages([
                ("system", INTENT_SYSTEM_PROMPT),
                ("human", INTENT_USER_TEMPLATE),
            ])

            chain = prompt | self._intent_llm | self._intent_parser

            # Chain 실행 → Pydantic FashionIntent 객체 반환
            result: FashionIntent = chain.invoke({
                "message": message,
                "has_search_results": has_search_results,
                "has_user_image": has_user_image,
                "cart_count": cart_count,
            })

            # Pydantic 객체 → dict 변환 (기존 인터페이스 유지)
            intent_result = {
                "intent": result.intent,
                "sub_intent": result.sub_intent,
                "search_params": {
                    "target_categories": result.target_categories or [],
                    "color": result.color,
                    "brand": result.brand,
                    "item_type": result.item_type,
                    "pattern": result.pattern,
                    "style": result.style,
                    "material": result.material,
                },
                "commerce_params": {
                    "size": result.size,
                },
                "references": {
                    "type": result.reference_type or "none",
                    "indices": result.reference_indices or [],
                    "temporal": result.reference_temporal,
                },
                "confidence": result.confidence,
            }

            logger.info(
                f"LangChain Intent Classification: {intent_result['intent']}/{intent_result['sub_intent']} "
                f"(confidence: {intent_result['confidence']:.2f})"
            )

            return intent_result

        except Exception as e:
            logger.error(f"Intent classification failed: {e}")

        # 폴백: None 반환하여 키워드 기반 분류 사용
        return None


# =============================================================================
# Convenience functions
# =============================================================================

def get_langchain_service(model: str = 'gpt-4o-mini', temperature: float = 0.7) -> LangChainService:
    """
    Get LangChain service instance.

    Args:
        model: OpenAI model name
        temperature: Sampling temperature

    Returns:
        LangChainService instance
    """
    return LangChainService(model=model, temperature=temperature)


def merge_parsed_requests(parsed_result: dict) -> list[dict]:
    """
    다중 요청을 카테고리별로 병합.

    같은 카테고리에 대한 여러 요청이 있으면
    필터를 합쳐서 하나의 요청으로 만듦.

    Args:
        parsed_result: parse_refine_query_v2 결과

    Returns:
        카테고리별로 병합된 요청 리스트
    """
    requests = parsed_result.get('requests', [])
    if len(requests) <= 1:
        return requests

    # 카테고리별 그룹화
    category_map = {}
    for req in requests:
        for cat in req.get('target_categories', []):
            if cat not in category_map:
                category_map[cat] = {
                    'action': req.get('action', 'research'),
                    'target_categories': [cat],
                }
            # 필터 병합
            for key in ['color_filter', 'pattern_filter', 'style_vibe',
                       'sleeve_length', 'pants_length', 'outer_length',
                       'material_filter', 'brand_filter', 'price_sort',
                       'fit_filter', 'search_keywords']:
                if req.get(key):
                    category_map[cat][key] = req[key]

    return list(category_map.values())
