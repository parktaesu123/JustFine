# JustFine API Sync

여러 백엔드 프레임워크의 API 코드를 파싱해 Notion 명세 DB로 동기화하는 CLI 도구입니다.

## 한 줄 요약
- 기존 Spring 전용 파서를 **플러그형 Parser Layer**로 분리했고,
- 공통 동기화 로직은 **Core Engine**으로 고정했으며,
- Notion 출력은 **Output Layer**로 분리해,
- `--framework`만 바꿔서 확장 가능한 구조로 리팩토링했습니다.

---

## 필수 사용 흐름 (사용자 입장)

### 1. 설치 (처음 1회)
```bash
brew tap parktaesu123/justfine https://github.com/parktaesu123/JustFine.git
brew install --HEAD parktaesu123/justfine/justfine-api-sync
```

### 2. 가입/가이드 페이지 열기 (필요 시)
```bash
justfine-api-sync /signup
```

### 3. Notion 연결 (처음 1회)
```bash
justfine-api-sync /login --notion-token "실제_ntn_토큰"
```

실행 중 안내에 따라:
- 부모 페이지 검색어 입력
- 부모 페이지 번호 선택
- 기존 DB 재사용 여부 선택
- 새 DB 생성 시 이름 입력

완료되면 `~/.justfine/config.json`에 토큰/DB 설정이 저장됩니다.

### 4. 동기화 (반복)
```bash
justfine-api-sync /sync --framework spring --archive-missing
```

강제 갱신이 필요하면:
```bash
justfine-api-sync /sync --framework spring --archive-missing --force
```

---

## 리팩토링 결과 (요청사항 반영)

### 1) 3계층 아키텍처 분리
- Parser Layer: 프레임워크별 코드 분석
- Core Engine: spec hash 비교, create/update/skip/archive 처리
- Output Layer: Notion 매핑/업데이트

### 2) Parser 인터페이스 도입
- 공통 메서드: `extract_endpoints(repo_path)`
- 반환값: 통일된 API Spec JSON 리스트

### 3) Spring 파서 분리
- 기존 Spring 파싱 로직을 `SpringParser` 클래스로 이동

### 4) 다중 프레임워크 확장 설계 (Strategy + Plugin)
- 현재 지원: `spring`, `nestjs`, `express`, `django`
- 신규 프레임워크는 Parser Strategy를 등록하면 됨

### 5) CLI 프레임워크 선택
```bash
justfine-api-sync /sync --framework spring
justfine-api-sync /sync --framework nestjs
justfine-api-sync /sync --framework express
justfine-api-sync /sync --framework django
```

### 6) 공통 API Spec 구조
```json
{
  "name": "",
  "method": "",
  "endpoint": "",
  "params": [],
  "request": {},
  "response": {},
  "auth_required": true,
  "metadata": {}
}
```

### 7) /ai 역할 분리
- `/ai`는 코드 구조를 바꾸지 않고 `spec_profile` 설정만 업데이트
- 실제 반영은 `/sync` 실행 시 적용

### 8) 기존 기능 유지
- `/login`, `/connect`, `/sync`, `/ai`, `/signup`
- `spec_hash` 기반 변경 감지
- `--archive-missing`, `--force`

---

## 새로운 디렉토리 구조

```text
justfine/
  spec.py
  parsers/
    base.py
    factory.py
    spring_parser.py
    nestjs_parser.py
    express_parser.py
    django_parser.py
  core/
    engine.py
  output/
    notion_adapter.py
api_to_notion.py
Formula/justfine-api-sync.rb
```

---

## 주요 클래스 설계

### Parser Layer
- `BaseParser` (`justfine/parsers/base.py`)
  - 프레임워크 파서 공통 인터페이스
- `SpringParser`, `NestJsParser`, `ExpressParser`, `DjangoParser`
  - 각 프레임워크 문법 기준 endpoint 추출
- `register_parser(...)`, `create_parser(...)` (`justfine/parsers/factory.py`)
  - `Parser Registry`에 전략(Strategy) 등록 후 런타임 선택
  - Built-in + 외부 Plugin(entry point/ENV) 자동 로드

