# API 명세서

## 기본 정보

- **Base URL**: `/api/v1`
- **인증**: JWT Bearer Token
- **토큰 유효기간**: Access 1시간, Refresh 7일

---

## 1. 인증 API (Auth)

### 1.1 회원가입
```
POST /api/v1/auth/register
```

**Request Body:**
```json
{
  "username": "string (필수)",
  "email": "string (필수)",
  "password": "string (필수)",
  "password_confirm": "string (필수)"
}
```

**Response (201 Created):**
```json
{
  "user": {
    "user_id": 1,
    "username": "string",
    "email": "string"
  },
  "tokens": {
    "refresh": "string",
    "access": "string"
  }
}
```

**Error Response:**
| 상태 코드 | 설명 | 응답 |
|----------|------|------|
| 400 | 패스워드 불일치 | `{"password_confirm": ["비밀번호가 일치하지 않습니다."]}` |
| 400 | 중복된 이메일 | `{"email": ["This field must be unique."]}` |

---

### 1.2 로그인
```
POST /api/v1/auth/login
```

**Request Body:**
```json
{
  "username": "string (필수)",
  "password": "string (필수)"
}
```

**Response (200 OK):**
```json
{
  "refresh": "string",
  "access": "string"
}
```

**Error Response:**
| 상태 코드 | 설명 | 응답 |
|----------|------|------|
| 401 | 잘못된 자격증명 | `{"detail": "No active account found with the given credentials"}` |

---

### 1.3 토큰 갱신
```
POST /api/v1/auth/refresh
```

**Request Body:**
```json
{
  "refresh": "string (필수)"
}
```

**Response (200 OK):**
```json
{
  "access": "string",
  "refresh": "string"
}
```

**Error Response:**
| 상태 코드 | 설명 | 응답 |
|----------|------|------|
| 401 | 만료/무효 토큰 | `{"detail": "Token is invalid or expired"}` |

---

## 2. 사용자 API (Users)

### 2.1 프로필 조회
```
GET /api/v1/users/profile
Authorization: Bearer {access_token}
```

**Response (200 OK):**
```json
{
  "user_id": 1,
  "user_name": "string",
  "user_email": "string",
  "phone_number": "string or null",
  "address": "string or null",
  "birth_date": "YYYY-MM-DD or null",
  "user_image_url": "string or null",
  "payment": "string or null",
  "updated_at": "2026-01-17T12:34:56Z",
  "created_at": "2026-01-17T12:34:56Z"
}
```

---

### 2.2 프로필 수정
```
PATCH /api/v1/users/profile
Authorization: Bearer {access_token}
```

**Request Body (모든 필드 선택):**
```json
{
  "phone_number": "string",
  "address": "string",
  "birth_date": "YYYY-MM-DD",
  "user_image_url": "string",
  "payment": "string"
}
```

**Response (200 OK):**
```json
{
  "user_id": 1,
  "user_name": "string",
  "user_email": "string",
  "phone_number": "string or null",
  "address": "string or null",
  "birth_date": "YYYY-MM-DD or null",
  "user_image_url": "string or null",
  "payment": "string or null",
  "updated_at": "2026-01-17T12:34:56Z",
  "created_at": "2026-01-17T12:34:56Z"
}
```

---

### 2.3 온보딩 (회원가입 후 추가 정보 입력)
```
PATCH /api/v1/users/onboarding
Authorization: Bearer {access_token}
```

**Request Body:**
```json
{
  "user_email": "string",
  "address": "string",
  "payment": "card",
  "phone_number": "string"
}
```

**Response (200 OK):**
```json
{
  "user_id": 1,
  "user_name": "string",
  "user_email": "string",
  "address": "string",
  "payment": "card",
  "phone_number": "string",
  "updated_at": "2026-01-17T12:34:56Z"
}
```

**Error Response:**
| 상태 코드 | 설명 | 응답 |
|----------|------|------|
| 400 | 필수 필드 누락, 이메일/전화번호 형식 오류 | `{"message": "Invalid request data"}` |
| 401 | 인증 토큰 없음/무효 | `{"message": "Unauthorized"}` |
| 500 | 서버 오류 | `{"message": "Internal server error"}` |

---

## 3. 장바구니 API (Cart)

### 3.1 장바구니 조회
```
GET /api/v1/cart-items
Authorization: Bearer {access_token}
```

