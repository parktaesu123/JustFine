# JustFine API Sync

Spring 서버 코드를 읽어 Notion API 명세를 자동 동기화하는 CLI입니다.

## 1) 설치 (brew)

```bash
brew tap parktaesu123/justfine https://github.com/parktaesu123/JustFine.git
brew install --HEAD parktaesu123/justfine/justfine-api-sync
```

## 2) 로그인 + 연결 (한 번만)

```bash
justfine-api-sync /login --notion-token "실제_ntn_토큰"
```

## 3) 동기화

```bash
justfine-api-sync /sync --archive-missing
```

기존 명세를 새 포맷으로 강제 재반영할 때:

```bash
justfine-api-sync /sync --archive-missing --force
```

## 생성되는 핵심 컬럼 (깔끔 모드)

- `API Name`
- `HTTP Method`
- `Endpoint`
- `Token Required`
- `Request`
- `Response`

## 참고

- 기존 DB에 예전 컬럼이 많으면 그대로 남아 보일 수 있습니다.
- 위 6개만 깔끔하게 쓰려면 새 DB를 만들거나 기존 DB 컬럼을 정리하세요.
