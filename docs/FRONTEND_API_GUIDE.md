# AI 패션 어시스턴트 - 프론트엔드 통합 가이드

> **작성일**: 2026-01-20
> **버전**: 1.0.0
> **대상**: 프론트엔드 개발팀

---

## 목차

1. [개요](#1-개요)
2. [인증](#2-인증)
3. [API 엔드포인트](#3-api-엔드포인트)
4. [요청/응답 형식](#4-요청응답-형식)
5. [응답 타입별 UI 처리](#5-응답-타입별-ui-처리)
6. [비동기 작업 폴링](#6-비동기-작업-폴링)
7. [세션 관리](#7-세션-관리)
8. [통합 플로우 예시](#8-통합-플로우-예시)
9. [에러 처리](#9-에러-처리)
10. [React 통합 예시](#10-react-통합-예시)

---

## 1. 개요

### 1.1 새로운 채팅 기반 인터페이스

기존의 개별 API 호출 방식에서 **통합 채팅 API**로 변경되었습니다.

```
기존: 검색 API → 피팅 API → 장바구니 API (각각 별도 호출)
신규: 채팅 API 하나로 모든 기능 통합 (자연어 + 이미지)
```

### 1.2 주요 변경점

| 항목 | 기존 | 신규 |
|------|------|------|
| 검색 | `POST /api/v1/analyses` | `POST /api/v1/chat` (메시지/이미지) |
| 피팅 | `POST /api/v1/fittings` | `POST /api/v1/chat` ("입어볼래") |
| 장바구니 | `POST /api/v1/cart` | `POST /api/v1/chat` ("담아줘") |
| 상태확인 | 각 API별 status 엔드포인트 | `POST /api/v1/chat/status` |

### 1.3 핵심 컨셉

- **하이브리드 UI**: 채팅 패널 + 콘텐츠 패널 (상품 목록, 피팅 결과 등)
- **세션 기반**: 대화 컨텍스트 유지 (2시간 TTL)
- **비동기 처리**: 이미지 분석, 피팅은 폴링으로 결과 확인

---

## 2. 인증

모든 API는 JWT 인증이 필요합니다.

### 2.1 헤더 형식

```http
Authorization: Bearer <access_token>
Content-Type: application/json
```

### 2.2 토큰 갱신

```http
POST /api/v1/auth/refresh
Content-Type: application/json

{
  "refresh": "<refresh_token>"
}
```

---

## 3. API 엔드포인트

### 3.1 채팅 API

#### `POST /api/v1/chat`

메인 채팅 엔드포인트. 모든 사용자 요청을 처리합니다.

**Request (JSON)**
```http
POST /api/v1/chat
Content-Type: application/json
Authorization: Bearer <token>

{
  "message": "검은색 자켓 찾아줘",
  "session_id": "uuid-session-id"  // 선택사항, 없으면 새 세션 생성
}
```

**Request (Multipart - 이미지 포함)**
```http
POST /api/v1/chat
Content-Type: multipart/form-data
Authorization: Bearer <token>

message: "이거랑 비슷한 거 찾아줘"
session_id: "uuid-session-id"
image: <file>
```

**Response**
```json
{
  "session_id": "550e8400-e29b-41d4-a716-446655440000",
  "response": {
    "text": "찾은 상품이에요:\n\n1. Nike 에어맥스 - ₩159,000\n2. Adidas 울트라부스트 - ₩189,000\n...",
    "type": "search_results",
    "data": {
      "products": [...],
      "total_count": 5
    },
    "suggestions": [
      {"label": "피팅해볼까요?", "action": "fitting"},
      {"label": "장바구니에 담기", "action": "add_cart"}
    ]
  },
  "context": {
    "current_analysis_id": 123,
    "has_search_results": true,
    "has_user_image": true,
    "cart_item_count": 3
  }
}
```

---

#### `POST /api/v1/chat/status`

비동기 작업(분석, 피팅) 상태 확인

**Request**
```json
{
  "type": "analysis",  // "analysis" 또는 "fitting"
  "id": 123,
  "session_id": "uuid-session-id"
}
```

**Response (진행 중)**
```json
{
  "session_id": "uuid-session-id",
  "response": {
    "text": "이미지를 분석 중이에요... 잠시만 기다려주세요!",
    "type": "analysis_pending",
    "data": {
      "analysis_id": 123,
      "status_url": "/api/v1/analyses/123/status"
    },
    "suggestions": []
  }
}
```

**Response (완료)**
```json
{
  "session_id": "uuid-session-id",
  "response": {
    "text": "찾은 상품이에요:\n\n1. ...",
    "type": "search_results",
    "data": {
      "products": [...]
    },
    "suggestions": [...]
  }
}
```

---

#### `GET /api/v1/chat/sessions/<session_id>`

세션 정보 및 대화 이력 조회

**Response**
```json
{
  "session_id": "uuid-session-id",
  "user_id": 1,
  "created_at": "2026-01-20T10:00:00Z",
  "last_activity": "2026-01-20T10:30:00Z",
  "has_search_results": true,
  "has_user_image": true,
  "cart_item_count": 2,
  "turns": [
    {
      "user": "검은색 자켓 찾아줘",
      "assistant": "찾은 상품이에요:\n\n1. ...",
      "timestamp": "2026-01-20T10:00:00Z"
    },
    {
      "user": "1번 입어볼래",
      "assistant": "피팅 중이에요...",
      "timestamp": "2026-01-20T10:01:00Z"
    }
  ]
}
```

---

#### `DELETE /api/v1/chat/sessions/<session_id>`

세션 삭제 (대화 초기화)

**Response**
```
HTTP 204 No Content
```

---

## 4. 요청/응답 형식

### 4.1 공통 응답 구조

모든 채팅 응답은 동일한 구조를 따릅니다:

```typescript
interface ChatResponse {
  session_id: string;
  response: {
    text: string;           // 채팅에 표시할 텍스트
    type: ResponseType;     // UI 렌더링 결정용 타입
    data: object;           // 타입별 추가 데이터
    suggestions: Suggestion[];  // 추천 액션 버튼
  };
  context: {
    current_analysis_id?: number;
    has_search_results: boolean;
    has_user_image: boolean;
    cart_item_count: number;
  };
}

interface Suggestion {
  label: string;    // 버튼 텍스트
  action: string;   // 액션 식별자
}
```

### 4.2 Response Type 목록

| Type | 설명 | data 구조 |
|------|------|-----------|
| `search_results` | 검색 결과 | `{ products, total_count }` |
| `no_results` | 검색 결과 없음 | `{}` |
| `analysis_pending` | 이미지 분석 중 | `{ analysis_id, status_url }` |
| `fitting_pending` | 피팅 처리 중 | `{ fitting_id, product }` |
| `fitting_result` | 피팅 완료 | `{ fitting_image_url, product }` |
| `batch_fitting_pending` | 배치 피팅 중 | `{ fitting_ids, count }` |
| `cart_added` | 장바구니 추가됨 | `{ product, size, quantity }` |
| `cart_list` | 장바구니 목록 | `{ items, total_price }` |
| `cart_empty` | 장바구니 비어있음 | `{}` |
| `order_created` | 주문 생성됨 | `{ order_id, total_price }` |
| `size_recommendation` | 사이즈 추천 | `{ recommended_size, available_sizes }` |
| `ask_selection` | 선택 요청 | `{ options }` |
| `ask_size` | 사이즈 선택 요청 | `{ available_sizes }` |
| `ask_body_info` | 신체 정보 요청 | `{}` |
| `ask_user_image` | 전신 사진 요청 | `{}` |
| `ask_search_first` | 검색 먼저 요청 | `{}` |
| `greeting` | 인사 | `{}` |
| `help` | 도움말 | `{}` |
| `general` | 일반 응답 | `{}` |
| `error` | 에러 | `{ error_type }` |

---

## 5. 응답 타입별 UI 처리

### 5.1 `search_results` - 상품 목록 표시

```json
{
  "type": "search_results",
  "data": {
    "products": [
      {
        "index": 1,
        "product_id": 12345,
        "brand_name": "Nike",
        "product_name": "에어맥스 90",
        "selling_price": 159000,
        "image_url": "https://...",
        "product_url": "https://...",
        "sizes": ["250", "255", "260", "265", "270"]
      }
    ],
    "total_count": 5,
    "understood_intent": "검은색 운동화 검색"
  }
}
```

**UI 처리**
```
┌─────────────────────────────────────────────────────────────┐
│ [채팅 패널]              │ [콘텐츠 패널 - 상품 그리드]       │
│                          │                                   │
│ 🤖 찾은 상품이에요:      │  ┌─────┐ ┌─────┐ ┌─────┐         │
│                          │  │ 📷  │ │ 📷  │ │ 📷  │         │
│ 1. Nike 에어맥스 90      │  │Nike │ │Adidas│ │NB   │         │
│    ₩159,000              │  │159K │ │189K │ │149K │         │
│                          │  └─────┘ └─────┘ └─────┘         │
│ [피팅해볼까요?]          │                                   │
│ [장바구니에 담기]        │  ┌─────┐ ┌─────┐                 │
│                          │  │ 📷  │ │ 📷  │                 │
└─────────────────────────────────────────────────────────────┘
```

---

### 5.2 `fitting_pending` / `fitting_result` - 피팅 처리

**피팅 진행 중**
```json
{
  "type": "fitting_pending",
  "data": {
    "fitting_id": 456,
    "product": {
      "product_id": 12345,
      "product_name": "에어맥스 90"
    },
    "status_url": "/api/v1/fitting-images/456/status"
  }
}
```

**UI 처리**: 로딩 스피너 표시, 3초마다 status API 폴링

**피팅 완료**
```json
{
  "type": "fitting_result",
  "data": {
    "fitting_image_url": "https://cdn.example.com/fitting/456.jpg",
    "product": {
      "product_id": 12345,
      "brand_name": "Nike",
      "product_name": "에어맥스 90",
      "selling_price": 159000
    },
    "color_match_score": 85
  }
}
```

**UI 처리**
```
┌─────────────────────────────────────────────────────────────┐
│ [채팅 패널]              │ [콘텐츠 패널 - 피팅 결과]         │
│                          │                                   │
│ 🤖 에어맥스 90 피팅      │     ┌─────────────────┐          │
│    결과예요!             │     │                 │          │
│                          │     │   [피팅 이미지]  │          │
│ 컬러 매칭 점수: 85/100   │     │                 │          │
│                          │     │    사용자+상품   │          │
│ [장바구니에 담기]        │     │                 │          │
│ [다른 상품 피팅]         │     └─────────────────┘          │
│ [주문하기]               │     Nike 에어맥스 90             │
│                          │     ₩159,000                     │
└─────────────────────────────────────────────────────────────┘
```

---

### 5.3 `cart_list` - 장바구니

```json
{
  "type": "cart_list",
  "data": {
    "items": [
      {
        "cart_item_id": 789,
        "product": {
          "product_id": 12345,
          "brand_name": "Nike",
          "product_name": "에어맥스 90",
          "selling_price": 159000,
          "image_url": "https://..."
        },
        "size": "265",
        "quantity": 1
      }
    ],
    "total_price": 318000,
    "item_count": 2
  }
}
```

---

### 5.4 `ask_selection` - 선택 요청

사용자가 어떤 상품을 선택할지 명확하지 않을 때:

```json
{
  "type": "ask_selection",
  "data": {
    "options": [
      {"product_id": 1, "brand_name": "Nike", "product_name": "에어맥스 90"},
      {"product_id": 2, "brand_name": "Adidas", "product_name": "울트라부스트"}
    ]
  },
  "suggestions": [
    {"label": "1번", "action": "select_1"},
    {"label": "2번", "action": "select_2"}
  ]
}
```

**UI 처리**: suggestions의 버튼 또는 상품 카드 클릭으로 선택

---

### 5.5 `size_recommendation` - 사이즈 추천

```json
{
  "type": "size_recommendation",
  "data": {
    "recommended_size": "L",
    "available_sizes": ["S", "M", "L", "XL"],
    "confidence": 85,
    "product": {...}
  },
  "suggestions": [
    {"label": "L로 담기", "action": "add_cart"},
    {"label": "다른 사이즈", "action": "size_recommend"}
  ]
}
```

---

## 6. 비동기 작업 폴링

### 6.1 폴링 플로우

```
┌──────────────┐     POST /chat      ┌──────────────┐
│   Frontend   │ ──────────────────> │   Backend    │
│              │ <────────────────── │              │
│              │  analysis_pending   │              │
│              │  (analysis_id: 123) │              │
│              │                     │              │
│  [3초 대기]  │                     │  [Celery     │
│              │                     │   처리 중]   │
│              │  POST /chat/status  │              │
│              │ ──────────────────> │              │
│              │ <────────────────── │              │
│              │  analysis_pending   │              │
│              │                     │              │
│  [3초 대기]  │                     │              │
│              │  POST /chat/status  │              │
│              │ ──────────────────> │              │
│              │ <────────────────── │              │
│              │  search_results ✓   │              │
└──────────────┘                     └──────────────┘
```

### 6.2 폴링 구현 예시

```typescript
async function pollStatus(
  type: 'analysis' | 'fitting',
  id: number,
  sessionId: string,
  maxAttempts = 20,
  interval = 3000
): Promise<ChatResponse> {
  for (let i = 0; i < maxAttempts; i++) {
    const response = await fetch('/api/v1/chat/status', {
      method: 'POST',
      headers: {
        'Authorization': `Bearer ${token}`,
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({ type, id, session_id: sessionId })
    });

    const data = await response.json();

    // 완료 또는 실패 시 반환
    if (!data.response.type.includes('pending')) {
      return data;
    }

    // 대기 후 재시도
    await new Promise(resolve => setTimeout(resolve, interval));
  }

  throw new Error('Polling timeout');
}
```

### 6.3 폴링이 필요한 Response Types

| Type | 폴링 필요 | 완료 Type |
|------|-----------|-----------|
| `analysis_pending` | ✅ | `search_results` 또는 `no_results` |
| `fitting_pending` | ✅ | `fitting_result` |
| `batch_fitting_pending` | ✅ | `fitting_result` (각각) |
| 기타 | ❌ | - |

---

## 7. 세션 관리

### 7.1 세션 생성

첫 요청 시 `session_id`를 생략하면 서버에서 새 세션 생성:

```javascript
// 첫 요청
const response = await chat({ message: "안녕" });
const sessionId = response.session_id;  // 저장해두기

// 이후 요청
await chat({ message: "자켓 찾아줘", session_id: sessionId });
```

### 7.2 세션 유지

- **TTL**: 2시간 (마지막 활동 기준)
- **저장 위치**: localStorage 또는 sessionStorage 권장
- **대화 이력**: 최대 20턴 저장

### 7.3 세션 초기화

새 대화 시작 시:

```javascript
// 방법 1: session_id 생략
const response = await chat({ message: "안녕" });

// 방법 2: 명시적 삭제
await fetch(`/api/v1/chat/sessions/${sessionId}`, {
  method: 'DELETE',
  headers: { 'Authorization': `Bearer ${token}` }
});
```

---

## 8. 통합 플로우 예시

### 8.1 전체 쇼핑 플로우

```
사용자                     프론트엔드                      백엔드
  │                           │                             │
  │  [이미지 업로드]          │                             │
  ├──────────────────────────>│                             │
  │                           │  POST /chat (image)         │
  │                           ├────────────────────────────>│
  │                           │  analysis_pending           │
  │                           │<────────────────────────────┤
  │  "분석 중..." 표시        │                             │
  │<──────────────────────────┤                             │
  │                           │  [3초마다 폴링]             │
  │                           │  POST /chat/status          │
  │                           ├────────────────────────────>│
  │                           │  search_results             │
  │                           │<────────────────────────────┤
  │  상품 목록 표시           │                             │
  │<──────────────────────────┤                             │
  │                           │                             │
  │  "1번 입어볼래"           │                             │
  ├──────────────────────────>│                             │
  │                           │  POST /chat                 │
  │                           ├────────────────────────────>│
  │                           │  fitting_pending            │
  │                           │<────────────────────────────┤
  │  "피팅 중..." 표시        │                             │
  │<──────────────────────────┤                             │
  │                           │  [폴링]                     │
  │                           │  POST /chat/status          │
  │                           ├────────────────────────────>│
  │                           │  fitting_result             │
  │                           │<────────────────────────────┤
  │  피팅 이미지 표시         │                             │
  │<──────────────────────────┤                             │
  │                           │                             │
  │  "마음에 들어, L 사이즈   │                             │
  │   로 담아줘"              │                             │
  ├──────────────────────────>│                             │
  │                           │  POST /chat                 │
  │                           ├────────────────────────────>│
  │                           │  cart_added                 │
  │                           │<────────────────────────────┤
  │  "담았어요!" 표시         │                             │
  │<──────────────────────────┤                             │
  │                           │                             │
  │  "주문할게"               │                             │
  ├──────────────────────────>│                             │
  │                           │  POST /chat                 │
  │                           ├────────────────────────────>│
  │                           │  order_created              │
  │                           │<────────────────────────────┤
  │  주문 완료 표시           │                             │
  │<──────────────────────────┤                             │
```

### 8.2 사용자 입력 예시

| 사용자 입력 | 의도 | 응답 타입 |
|------------|------|-----------|
| (이미지만) | 이미지 검색 | `analysis_pending` → `search_results` |
| "검은색 자켓 찾아줘" | 텍스트 검색 | `search_results` |
| "더 싼 거 보여줘" | 조건 변경 | `search_results` |
| "나이키로 보여줘" | 브랜드 필터 | `search_results` |
| "1번 입어볼래" | 단일 피팅 | `fitting_pending` → `fitting_result` |
| "다 입어봐" | 배치 피팅 | `batch_fitting_pending` |
| "이거 담아줘" | 장바구니 추가 | `ask_size` 또는 `cart_added` |
| "L 사이즈로" | 사이즈 지정 | `cart_added` |
| "장바구니 보여줘" | 장바구니 조회 | `cart_list` |
| "주문할게" | 결제 | `order_created` |
| "175cm 70kg인데 사이즈 뭐가 좋아?" | 사이즈 추천 | `size_recommendation` |
| "안녕" | 인사 | `greeting` |
| "뭐 할 수 있어?" | 도움말 | `help` |

---

## 9. 에러 처리

### 9.1 에러 응답 형식

```json
{
  "session_id": "...",
  "response": {
    "text": "검색 중 문제가 발생했어요. 다시 시도해주세요.",
    "type": "error",
    "data": {
      "error_type": "search_error"
    },
    "suggestions": [
      {"label": "다시 시도", "action": "retry"}
    ]
  }
}
```

### 9.2 에러 타입

| error_type | 설명 | 권장 처리 |
|------------|------|-----------|
| `search_error` | 검색 실패 | 재시도 버튼 |
| `upload_error` | 이미지 업로드 실패 | 다른 이미지로 재시도 |
| `fitting_error` | 피팅 실패 | 재시도 또는 다른 상품 |
| `fitting_failed` | 피팅 처리 실패 | 재시도 |
| `product_not_found` | 상품 정보 없음 | 다른 상품 선택 |
| `empty_cart` | 장바구니 비어있음 | 검색 유도 |
| `invalid_quantity` | 잘못된 수량 | 올바른 수량 입력 요청 |
| `user_not_found` | 사용자 없음 | 로그인 요청 |
| `order_not_found` | 주문 없음 | 주문 내역 확인 |
| `cannot_cancel` | 취소 불가 | 안내 메시지 |
| `system_error` | 시스템 오류 | 재시도 |
| `analysis_failed` | 분석 실패 | 다른 이미지로 재시도 |
| `analysis_not_found` | 분석 정보 없음 | 새 검색 유도 |

### 9.3 HTTP 에러

| Status | 설명 | 처리 |
|--------|------|------|
| 400 | 잘못된 요청 | 에러 메시지 표시 |
| 401 | 인증 실패 | 로그인 페이지로 리다이렉트 |
| 403 | 권한 없음 | 에러 메시지 표시 |
| 404 | 리소스 없음 | 에러 메시지 표시 |
| 500 | 서버 에러 | 재시도 유도 |

---

## 10. React 통합 예시

### 10.1 커스텀 훅

```typescript
// hooks/useChat.ts
import { useState, useCallback } from 'react';

interface ChatMessage {
  role: 'user' | 'assistant';
  content: string;
  data?: any;
  type?: string;
}

export function useChat() {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [contentPanelData, setContentPanelData] = useState<any>(null);

  const sendMessage = useCallback(async (
    message: string,
    image?: File
  ) => {
    setIsLoading(true);

    // 사용자 메시지 추가
    setMessages(prev => [...prev, { role: 'user', content: message }]);

    try {
      // FormData 구성
      const formData = new FormData();
      if (message) formData.append('message', message);
      if (image) formData.append('image', image);
      if (sessionId) formData.append('session_id', sessionId);

      // API 호출
      const response = await fetch('/api/v1/chat', {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${getToken()}`
        },
        body: formData
      });

      const data = await response.json();

      // 세션 ID 저장
      if (!sessionId) {
        setSessionId(data.session_id);
        localStorage.setItem('chatSessionId', data.session_id);
      }

      // 비동기 작업 처리
      let finalResponse = data;
      if (data.response.type.includes('pending')) {
        finalResponse = await pollUntilComplete(data);
      }

      // 어시스턴트 메시지 추가
      setMessages(prev => [...prev, {
        role: 'assistant',
        content: finalResponse.response.text,
        data: finalResponse.response.data,
        type: finalResponse.response.type
      }]);

      // 콘텐츠 패널 업데이트
      updateContentPanel(finalResponse.response);

    } catch (error) {
      console.error('Chat error:', error);
      setMessages(prev => [...prev, {
        role: 'assistant',
        content: '오류가 발생했어요. 다시 시도해주세요.',
        type: 'error'
      }]);
    } finally {
      setIsLoading(false);
    }
  }, [sessionId]);

  const pollUntilComplete = async (initialData: any) => {
    const { type } = initialData.response;
    const checkType = type === 'analysis_pending' ? 'analysis' : 'fitting';
    const id = type === 'analysis_pending'
      ? initialData.response.data.analysis_id
      : initialData.response.data.fitting_id;

    for (let i = 0; i < 20; i++) {
      await new Promise(r => setTimeout(r, 3000));

      const response = await fetch('/api/v1/chat/status', {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${getToken()}`,
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({
          type: checkType,
          id,
          session_id: sessionId
        })
      });

      const data = await response.json();
      if (!data.response.type.includes('pending')) {
        return data;
      }
    }
    throw new Error('Polling timeout');
  };

  const updateContentPanel = (response: any) => {
    const { type, data } = response;

    switch (type) {
      case 'search_results':
        setContentPanelData({
          view: 'products',
          products: data.products
        });
        break;
      case 'fitting_result':
        setContentPanelData({
          view: 'fitting',
          imageUrl: data.fitting_image_url,
          product: data.product
        });
        break;
      case 'cart_list':
        setContentPanelData({
          view: 'cart',
          items: data.items,
          totalPrice: data.total_price
        });
        break;
      default:
        // 콘텐츠 패널 유지
        break;
    }
  };

  const clearSession = useCallback(() => {
    setMessages([]);
    setSessionId(null);
    setContentPanelData(null);
    localStorage.removeItem('chatSessionId');
  }, []);

  return {
    messages,
    sessionId,
    isLoading,
    contentPanelData,
    sendMessage,
    clearSession
  };
}
```

### 10.2 컴포넌트 구조

```typescript
// components/ChatInterface.tsx
import { useChat } from '../hooks/useChat';

export function ChatInterface() {
  const {
    messages,
    isLoading,
    contentPanelData,
    sendMessage
  } = useChat();

  return (
    <div className="chat-interface">
      {/* 채팅 패널 (좌측 또는 하단) */}
      <ChatPanel
        messages={messages}
        isLoading={isLoading}
        onSend={sendMessage}
      />

      {/* 콘텐츠 패널 (우측 또는 메인) */}
      <ContentPanel data={contentPanelData} />
    </div>
  );
}

// 콘텐츠 패널 - 타입별 렌더링
function ContentPanel({ data }: { data: any }) {
  if (!data) return <WelcomeScreen />;

  switch (data.view) {
    case 'products':
      return <ProductGrid products={data.products} />;
    case 'fitting':
      return <FittingResult
        imageUrl={data.imageUrl}
        product={data.product}
      />;
    case 'cart':
      return <CartView
        items={data.items}
        totalPrice={data.totalPrice}
      />;
    default:
      return <WelcomeScreen />;
  }
}
```

### 10.3 Suggestion 버튼 처리

```typescript
// components/SuggestionButtons.tsx
interface SuggestionButtonsProps {
  suggestions: { label: string; action: string }[];
  onAction: (action: string) => void;
}

export function SuggestionButtons({
  suggestions,
  onAction
}: SuggestionButtonsProps) {
  const handleClick = (action: string) => {
    // action에 따른 메시지 매핑
    const actionMessages: Record<string, string> = {
      'fitting': '피팅해줘',
      'add_cart': '담아줘',
      'view_cart': '장바구니 보여줘',
      'checkout': '주문할게',
      'search': '검색하고 싶어',
      'refine': '다른 조건으로 찾아줘',
      'retry': '다시 해줘',
      'select_1': '1번',
      'select_2': '2번',
      // ...
    };

    const message = actionMessages[action] || action;
    onAction(message);
  };

  return (
    <div className="suggestion-buttons">
      {suggestions.map((s, i) => (
        <button
          key={i}
          onClick={() => handleClick(s.action)}
          className="suggestion-btn"
        >
          {s.label}
        </button>
      ))}
    </div>
  );
}
```

---

## 부록: TypeScript 타입 정의

```typescript
// types/chat.ts

export type ResponseType =
  | 'search_results'
  | 'no_results'
  | 'analysis_pending'
  | 'fitting_pending'
  | 'fitting_result'
  | 'batch_fitting_pending'
  | 'cart_added'
  | 'cart_list'
  | 'cart_empty'
  | 'order_created'
  | 'size_recommendation'
  | 'ask_selection'
  | 'ask_size'
  | 'ask_body_info'
  | 'ask_user_image'
  | 'ask_search_first'
  | 'greeting'
  | 'help'
  | 'general'
  | 'error';

export interface Product {
  index?: number;
  product_id: number;
  brand_name: string;
  product_name: string;
  selling_price: number;
  image_url: string;
  product_url: string;
  sizes?: string[];
}

export interface CartItem {
  cart_item_id: number;
  product: Product;
  size: string;
  quantity: number;
}

export interface Suggestion {
  label: string;
  action: string;
}

export interface ChatResponseData {
  // search_results
  products?: Product[];
  total_count?: number;
  understood_intent?: string;

  // fitting
  fitting_id?: number;
  fitting_ids?: number[];
  fitting_image_url?: string;
  color_match_score?: number;

  // cart
  items?: CartItem[];
  total_price?: number;
  item_count?: number;

  // order
  order_id?: number;
  items_count?: number;

  // size
  recommended_size?: string;
  available_sizes?: string[];
  confidence?: number;

  // status
  analysis_id?: number;
  status_url?: string;

  // error
  error_type?: string;

  // common
  product?: Product;
  size?: string;
  quantity?: number;
}

export interface ChatResponse {
  session_id: string;
  response: {
    text: string;
    type: ResponseType;
    data: ChatResponseData;
    suggestions: Suggestion[];
  };
  context: {
    current_analysis_id?: number;
    has_search_results: boolean;
    has_user_image: boolean;
    cart_item_count: number;
  };
}
```

---

## 문의

백엔드 관련 문의: 백엔드 팀 Slack 채널