**Response (200 OK):**
```json
{
  "items": [
    {
      "cart_item_id": 1,
      "selected_product_id": 123,
      "quantity": 2,
      "product_details": {
        "product_id": 456,
        "brand_name": "브랜드명",
        "product_name": "상품명",
        "selling_price": 59000,
        "main_image_url": "https://...",
        "product_url": "https://...",
        "size": "M",
        "inventory": 10
      },
      "created_at": "2026-01-17T12:34:56Z"
    }
  ],
  "total_quantity": 2,
  "total_price": 118000
}
```

---

### 3.2 장바구니 추가
```
POST /api/v1/cart-items
Authorization: Bearer {access_token}
```

**Request Body:**
```json
{
  "selected_product_id": 123,
  "quantity": 1
}
```

**Response (201 Created):**
```json
{
  "cart_id": 1,
  "selected_product_id": 123,
  "quantity": 1,
  "created_at": "2026-01-17T12:34:56Z"
}
```

**Error Response:**
| 상태 코드 | 설명 | 응답 |
|----------|------|------|
| 400 | 상품 없음 | `{"selected_product_id": ["해당 상품을 찾을 수 없습니다."]}` |

---

### 3.3 장바구니 삭제
```
DELETE /api/v1/cart-items/{cart_item_id}
Authorization: Bearer {access_token}
```

**Response:** `204 No Content`

**Error Response:**
| 상태 코드 | 설명 | 응답 |
|----------|------|------|
| 404 | 항목 없음 | `{"detail": "해당 장바구니 항목을 찾을 수 없습니다."}` |

---

## 4. 주문 API (Orders)

### 4.1 주문 생성
```
POST /api/v1/orders/
Authorization: Bearer {access_token}
```

**Request Body:**
```json
{
  "cart_item_ids": [1, 2, 3],
  "user_id": 9,
  "payment_method": "card"
}
```

**Response (201 Created):**
```json
{
  "order_id": 1,
  "total_price": 203800,
  "delivery_address": "서울시 강남구...",
  "created_at": "2026-01-17T12:34:56Z",
  "order_status": "PAID"
}
```

**Error Response:**
| 상태 코드 | 설명 | 응답 |
|----------|------|------|
| 400 | 유효하지 않은 장바구니 | `{"cart_item_ids": ["유효하지 않은 장바구니 항목이 포함되어 있습니다."]}` |
| 400 | user_id 불일치 | `{"user_id": ["잘못된 사용자 ID입니다."]}` |

---

### 4.2 주문 목록 조회
```
GET /api/v1/orders/
Authorization: Bearer {access_token}
```

**Query Parameters:**
| 파라미터 | 타입 | 설명 |
|---------|------|------|
| cursor | string | 페이지네이션 커서 |
| limit | integer | 페이지 크기 (기본값: 10) |
| status | string | 주문 상태 필터 (PENDING/PAID/PREPARING/SHIPPING/DELIVERED/CANCELLED) |

**Response (200 OK):**
```json
{
  "orders": [
    {
      "order_id": 1,
      "total_price": 203800,
      "created_at": "2026-01-17T12:34:56Z"
    }
  ],
  "next_cursor": "abc123"
}
```

---

### 4.3 주문 상세 조회
```
GET /api/v1/orders/{order_id}/
Authorization: Bearer {access_token}
```

**Response (200 OK):**
```json
{
  "order_id": 1,
  "total_price": 203800,
  "delivery_address": "서울시 강남구...",
  "order_items": [
    {
      "order_item_id": 1,
      "order_status": "PAID",
      "selected_product_id": 123,
      "purchased_quantity": 1,
      "price_at_order": 94800,
      "product_name": "상품명"
    }
  ],
  "created_at": "2026-01-17T12:34:56Z",
  "updated_at": "2026-01-17T12:34:56Z"
}
```

---

### 4.4 주문 취소
```
PATCH /api/v1/orders/{order_id}/
Authorization: Bearer {access_token}
```

**Request Body:**
```json
{
  "order_status": "canceled"
}
```

**Response (200 OK):**
```json
{
  "order_id": 1,
  "order_status": "cancelled",
  "updated_at": "2026-01-17T12:34:56Z"
}
```

**Error Response:**
| 상태 코드 | 설명 | 응답 |
|----------|------|------|
| 400 | 취소 불가 상태 | `{"detail": "이미 배송 중이거나 취소 불가능한 상태입니다."}` |
| 400 | 잘못된 값 | `{"order_status": ["order_status는 'canceled'여야 합니다."]}` |

---

## 5. 가상 피팅 API (Fittings)

### 5.1 사용자 전신 이미지 업로드
```
POST /api/v1/user-images
Authorization: Bearer {access_token}
Content-Type: multipart/form-data
```

