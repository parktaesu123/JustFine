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

선행 설정 없이 바로 로그인 명령부터 실행해도 됩니다.
`login`이 필요한 경우 Notion Integration 생성 페이지를 자동으로 열고, 터미널에서 값 입력을 받습니다.

```bash
justfine-api-sync login
# 또는
justfine-api-sync /login
```

로그인 중 안내되는 Redirect URI는 아래로 맞추면 됩니다.

- `http://127.0.0.1:8765/callback`

인증 승인 후 토큰은 로컬에 저장됩니다.

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
