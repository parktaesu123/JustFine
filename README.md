# JustFine API Sync

Spring 서버 코드를 읽어 Notion API 명세 DB를 자동으로 생성/업데이트하는 CLI입니다.

## 터미널에서 바로 설치

```bash
pipx install "git+https://github.com/parktaesu123/JustFine.git"
```

설치 확인:

```bash
justfine-api-sync --help
```

## 한 번만 설정 (OAuth 로그인)

### 1) Notion OAuth Integration 준비

Notion에서 OAuth Integration을 만들고 아래 값을 준비하세요.

- `NOTION_CLIENT_ID`
- `NOTION_CLIENT_SECRET`

OAuth Redirect URI는 **반드시** 아래로 설정하세요.

- `http://127.0.0.1:8765/callback`

### 2) 터미널에서 로그인

```bash
export NOTION_CLIENT_ID="your_client_id"
export NOTION_CLIENT_SECRET="your_client_secret"

justfine-api-sync login
```

그러면 브라우저가 열리고 권한 승인 후, 토큰이 로컬에 저장됩니다.

- 저장 위치: `~/.justfine/config.json`

## 한 번만 설정 (Notion DB 자동 생성)

```bash
justfine-api-sync init \
  --parent-page-id "your_notion_page_id" \
  --database-title "API Spec"
```

`parent-page-id`는 DB를 만들 페이지의 ID입니다.
Notion 페이지 URL의 마지막 ID(하이픈 제거 전/후 둘 다 가능)를 넣으면 됩니다.

이 명령이 끝나면 생성된 `database_id`도 `~/.justfine/config.json`에 저장됩니다.

## 매일 쓰는 명령 (코드 -> Notion 동기화)

서버 프로젝트 루트에서 실행:

```bash
justfine-api-sync sync --repo . --archive-missing
```

동작:

- 새 API: Notion에 생성
- 바뀐 API: Notion 업데이트
- 안 바뀐 API: 스킵
- 코드에서 삭제된 API: 아카이브 (`--archive-missing`)

## 자주 쓰는 옵션

```bash
justfine-api-sync sync --repo . --dry-run
justfine-api-sync sync --repo . --database-id "override_db_id"
justfine-api-sync config
```

## 자동화

예: 5분마다 동기화 (cron)

```bash
*/5 * * * * /usr/local/bin/justfine-api-sync sync --repo "/absolute/path/to/backend" --archive-missing >> /tmp/justfine-api-sync.log 2>&1
```

## 현재 지원 범위

- Spring Java annotation 기반 엔드포인트 추출
- `@GetMapping`, `@PostMapping`, `@PutMapping`, `@DeleteMapping`, `@PatchMapping`, `@RequestMapping`
- `@PathVariable`, `@RequestParam`, `@RequestBody` 단순 추출

## 참고

- 파서는 정규식 기반이라 복잡한 시그니처/커스텀 패턴은 누락될 수 있습니다.
- 필요하면 다음 단계로 OpenAPI(springdoc) 기반 정밀 동기화로 확장 가능합니다.
