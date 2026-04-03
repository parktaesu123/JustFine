# JustFine API Sync

Spring 서버 코드를 읽어 Notion API 명세를 자동으로 생성/업데이트하는 CLI입니다.

## 이 도구로 할 수 있는 것
- 코드에서 API 엔드포인트를 스캔
- Notion DB에 명세 생성/수정
- 코드에서 사라진 API는 아카이브 (`--archive-missing`)
- 자연어 명령으로 명세 포맷 변경 (`/ai`)

---

## 필수 사용 흐름 (처음 1회 + 반복)

### 1. 설치 (처음 1회)
```bash
brew tap parktaesu123/justfine https://github.com/parktaesu123/JustFine.git
brew install --HEAD parktaesu123/justfine/justfine-api-sync
```

### 2. 가입/설정 안내 열기 (처음 1회, 선택)
필요한 정보 얻는 페이지를 바로 엽니다.

```bash
justfine-api-sync /signup
```

### 3. Notion 연결 (처음 1회)
Notion 내부 통합 토큰(`ntn_...`)을 준비한 뒤 실행:

```bash
justfine-api-sync /login --notion-token "실제_ntn_토큰"
```

실행 중에 나오는 입력:
- `Page search keyword [API]`: 명세를 둘 Notion 페이지 제목 검색어 입력 (예: `api`)
- 페이지 목록이 나오면 번호 선택
- 기존 DB를 재사용할지 물으면 선택 (`y`/`n`)
- 새로 만들면 DB 이름 입력

완료되면 `~/.justfine/config.json`에 연결 정보가 저장됩니다.

### 4. 동기화 (매번 반복)
서버 프로젝트 루트에서:

```bash
justfine-api-sync /sync --archive-missing
```

코드가 바뀌면 이 명령만 다시 실행하면 됩니다.

---

## 강제 전체 갱신 (포맷 변경 후 권장)
기존 페이지까지 전부 다시 반영하려면:

```bash
justfine-api-sync /sync --archive-missing --force
```

---

## 현재 기본 명세 컬럼 (깔끔 모드)
- `API Name`
- `HTTP Method`
- `Endpoint`
- `Token Required`
- `Request`
- `Response`

---

## 부가 기능

### 자연어로 명세 포맷 변경
예: response에 상태코드 포함

```bash
justfine-api-sync /ai "response에 httpStatus도 추가해줘"
justfine-api-sync /sync --archive-missing --force
```

설명:
- `/ai`가 요구사항을 명세 포맷 프로필에 반영
- 다음 `/sync`부터 반영
- `--force`를 붙이면 기존 데이터도 즉시 재반영

### 현재 저장된 연결 정보 확인
```bash
justfine-api-sync config
```

---

## 자주 겪는 문제

### 1) `No database id found`
연결이 아직 안 된 상태입니다.

```bash
justfine-api-sync /login --notion-token "실제_ntn_토큰"
```

### 2) `API token is invalid (401)`
토큰 값이 잘못됐거나 만료/회수됨.
- Notion에서 새 토큰 재발급 후 다시 `/login`
- `--notion-token "ntn_...."` 예시 문자열을 그대로 넣으면 실패

### 3) Notion이 안 바뀌는 것처럼 보일 때
- 다른 DB를 보고 있을 수 있음 (`justfine-api-sync config` 확인)
- 강제 반영으로 확인:
```bash
justfine-api-sync /sync --archive-missing --force
```

---

## 보안 주의
- 토큰(`ntn_...`)을 채팅/커밋/로그에 노출하지 마세요.
- 노출 시 즉시 Notion에서 토큰 재발급(rotate)하세요.
