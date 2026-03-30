# JustFine API Sync

Spring 서버 코드를 읽어 Notion API 명세를 자동 동기화하는 CLI입니다.

## 설치 (Homebrew 바로 설치)

```bash
brew tap parktaesu123/justfine https://github.com/parktaesu123/JustFine.git
brew install --HEAD parktaesu123/justfine/justfine-api-sync
```

이미 설치 시도했다면:

```bash
brew uninstall justfine-api-sync || true
brew update
brew install --HEAD parktaesu123/justfine/justfine-api-sync
```

설치 확인:

```bash
justfine-api-sync --help
```

Homebrew 설치가 안 될 경우:

```bash
python3 -m pip install --user "git+https://github.com/parktaesu123/JustFine.git"
python3 -m api_to_notion --help
```

## 설치 (pip만 사용, pipx 불필요)

```bash
python3 -m pip install --user "git+https://github.com/parktaesu123/JustFine.git"
```

## 가장 쉬운 시작

```bash
justfine-api-sync connect
justfine-api-sync sync --archive-missing
```

내부 API 통합 토큰(`ntn_...`)을 이미 갖고 있으면 이렇게 실행:

```bash
justfine-api-sync connect --notion-token "실제_ntn_토큰_전체값"
justfine-api-sync sync --archive-missing
```

주의:
- `"ntn_...."` 같은 예시 문자열을 그대로 넣으면 `401 unauthorized`가 발생합니다.
- `connect` 실행 중 `Page search keyword`는 토큰 입력칸이 아니라 Notion 페이지 검색어 입력칸입니다. (`API` 같은 키워드 입력)
- 토큰이 노출되면 즉시 Notion에서 재발급(rotate)하세요.

그 다음부터는 이 한 줄이면 됩니다.

```bash
justfine-api-sync sync --archive-missing
```

## 설치 (pipx 사용 시)

```bash
pipx install "git+https://github.com/parktaesu123/JustFine.git"
```

```bash
justfine-api-sync connect
justfine-api-sync sync --archive-missing
```

## 자동 생성되는 명세 항목

- 도메인 그룹(`Domain`)
- API 이름(`API Name`)
- 메서드/엔드포인트(`Method`, `Path`)
- 인증 필요 여부/헤더(`Auth Required`, `Headers`)
- 요청 정보(`Params`, `Request Body`, `Request Schema`)
- 응답 정보(`Response`, `Response Schema`)
- 예외 정보(`Exceptions`: 예외명, 에러코드, HTTP 상태코드)

## 기타 명령

```bash
python3 -m api_to_notion /login
python3 -m api_to_notion init --parent-page-id "..." --database-title "API Spec"
python3 -m api_to_notion config
```

## 트러블슈팅

- `API token is invalid (401)`:
  - 토큰이 잘못됐거나 예시 문자열을 넣은 경우입니다.
  - 실제 내부 통합 토큰(`ntn_...`) 전체를 넣어 다시 실행하세요.

- `No Notion token found`:
  - `connect`를 먼저 성공시키거나 `--notion-token` 인자로 전달하세요.

## 참고

- 예외/에러코드/스키마는 코드 기반 추론이므로 프로젝트 구현 패턴에 따라 일부는 보정이 필요할 수 있습니다.
- Spring Java annotation 기반 추출을 지원합니다.