**Request Body:**
| 필드 | 타입 | 설명 |
|-----|------|------|
| file | file | 이미지 파일 (JPG/PNG/WEBP, 최대 10MB) |

**Response (201 Created):**
```json
{
  "user_image_id": 1,
  "user_image_url": "https://storage.googleapis.com/.../image.jpg",
  "created_at": "2026-01-17T12:34:56Z"
}
```

**Error Response:**
| 상태 코드 | 설명 | 응답 |
|----------|------|------|
| 400 | 파일 크기 초과 | `{"file": ["파일 크기는 10MB 이하여야 합니다."]}` |
| 400 | 지원하지 않는 형식 | `{"file": ["JPG, PNG, WEBP 파일만 업로드 가능합니다."]}` |

---

### 5.2 가상 피팅 요청
```
POST /api/v1/fitting-images
Authorization: Bearer {access_token}
```

**Request Body:**
```json
{
  "product_id": 456,
  "user_image_url": "https://storage.googleapis.com/.../image.jpg"
}
```

**Response (201 Created):**
```json
{
  "fitting_image_id": 1,
  "fitting_image_status": "PENDING",
  "fitting_image_url": null,
  "polling": {
    "status_url": "/api/v1/fitting-images/1/status",
    "result_url": "/api/v1/fitting-images/1"
  },
  "completed_at": "2026-01-17T12:34:56Z"
}
```

**Response (200 OK - 캐시된 결과):**
```json
{
  "fitting_image_id": 1,
  "fitting_image_status": "DONE",
  "fitting_image_url": "https://...",
  "completed_at": "2026-01-17T12:34:56Z"
}
```

**Error Response:**
| 상태 코드 | 설명 | 응답 |
|----------|------|------|
| 400 | 이미지 없음 | `{"user_image_url": ["존재하지 않는 사용자 이미지 URL입니다. 먼저 /api/v1/user-images 에서 이미지를 업로드하세요."]}` |

---

### 5.3 피팅 상태 조회 (Polling)
```
GET /api/v1/fitting-images/{fitting_image_id}/status
Authorization: Bearer {access_token}
```

**Response (200 OK):**
```json
{
  "fitting_image_status": "RUNNING",
  "progress": 40,
  "updated_at": "2026-01-17T12:34:56Z"
}
```

**Progress 값:**
| 상태 | progress |
|-----|----------|
| PENDING | 0 |
| RUNNING | 40 |
| DONE | 100 |
| FAILED | 0 |

---

### 5.4 피팅 결과 조회
```
GET /api/v1/fitting-images/{fitting_image_id}
Authorization: Bearer {access_token}
```

**Response (200 OK):**
```json
{
  "fitting_image_id": 1,
  "fitting_image_status": "DONE",
  "fitting_image_url": "https://...",
  "completed_at": "2026-01-17T12:34:56Z"
}
```

---

## 6. 이미지 분석 API (Analyses)

### 6.1 이미지 업로드
```
POST /api/v1/uploaded-images
Authorization: Bearer {access_token}
Content-Type: multipart/form-data
```

**Request Body:**
| 필드 | 타입 | 설명 |
|-----|------|------|
| file | file | 이미지 파일 (JPG/PNG/WEBP, 최대 10MB) |

**Response (201 Created):**
```json
{
  "uploaded_image_id": 1,
  "uploaded_image_url": "https://...",
  "created_at": "2026-01-17T12:34:56Z"
}
```

---

### 6.2 업로드 이미지 목록 조회
```
GET /api/v1/uploaded-images
Authorization: Bearer {access_token}
```

**Query Parameters:**
| 파라미터 | 타입 | 설명 |
|---------|------|------|
| cursor | string | 페이지네이션 커서 |
| limit | integer | 페이지 크기 (기본값: 10) |

**Response (200 OK):**
```json
{
  "items": [
    {
      "uploaded_image_id": 1,
      "uploaded_image_url": "https://...",
      "created_at": "2026-01-17T12:34:56Z"
    }
  ],
  "next_cursor": "abc123"
}
```

---

### 6.3 이미지 분석 시작
```
POST /api/v1/analyses
Authorization: Bearer {access_token}
```

**Request Body:**
```json
{
  "uploaded_image_id": 1
}
```

**Response (201 Created):**
```json
{
  "analysis_id": 1,
  "status": "PENDING",
  "polling": {
    "status_url": "/api/v1/analyses/1/status",
    "result_url": "/api/v1/analyses/1"
  }
}
```

---

### 6.4 분석 상태 조회 (Polling)
```
GET /api/v1/analyses/{analysis_id}/status
Authorization: Bearer {access_token}
```

