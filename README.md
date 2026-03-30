# JustFine API Sync

Spring 서버 코드를 읽어 Notion API 명세를 자동 동기화하는 CLI입니다.

## 설치

```bash
pipx install "git+https://github.com/parktaesu123/JustFine.git"
```

## 가장 쉬운 시작

```bash
justfine-api-sync connect
justfine-api-sync sync --archive-missing
```

그 다음부터는 이 한 줄이면 됩니다.

```bash
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
justfine-api-sync /login
justfine-api-sync init --parent-page-id "..." --database-title "API Spec"
justfine-api-sync config
```

## 참고

- 예외/에러코드/스키마는 코드 기반 추론이므로 프로젝트 구현 패턴에 따라 일부는 보정이 필요할 수 있습니다.
- Spring Java annotation 기반 추출을 지원합니다.