### Core Engine
- `SyncEngine` (`justfine/core/engine.py`)
  - 공통 hash 계산(`compute_spec_hash`)
  - endpoint key 계산(`spec_key`)
  - 동기화 오케스트레이션(`sync`)
- `SyncResult`
  - `created`, `updated`, `skipped`, `archived` 통계

### Output Layer
- `NotionOutputAdapter` (`justfine/output/notion_adapter.py`)
  - DB 준비(`prepare`)
  - 기존 row 조회(`fetch_existing`)
  - upsert(`upsert`)
  - 누락 archive(`archive_missing`)

---

## 인터페이스 정의 (Python)

```python
# justfine/parsers/base.py
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Dict, List, Any

class BaseParser(ABC):
    framework: str

    @abstractmethod
    def extract_endpoints(self, repo_path: Path) -> List[Dict[str, Any]]:
        """Return unified API spec JSON list."""
        raise NotImplementedError
```

```python
# justfine/core/engine.py
from typing import Protocol, Dict, Any, Set

class OutputAdapter(Protocol):
    def prepare(self) -> None: ...
    def fetch_existing(self) -> Dict[str, Dict[str, Any]]: ...
    def upsert(self, key: str, spec: Dict[str, Any], spec_hash: str, existing_row: Dict[str, Any] | None) -> str: ...
    def archive_missing(self, existing: Dict[str, Dict[str, Any]], seen_keys: Set[str]) -> int: ...
```

---

## 간단 코드 예시

### 1) CLI -> Parser 선택 -> Engine 동기화

```python
parser = create_parser(args.framework)
specs = parser.extract_endpoints(repo)

adapter = NotionOutputAdapter(
    client=NotionClient(notion_token),
    database_id=database_id,
    spec_profile=get_spec_profile(),
    property_map=load_property_config(args.property_map),
)

engine = SyncEngine()
result = engine.sync(
    specs=specs,
    output=adapter,
    archive_missing=args.archive_missing,
    force_update=args.force,
)
```

### 2) /ai는 profile만 갱신

```python
updated = local_rule_profile_update(instruction, current)
ai_updated = None if args.local_only else openai_profile_update(instruction, updated)
save_spec_profile(ai_updated or updated)
```

---

## 새 프레임워크 추가 방법

예: FastAPI 추가

1. `justfine/parsers/fastapi_parser.py` 생성
2. `BaseParser` 상속 후 `extract_endpoints()` 구현
3. 통일 spec JSON으로 반환
4. 플러그인 등록 방식 중 하나 선택
5. `justfine-api-sync /sync --framework fastapi` 실행

이렇게 하면 Core Engine/Output Layer는 그대로 재사용됩니다.

### Plugin 등록 방식

1. Python entry point 방식 (권장)
```toml
[project.entry-points."justfine.parsers"]
fastapi = "my_fastapi_parser.plugin:FastApiParser"
```

2. 환경변수 방식 (빠른 테스트)
```bash
export JUSTFINE_PARSER_PLUGINS="my_fastapi_parser.plugin:FastApiParser"
justfine-api-sync /sync --framework fastapi
```

---

## /sync 옵션 요약

```bash
justfine-api-sync /sync [--framework <parser-name>] [--archive-missing] [--force] [--dry-run]
```

- `--archive-missing`: 코드에서 사라진 endpoint row archive
- `--force`: hash 같아도 강제 업데이트
- `--dry-run`: Notion 반영 없이 파싱 결과 출력

---

## 부가사항

### 설정 확인
```bash
justfine-api-sync config
```

### 설치 제거
```bash
brew uninstall justfine-api-sync
brew untap parktaesu123/justfine
```

### Homebrew cleanup 관련
- `brew cleanup`은 오래된 캐시/구버전 keg 정리입니다.
- 현재 사용 중인 최신 설치 자체를 지우는 명령은 아닙니다.

---

## 트러블슈팅 핵심

- `No Notion token found`
  - `/login` 먼저 실행하거나 `--notion-token` 전달
- `No database id found`
  - `/login` 과정에서 DB 연결 완료 또는 `--database-id` 직접 전달
- `No results found. Try another keyword.`
  - Notion에서 페이지를 먼저 만들고, 통합 권한을 해당 페이지에 연결한 뒤 검색어 재입력
