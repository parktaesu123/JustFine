# JustFine API Sync

Spring 서버 코드를 읽어 Notion API 명세를 자동 동기화하는 CLI입니다.

## 설치

```bash
pipx install "git+https://github.com/parktaesu123/JustFine.git"
```

## 가장 쉬운 시작 (ID 복붙 없음)

서버 프로젝트 터미널에서:

```bash
justfine-api-sync connect
justfine-api-sync sync --archive-missing
```

`connect`가 하는 일:

- 필요하면 `login` 자동 진행
- Notion 페이지 검색 후 번호 선택
- 기존 DB 선택 또는 새 DB 자동 생성
- `database_id`를 `~/.justfine/config.json`에 저장

그 다음부터는 아래 한 줄만 쓰면 됩니다.

```bash
justfine-api-sync sync --archive-missing
```

## 다른 명령

```bash
justfine-api-sync /login
justfine-api-sync init --parent-page-id "..." --database-title "API Spec"
justfine-api-sync config
```

## 현재 지원 범위

- Spring Java annotation 기반 엔드포인트 추출
- `@GetMapping`, `@PostMapping`, `@PutMapping`, `@DeleteMapping`, `@PatchMapping`, `@RequestMapping`
- `@PathVariable`, `@RequestParam`, `@RequestBody` 단순 추출
