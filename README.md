# API -> Notion 자동 명세 동기화

코드(Spring Java 컨트롤러)를 읽어 API 엔드포인트를 추출하고 Notion 데이터베이스에 자동 동기화합니다.

이제 아래를 지원합니다.

- 신규 API 생성 시: Notion 페이지 자동 생성
- 기존 API 변경 시: 해시 기반 변경 감지 후 자동 업데이트
- 코드에서 API 삭제 시: Notion 페이지 자동 아카이브(`--archive-missing`)
- 변경 없는 API: 자동 스킵

## 지원 범위

- `@GetMapping`, `@PostMapping`, `@PutMapping`, `@DeleteMapping`, `@PatchMapping`, `@RequestMapping`
- 클래스 레벨 + 메서드 레벨 path 결합
- `@PathVariable`, `@RequestParam`, `@RequestBody` 단순 추출

## 1) 준비

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Notion 준비:

1. Notion Integration 생성 + 토큰 발급
2. API 명세용 DB를 Integration에 공유(Share)
3. DB 컬럼 생성 (아래 권장)

## 2) Notion DB 권장 컬럼

- `Name` (title) <- 필수
- `Method` (select 또는 rich_text)
- `Path` (rich_text)
- `Controller` (rich_text)
- `Summary` (rich_text)
- `Params` (rich_text)
- `Request Body` (rich_text)
- `Response` (rich_text)
- `Source` (rich_text)
- `Endpoint ID` (rich_text)
- `Spec Hash` (rich_text)
- `Status` (select 또는 rich_text)
- `Last Synced At` (date 또는 rich_text)

컬럼명이 다르면 `--property-map`으로 매핑하세요.

## 3) 실행

```bash
export NOTION_TOKEN="secret_xxx"
python api_to_notion.py \
  --repo "/absolute/path/to/backend-repo" \
  --database-id "notion_database_id" \
  --property-map "property-map.example.json" \
  --archive-missing
```

드라이런:

```bash
python api_to_notion.py --repo "/absolute/path/to/backend-repo" --dry-run
```

## 4) 자동 반영 운영 방법

### 옵션 A. cron으로 5분마다 동기화

```bash
*/5 * * * * cd /Users/bagtaesu/Desktop/git/JustFine && /Users/bagtaesu/Desktop/git/JustFine/.venv/bin/python api_to_notion.py --repo "/absolute/path/to/backend-repo" --database-id "notion_database_id" --archive-missing >> /tmp/api-sync.log 2>&1
```

### 옵션 B. GitHub Actions (push마다 동기화)

`push -> sync script 실행`으로 두면 API 변경 즉시 Notion 반영됩니다.

## 주의/한계

- 파서는 정규식 기반이라 복잡한 코드 패턴에서 누락 가능
- 현재는 Spring(Java) 기준
- 응답 스키마(`Response`)는 코드에서 자동 추론하지 않음

원하면 다음 단계로 `springdoc-openapi`를 붙여 OpenAPI 스펙(JSON) 기준으로 더 정확하게 동기화하도록 고도화할 수 있습니다.
