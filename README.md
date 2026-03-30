# JustFine API Sync

Spring 서버 코드를 읽어 Notion API 명세를 자동 동기화하는 CLI입니다.

## 1) 설치 (brew)

```bash
brew tap parktaesu123/justfine https://github.com/parktaesu123/JustFine.git
brew install --HEAD parktaesu123/justfine/justfine-api-sync
```

## 2) 로그인 + 연결 (한 번만)

가장 쉬운 방법:

```bash
justfine-api-sync /login
```

권장: 토큰을 바로 넣는 방법

```bash
justfine-api-sync /login --notion-token "실제_ntn_토큰"
```

`/login`이 하는 일:

- Notion 토큰 저장
- 이어서 페이지/DB 선택 또는 생성까지 진행
- 설정을 `~/.justfine/config.json`에 저장

## 3) 동기화

```bash
justfine-api-sync /sync --archive-missing
```

## 실수 방지

- `--notion-token "ntn_...."` 처럼 예시 문자열 그대로 넣으면 실패합니다.
- `Page search keyword`는 토큰 입력칸이 아니라 Notion 페이지 검색어 입력칸입니다.
- 토큰이 노출되면 즉시 Notion에서 재발급(rotate)하세요.

## 주요 명령

```bash
justfine-api-sync /login
justfine-api-sync /connect
justfine-api-sync /sync
justfine-api-sync config
```