**Response (200 OK):**
```json
{
  "analysis_id": 1,
  "status": "RUNNING",
  "progress": 50,
  "updated_at": "2026-01-17T12:34:56Z"
}
```

**Status 값:**
| 상태 | 설명 |
|-----|------|
| PENDING | 대기 중 |
| RUNNING | 분석 중 |
| DONE | 완료 |
| FAILED | 실패 |

---

### 6.5 분석 결과 조회
```
GET /api/v1/analyses/{analysis_id}
Authorization: Bearer {access_token}
```

**Response (200 OK):**
```json
{
  "analysis_id": 1,
  "uploaded_image": {
    "id": 1,
    "url": "https://..."
  },
  "status": "DONE",
  "items": [
    {
      "detected_object_id": 1,
      "category_name": "상의",
      "confidence_score": 0.95,
      "bbox": {
        "x1": 0.1,
        "y1": 0.2,
        "x2": 0.5,
        "y2": 0.8
      },
      "match": {
        "product_id": 456,
        "product": {
          "id": 456,
          "brand_name": "브랜드명",
          "product_name": "상품명",
          "selling_price": 59000,
          "image_url": "https://...",
          "product_url": "https://...",
          "sizes": [
            {
              "size_code_id": 1,
              "size_value": "M",
              "inventory": 10,
              "selected_product_id": 123
            }
          ]
        }
      }
    }
  ]
}
```

---

### 6.6 자연어 재분석
```
PATCH /api/v1/analyses
Authorization: Bearer {access_token}
```

**Request Body:**
```json
{
  "analysis_id": 1,
  "query": "상의만 다시 검색해줘",
  "detected_object_id": 1
}
```

**Response (200 OK):**
```json
{
  "analysis_id": 1,
  "status": "DONE",
  "image": {
    "uploaded_image_id": 1,
    "uploaded_image_url": "https://..."
  },
  "items": [
    {
      "detected_object_id": 1,
      "category_name": "상의",
      "confidence_score": 0.95,
      "bbox": { "x1": 0.1, "y1": 0.2, "x2": 0.5, "y2": 0.8 },
      "match": {
        "product_id": 789,
        "product": {
          "id": 789,
          "brand_name": "새브랜드",
          "product_name": "새상품",
          "selling_price": 45000,
          "image_url": "https://...",
          "product_url": "https://..."
        }
      }
    }
  ]
}
```

---

### 6.7 통합 히스토리 조회
```
GET /api/v1/uploaded-images/{uploaded_image_id}
Authorization: Bearer {access_token}
```

**Query Parameters:**
| 파라미터 | 타입 | 설명 |
|---------|------|------|
| cursor | string | 페이지네이션 커서 |
| limit | integer | 페이지 크기 (기본값: 10) |

**Response (200 OK):**
```json
{
  "items": [
    {
      "detected_object_id": 1,
      "category_name": "상의",
      "confidence_score": 0.95,
      "bbox": { "x1": 0.1, "y1": 0.2, "x2": 0.5, "y2": 0.8 },
      "match": {
        "product_id": 456,
        "product": {
          "id": 456,
          "brand_name": "브랜드명",
          "product_name": "상품명",
          "selling_price": 59000,
          "image_url": "https://...",
          "product_url": "https://..."
        },
        "fitting": {
          "fitting_image_id": 1,
          "fitting_image_url": "https://..."
        }
      }
    }
  ],
  "next_cursor": "abc123"
}
```

---

## 공통 에러 응답

| 상태 코드 | 설명 | 응답 |
|----------|------|------|
| 401 | 인증 토큰 없음 | `{"detail": "Authentication credentials were not provided."}` |
| 401 | 토큰 무효/만료 | `{"detail": "Invalid token."}` |
| 403 | 권한 없음 | `{"detail": "You do not have permission to perform this action."}` |
| 404 | 리소스 없음 | `{"detail": "Not found."}` |
| 500 | 서버 오류 | `{"error": "Internal server error"}` |

---

## 참고 사항

- **인증**: 회원가입, 로그인, 토큰 갱신을 제외한 모든 API는 `Authorization: Bearer {token}` 헤더 필요
- **파일 업로드**: `multipart/form-data` 형식, 허용 형식 JPG/PNG/WEBP, 최대 10MB
- **페이지네이션**: Cursor 기반, `next_cursor`가 null이면 마지막 페이지
- **Soft Delete**: 삭제된 데이터는 `is_deleted=True`로 표시되며 실제 삭제되지 않음
- **비동기 처리**: 이미지 분석, 가상 피팅은 Celery 비동기 처리, polling으로 상태 확인
