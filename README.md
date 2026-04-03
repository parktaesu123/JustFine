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

## 4) 자연어로 명세 포맷 변경 (AI)

예시:

```bash
justfine-api-sync /ai "response에 httpStatus도 추가해줘"
justfine-api-sync /sync --archive-missing --force
```

설명:
- `/ai`가 요구사항을 해석해서 명세 포맷 프로필을 업데이트합니다.
- 다음 `/sync`부터 반영됩니다.

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
