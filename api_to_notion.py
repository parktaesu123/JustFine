#!/usr/bin/env python3
import argparse
import base64
import hashlib
import json
import os
import re
import secrets
import sys
import threading
import time
import webbrowser
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import parse_qs, urlencode, urlparse
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

from justfine.core.engine import SyncEngine
from justfine.output.notion_adapter import NotionOutputAdapter
from justfine.parsers.factory import create_parser, get_available_frameworks

NOTION_VERSION = "2022-06-28"
NOTION_API_BASE = "https://api.notion.com/v1"
NOTION_OAUTH_AUTHORIZE = "https://api.notion.com/v1/oauth/authorize"
NOTION_OAUTH_TOKEN = "https://api.notion.com/v1/oauth/token"
CONFIG_DIR = Path.home() / ".justfine"
CONFIG_PATH = CONFIG_DIR / "config.json"
NOTION_INTEGRATION_CREATE_URL = "https://www.notion.so/profile/integrations"
JUSTFINE_SIGNUP_URL = os.getenv("JUSTFINE_SIGNUP_URL", "https://github.com/parktaesu123/JustFine#readme")
DEFAULT_SPEC_PROFILE: Dict[str, bool] = {
    "response_include_http_status": False,
    "response_include_error_code": False,
    "response_include_exception_name": False,
    "request_include_headers": False,
}


def http_json(
    method: str,
    url: str,
    headers: Optional[Dict[str, str]] = None,
    json_payload: Optional[dict] = None,
    form_payload: Optional[Dict[str, str]] = None,
    timeout: int = 30,
) -> dict:
    req_headers = dict(headers or {})
    data = None
    if json_payload is not None:
        req_headers.setdefault("Content-Type", "application/json")
        data = json.dumps(json_payload).encode("utf-8")
    elif form_payload is not None:
        req_headers.setdefault("Content-Type", "application/x-www-form-urlencoded")
        data = urlencode(form_payload).encode("utf-8")

    req = Request(url, data=data, headers=req_headers, method=method)
    try:
        with urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8")
            return json.loads(body) if body else {}
    except HTTPError as e:
        body = e.read().decode("utf-8", errors="ignore")
        raise RuntimeError(f"HTTP error {e.code}: {body}") from e
    except URLError as e:
        raise RuntimeError(f"Network error: {e}") from e


@dataclass
class Endpoint:
    method: str
    path: str
    domain: str
    api_name: str
    controller: str
    summary: str
    auth_required: str
    headers: List[Dict[str, str]]
    params: List[Dict[str, str]]
    request_body: str
    request_schema: str
    response: str
    response_schema: str
    exceptions: List[Dict[str, str]]
    source_file: str

    @property
    def endpoint_key(self) -> str:
        return f"{self.method.upper()} {self.path}"

    @property
    def stable_id(self) -> str:
        raw = f"{self.method.upper()}::{self.path}::{self.controller}"
        return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]

    @property
    def spec_hash(self) -> str:
        payload = {
            "method": self.method,
            "path": self.path,
            "domain": self.domain,
            "api_name": self.api_name,
            "controller": self.controller,
            "summary": self.summary,
            "auth_required": self.auth_required,
            "headers": self.headers,
            "params": self.params,
            "request_body": self.request_body,
            "request_schema": self.request_schema,
            "response": self.response,
            "response_schema": self.response_schema,
            "exceptions": self.exceptions,
        }
        raw = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


@dataclass
class ExistingPage:
    page_id: str
    title: str
    endpoint_id: str
    spec_hash: str


class NotionClient:
    def __init__(self, token: str):
        self.base_url = NOTION_API_BASE
        self.headers = {
            "Authorization": f"Bearer {token}",
            "Notion-Version": NOTION_VERSION,
            "Content-Type": "application/json",
        }

    def _request(self, method: str, path: str, payload: Optional[dict] = None) -> dict:
        url = f"{self.base_url}{path}"
        return http_json(method, url, headers=self.headers, json_payload=payload, timeout=30)

    def get_database(self, database_id: str) -> dict:
        return self._request("GET", f"/databases/{database_id}")

    def create_database(self, parent_page_id: str, title: str) -> dict:
        payload = {
            "parent": {"type": "page_id", "page_id": parent_page_id},
            "title": [{"type": "text", "text": {"content": title}}],
            "properties": {
                "Name": {"title": {}},
                "API Name": {"rich_text": {}},
                "HTTP Method": {"select": {"options": [{"name": "GET"}, {"name": "POST"}, {"name": "PUT"}, {"name": "DELETE"}, {"name": "PATCH"}]}},
                "Endpoint": {"rich_text": {}},
                "Token Required": {"select": {"options": [{"name": "Yes"}, {"name": "No"}]}},
                "Request": {"rich_text": {}},
                "Response": {"rich_text": {}},
                "Last Synced At": {"date": {}},
            },
        }
        return self._request("POST", "/databases", payload)

    def query_database(self, database_id: str, start_cursor: Optional[str] = None) -> dict:
        payload = {}
        if start_cursor:
            payload["start_cursor"] = start_cursor
        return self._request("POST", f"/databases/{database_id}/query", payload)

    def create_page(self, database_id: str, properties: dict) -> dict:
        return self._request(
            "POST",
            "/pages",
            {"parent": {"database_id": database_id}, "properties": properties},
        )

    def update_page(self, page_id: str, properties: dict) -> dict:
        return self._request("PATCH", f"/pages/{page_id}", {"properties": properties})

    def archive_page(self, page_id: str) -> dict:
        return self._request("PATCH", f"/pages/{page_id}", {"archived": True})

    def search(self, query: str, object_type: str, page_size: int = 10) -> List[dict]:
        payload = {
            "query": query,
            "page_size": page_size,
            "filter": {"property": "object", "value": object_type},
        }
        data = self._request("POST", "/search", payload)
        return data.get("results", [])


def load_config() -> dict:
    if not CONFIG_PATH.exists():
        return {}
    try:
        return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_config(cfg: dict) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")


def update_config(patch: dict) -> dict:
    cfg = load_config()
    cfg.update(patch)
    save_config(cfg)
    return cfg


def get_spec_profile() -> Dict[str, bool]:
    cfg = load_config()
    saved = cfg.get("spec_profile", {})
    profile = dict(DEFAULT_SPEC_PROFILE)
    if isinstance(saved, dict):
        for k, v in saved.items():
            if k in profile:
                profile[k] = bool(v)
    return profile


def save_spec_profile(profile: Dict[str, bool]) -> None:
    merged = dict(DEFAULT_SPEC_PROFILE)
    for k, v in profile.items():
        if k in merged:
            merged[k] = bool(v)
    update_config({"spec_profile": merged, "updated_at": datetime.now(timezone.utc).isoformat()})


def extract_first_json_object(text: str) -> Optional[dict]:
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    snippet = text[start : end + 1]
    try:
        obj = json.loads(snippet)
        return obj if isinstance(obj, dict) else None
    except Exception:
        return None


def local_rule_profile_update(instruction: str, current: Dict[str, bool]) -> Dict[str, bool]:
    ins = instruction.lower().strip()
    out = dict(current)

    def want_on(words: List[str]) -> bool:
        return any(w in ins for w in words) and not any(x in ins for x in ["제외", "빼", "remove", "without", "없애"])

    def want_off(words: List[str]) -> bool:
        return any(w in ins for w in words) and any(x in ins for x in ["제외", "빼", "remove", "without", "없애"])

    if want_on(["httpstatus", "http status", "상태코드", "status code"]):
        out["response_include_http_status"] = True
    if want_off(["httpstatus", "http status", "상태코드", "status code"]):
        out["response_include_http_status"] = False

    if want_on(["errorcode", "error code", "에러코드", "오류코드"]):
        out["response_include_error_code"] = True
    if want_off(["errorcode", "error code", "에러코드", "오류코드"]):
        out["response_include_error_code"] = False

    if want_on(["exception", "예외", "예외명"]):
        out["response_include_exception_name"] = True
    if want_off(["exception", "예외", "예외명"]):
        out["response_include_exception_name"] = False

    if want_on(["header", "헤더", "토큰포맷", "authorization format"]):
        out["request_include_headers"] = True
    if want_off(["header", "헤더", "토큰포맷", "authorization format"]):
        out["request_include_headers"] = False

    return out


def openai_profile_update(instruction: str, current: Dict[str, bool]) -> Optional[Dict[str, bool]]:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return None

    base = os.getenv("OPENAI_BASE_URL", "https://api.openai.com").rstrip("/")
    model = os.getenv("JUSTFINE_AI_MODEL", "gpt-4o-mini")
    url = f"{base}/v1/chat/completions"
    schema_keys = list(DEFAULT_SPEC_PROFILE.keys())
    sys_prompt = (
        "You map user's API spec formatting request into boolean toggles.\n"
        f"Return JSON only with keys: {schema_keys}.\n"
        "Do not include any extra keys."
    )
    user_prompt = (
        f"Current profile: {json.dumps(current, ensure_ascii=False)}\n"
        f"User request: {instruction}\n"
        "Return updated profile JSON."
    )
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": sys_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0,
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    try:
        data = http_json("POST", url, headers=headers, json_payload=payload, timeout=30)
    except Exception:
        return None

    choices = data.get("choices", [])
    if not choices:
        return None
    content = (((choices[0] or {}).get("message") or {}).get("content") or "").strip()
    parsed = extract_first_json_object(content)
    if not parsed:
        return None

    updated = dict(current)
    for k in DEFAULT_SPEC_PROFILE.keys():
        if k in parsed:
            updated[k] = bool(parsed[k])
    return updated


def resolve_setting(cli_value: Optional[str], env_key: str, cfg_key: str) -> Optional[str]:
    if cli_value:
        return cli_value
    env = os.getenv(env_key)
    if env:
        return env
    cfg = load_config()
    return cfg.get(cfg_key)


def prompt_secret(label: str) -> str:
    value = sanitize_user_text(input(f"{label}: "))
    if not value:
        raise RuntimeError(f"{label} is required")
    return value


def prompt_optional(label: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    value = sanitize_user_text(input(f"{label}{suffix}: "))
    return value or default


def sanitize_user_text(value: str) -> str:
    if value is None:
        return ""
    cleaned = value.replace("\ufeff", "").strip()
    # Drop broken surrogate characters that can appear during terminal paste.
    cleaned = cleaned.encode("utf-8", "ignore").decode("utf-8", "ignore")
    return cleaned


def pick_from_results(title: str, results: List[dict]) -> dict:
    if not results:
        raise RuntimeError("No results found. Try another keyword.")

    print(f"[select] {title}")
    for i, row in enumerate(results, start=1):
        name = extract_notion_title(row)
        rid = row.get("id", "").replace("-", "")
        print(f"  {i}. {name} ({rid[:8]}...)")

    while True:
        raw = input("Choose number: ").strip()
        if not raw.isdigit():
            print("Enter a valid number.")
            continue
        idx = int(raw)
        if 1 <= idx <= len(results):
            return results[idx - 1]
        print("Out of range. Try again.")


def extract_notion_title(obj: dict) -> str:
    if obj.get("object") == "page":
        props = obj.get("properties", {})
        for p in props.values():
            if p.get("type") == "title":
                return "".join(x.get("plain_text", "") for x in p.get("title", [])) or "Untitled"
        return "Untitled"
    if obj.get("object") == "database":
        return "".join(x.get("plain_text", "") for x in obj.get("title", [])) or "Untitled DB"
    return "Untitled"


def normalize_path(base: str, sub: str) -> str:
    joined = "/".join([base.strip("/"), sub.strip("/")]).strip("/")
    return "/" + joined if joined else "/"


def extract_mapping_value(annotation_block: str) -> Tuple[str, str]:
    ann_match = re.search(r"@(GetMapping|PostMapping|PutMapping|DeleteMapping|PatchMapping|RequestMapping)", annotation_block)
    if not ann_match:
        return "GET", "/"

    ann = ann_match.group(1)
    method = "GET"
    if ann == "RequestMapping":
        m = re.search(r"method\s*=\s*RequestMethod\.([A-Z]+)", annotation_block)
        if m:
            method = m.group(1)
    else:
        method = ann.replace("Mapping", "").upper()

    path = "/"
    v = re.search(r"(?:value|path)\s*=\s*\{?\s*\"([^\"]*)\"", annotation_block)
    if v:
        path = v.group(1)
    else:
        v2 = re.search(
            r"@(?:GetMapping|PostMapping|PutMapping|DeleteMapping|PatchMapping|RequestMapping)\(\s*\"([^\"]*)\"",
            annotation_block,
        )
        if v2:
            path = v2.group(1)

    return method, path


def parse_method_signature(line: str) -> Tuple[str, str]:
    m = re.search(r"\b([A-Za-z0-9_<>\[\]?.,]+)\s+([A-Za-z0-9_]+)\s*\(", line)
    if not m:
        return "", ""
    return m.group(1).strip(), m.group(2).strip()


def simple_type_name(t: str) -> str:
    raw = re.sub(r"[@,\s]", " ", t).strip().split()
    token = raw[-2] if len(raw) >= 2 and raw[-1] in ("final",) else raw[-1] if raw else t
    token = token.replace("...", "").strip()
    if "." in token:
        token = token.split(".")[-1]
    return token


def infer_domain(path: Path, text: str) -> str:
    pkg = re.search(r"package\s+([a-zA-Z0-9_.]+);", text)
    if pkg:
        parts = pkg.group(1).split(".")
        if "domain" in parts:
            i = parts.index("domain")
            if i + 1 < len(parts):
                return parts[i + 1]
        if "controller" in parts:
            i = parts.index("controller")
            if i > 0:
                return parts[i - 1]
    parts = [p for p in path.parts]
    if "domain" in parts:
        i = parts.index("domain")
        if i + 1 < len(parts):
            return parts[i + 1]
    return path.parent.name or "common"


def parse_params(signature_block: str) -> Tuple[List[Dict[str, str]], str, bool]:
    inside = ""
    m = re.search(r"\((.*)\)", signature_block, flags=re.S)
    if m:
        inside = m.group(1)

    parts = [p.strip() for p in inside.split(",") if p.strip()]
    params: List[Dict[str, str]] = []
    request_body = ""
    auth_from_param = False

    for p in parts:
        pname_match = re.search(r"\b([A-Za-z0-9_]+)\s*$", p)
        pname = pname_match.group(1) if pname_match else "unknown"
        ptype_match = re.search(r"(?:@[A-Za-z0-9_()\"=,\s]+\s+)*([A-Za-z0-9_<>\[\].]+)\s+[A-Za-z0-9_]+\s*$", p)
        ptype = simple_type_name(ptype_match.group(1)) if ptype_match else "string"

        if "@PathVariable" in p:
            params.append({"in": "path", "name": pname, "type": ptype})
        elif "@RequestParam" in p:
            params.append({"in": "query", "name": pname, "type": ptype})
        elif "@RequestHeader" in p:
            params.append({"in": "header", "name": pname, "type": ptype})
            if "authorization" in p.lower() or "token" in p.lower():
                auth_from_param = True
        elif "@RequestBody" in p:
            request_body = ptype
        else:
            params.append({"in": "query", "name": pname, "type": ptype})

        if "@AuthenticationPrincipal" in p or "token" in p.lower():
            auth_from_param = True

    return params, request_body, auth_from_param


def java_fields_from_text(text: str) -> Dict[str, str]:
    fields: Dict[str, str] = {}
    for m in re.finditer(
        r"(?:private|protected|public)\s+(?:final\s+)?([A-Za-z0-9_<>\[\].]+)\s+([A-Za-z0-9_]+)\s*;",
        text,
    ):
        ftype = simple_type_name(m.group(1))
        fname = m.group(2)
        fields[fname] = ftype
    return fields


def strip_generic(t: str) -> str:
    t = t.strip()
    t = re.sub(r"\[\]", "", t)
    if "<" in t and ">" in t:
        inner = t[t.find("<") + 1 : t.rfind(">")].strip()
        if inner:
            if "," in inner:
                inner = inner.split(",")[-1].strip()
            return strip_generic(inner)
    return simple_type_name(t)


def build_java_type_index(java_files: List[Path]) -> Tuple[Dict[str, Dict[str, str]], Dict[str, Dict[str, str]]]:
    dto_index: Dict[str, Dict[str, str]] = {}
    exc_index: Dict[str, Dict[str, str]] = {}
    status_map = {
        "BAD_REQUEST": "400",
        "UNAUTHORIZED": "401",
        "FORBIDDEN": "403",
        "NOT_FOUND": "404",
        "CONFLICT": "409",
        "UNPROCESSABLE_ENTITY": "422",
        "INTERNAL_SERVER_ERROR": "500",
    }

    for f in java_files:
        text = f.read_text(encoding="utf-8", errors="ignore")
        cname_match = re.search(r"class\s+([A-Za-z0-9_]+)", text)
        if not cname_match:
            continue
        cname = cname_match.group(1)
        dto_index[cname] = java_fields_from_text(text)

        if "Exception" in cname:
            status = ""
            status_m = re.search(r"HttpStatus\.([A-Z_]+)", text)
            if status_m:
                status = status_map.get(status_m.group(1), status_m.group(1))
            ecode = ""
            code_m = re.search(r"(?:ERROR_CODE|errorCode|code)\s*=\s*\"([A-Z0-9_:-]+)\"", text)
            if code_m:
                ecode = code_m.group(1)
            else:
                token_m = re.search(r"\b([A-Z][A-Z0-9_]*_ERROR)\b", text)
                if token_m:
                    ecode = token_m.group(1)
            exc_index[cname] = {"error_code": ecode, "http_status": status}

    return dto_index, exc_index


def build_schema_for_type(
    type_name: str,
    dto_index: Dict[str, Dict[str, str]],
    depth: int = 0,
    visited: Optional[set] = None,
) -> Dict[str, object]:
    if visited is None:
        visited = set()
    base = strip_generic(type_name)
    if not base or depth > 2:
        return {"type": base or "object"}
    if base in ("String", "Integer", "Long", "Boolean", "Double", "Float", "BigDecimal", "LocalDate", "LocalDateTime"):
        return {"type": base}
    if base in visited:
        return {"type": base}
    visited.add(base)
    fields = dto_index.get(base)
    if not fields:
        return {"type": base}
    children: Dict[str, object] = {}
    for fname, ftype in fields.items():
        children[fname] = build_schema_for_type(ftype, dto_index, depth + 1, visited.copy())
    return {"type": base, "fields": children}


def detect_auth_required(class_text: str, ann_block: str, signature: str, params: List[Dict[str, str]], auth_from_param: bool) -> Tuple[str, List[Dict[str, str]]]:
    combined = "\n".join([class_text, ann_block, signature]).lower()
    needs = auth_from_param or any(
        key in combined
        for key in (
            "@preauthorize",
            "@secured",
            "@rolesallowed",
            "@securityrequirement",
            "@authenticationprincipal",
            "bearer",
            "jwt",
        )
    )
    headers = [{"name": "Authorization", "required": "true", "format": "Bearer <token>"}] if needs else []
    if any(p.get("in") == "header" and ("authorization" in p.get("name", "").lower() or "token" in p.get("name", "").lower()) for p in params):
        needs = True
        if not headers:
            headers = [{"name": "Authorization", "required": "true", "format": "Bearer <token>"}]
    return ("Yes" if needs else "No"), headers


def parse_method_exceptions(signature: str, ann_block: str, body_lines: List[str], exc_index: Dict[str, Dict[str, str]]) -> List[Dict[str, str]]:
    found: Dict[str, Dict[str, str]] = {}
    throws_m = re.search(r"throws\s+([A-Za-z0-9_,\s]+)", signature)
    if throws_m:
        for ex in [x.strip() for x in throws_m.group(1).split(",") if x.strip()]:
            meta = exc_index.get(ex, {})
            found[ex] = {"name": ex, "error_code": meta.get("error_code", ""), "http_status": meta.get("http_status", "")}

    for line in body_lines:
        m = re.search(r"throw\s+new\s+([A-Za-z0-9_]+)", line)
        if m:
            ex = m.group(1)
            meta = exc_index.get(ex, {})
            found[ex] = {"name": ex, "error_code": meta.get("error_code", ""), "http_status": meta.get("http_status", "")}

    for m in re.finditer(r"@ApiResponse\(\s*responseCode\s*=\s*\"([0-9]{3})\"(?:,\s*description\s*=\s*\"([^\"]*)\")?", ann_block):
        code = m.group(1)
        desc = m.group(2) or f"HTTP_{code}_ERROR"
        key = f"ApiResponse{code}"
        found[key] = {"name": desc, "error_code": desc, "http_status": code}

    return list(found.values())


def parse_java_endpoints(root: Path) -> List[Endpoint]:
    endpoints: List[Endpoint] = []
    java_files = [p for p in root.rglob("*.java") if p.is_file()]
    dto_index, exc_index = build_java_type_index(java_files)

    for f in java_files:
        text = f.read_text(encoding="utf-8", errors="ignore")
        if "Mapping" not in text:
            continue

        controller_match = re.search(r"class\s+([A-Za-z0-9_]+)", text)
        controller_name = controller_match.group(1) if controller_match else f.stem
        domain = infer_domain(f, text)

        class_mapping = "/"
        for cm in re.finditer(r"@RequestMapping\((.*?)\)\s*(?:public\s+)?class", text, flags=re.S):
            _, pth = extract_mapping_value(cm.group(0))
            class_mapping = pth
            break

        lines = text.splitlines()
        i = 0
        while i < len(lines):
            line = lines[i]
            if re.search(r"@(GetMapping|PostMapping|PutMapping|DeleteMapping|PatchMapping|RequestMapping)", line):
                ann_block = line
                j = i + 1
                while j < len(lines) and (lines[j].strip().startswith("@") or ("(" in ann_block and ")" not in ann_block)):
                    ann_block += "\n" + lines[j]
                    if ")" in lines[j] and not lines[j].strip().startswith("@"):
                        break
                    j += 1

                sig = ""
                k = j
                while k < len(lines) and "{" not in lines[k]:
                    sig += " " + lines[k].strip()
                    if ")" in lines[k]:
                        break
                    k += 1

                if "class " in sig:
                    i += 1
                    continue

                method, local_path = extract_mapping_value(ann_block)
                return_type, method_name = parse_method_signature(sig)
                params, request_body, auth_from_param = parse_params(sig)
                full_path = normalize_path(class_mapping, local_path)

                body_lines: List[str] = []
                brace_depth = 0
                mline = k
                while mline < len(lines):
                    body_lines.append(lines[mline])
                    brace_depth += lines[mline].count("{")
                    brace_depth -= lines[mline].count("}")
                    if brace_depth <= 0 and "}" in lines[mline]:
                        break
                    mline += 1

                auth_required, headers = detect_auth_required(text, ann_block, sig, params, auth_from_param)
                request_schema_obj = build_schema_for_type(request_body, dto_index) if request_body else {"type": "none"}
                response_schema_obj = build_schema_for_type(return_type, dto_index) if return_type else {"type": "void"}
                exceptions = parse_method_exceptions(sig, ann_block, body_lines, exc_index)

                endpoints.append(
                    Endpoint(
                        method=method,
                        path=full_path,
                        domain=domain,
                        api_name=method_name or f"{method} {full_path}",
                        controller=controller_name,
                        summary=method_name or "",
                        auth_required=auth_required,
                        headers=headers,
                        params=params,
                        request_body=request_body or "",
                        request_schema=json.dumps(request_schema_obj, ensure_ascii=False),
                        response=return_type or "",
                        response_schema=json.dumps(response_schema_obj, ensure_ascii=False),
                        exceptions=exceptions,
                        source_file=str(f),
                    )
                )
                i = k
            i += 1

    unique: Dict[str, Endpoint] = {}
    for ep in endpoints:
        unique[ep.endpoint_key] = ep
    return list(unique.values())


def find_title_property(database: dict) -> str:
    for prop_name, info in database.get("properties", {}).items():
        if info.get("type") == "title":
            return prop_name
    raise RuntimeError("No title property in Notion database")


def rich_text(value: str) -> dict:
    safe = value or ""
    if not safe:
        return {"rich_text": []}
    return {"rich_text": [{"type": "text", "text": {"content": safe[:2000]}}]}


def extract_plain_text(prop: dict) -> str:
    ptype = prop.get("type")
    if ptype == "title":
        return "".join(x.get("plain_text", "") for x in prop.get("title", []))
    if ptype == "rich_text":
        return "".join(x.get("plain_text", "") for x in prop.get("rich_text", []))
    if ptype == "select":
        sel = prop.get("select")
        return sel.get("name", "") if sel else ""
    if ptype == "multi_select":
        return ",".join(x.get("name", "") for x in prop.get("multi_select", []))
    return ""


def compact_request_text(ep: Endpoint, profile: Dict[str, bool]) -> str:
    parts: List[str] = []
    if ep.params:
        parts.append(f"params={json.dumps(ep.params, ensure_ascii=False)}")
    if ep.request_body:
        parts.append(f"bodyType={ep.request_body}")
    if profile.get("request_include_headers") and ep.headers:
        parts.append(f"headers={json.dumps(ep.headers, ensure_ascii=False)}")
    if ep.request_schema and ep.request_schema != "{\"type\": \"none\"}":
        parts.append(f"schema={ep.request_schema}")
    return " | ".join(parts) if parts else "-"


def compact_response_text(ep: Endpoint, profile: Dict[str, bool]) -> str:
    parts: List[str] = []
    if ep.response:
        parts.append(f"type={ep.response}")
    if ep.response_schema and ep.response_schema != "{\"type\": \"void\"}":
        parts.append(f"schema={ep.response_schema}")
    if ep.exceptions:
        reduced: List[Dict[str, str]] = []
        for ex in ep.exceptions:
            item: Dict[str, str] = {}
            if profile.get("response_include_exception_name") and ex.get("name"):
                item["name"] = ex.get("name", "")
            if profile.get("response_include_error_code") and ex.get("error_code"):
                item["errorCode"] = ex.get("error_code", "")
            if profile.get("response_include_http_status") and ex.get("http_status"):
                item["httpStatus"] = ex.get("http_status", "")
            if item:
                reduced.append(item)
        if reduced:
            parts.append(f"errors={json.dumps(reduced, ensure_ascii=False)}")
    return " | ".join(parts) if parts else "-"


def map_properties(ep: Endpoint, db_schema: dict, prop_names: Dict[str, str], profile: Dict[str, bool]) -> dict:
    now_iso = datetime.now(timezone.utc).isoformat()
    props = {}

    title_prop = prop_names["title"]
    props[title_prop] = {
        "title": [{"type": "text", "text": {"content": (ep.api_name or ep.endpoint_key)[:2000]}}]
    }

    request_text = compact_request_text(ep, profile)
    response_text = compact_response_text(ep, profile)

    mapping = {
        "API Name": ep.api_name,
        "HTTP Method": ep.method,
        "Endpoint": ep.path,
        "Token Required": ep.auth_required,
        "Request": request_text,
        "Response": response_text,
        # Backward-compatible optional fields (only mapped if present in DB)
        "Method": ep.method,
        "Path": ep.path,
        "Auth Required": ep.auth_required,
        "Request Body": ep.request_body,
        "Endpoint ID": ep.stable_id,
        "Spec Hash": ep.spec_hash,
        "Last Synced At": now_iso,
    }

    for logical, value in mapping.items():
        actual = prop_names.get(logical)
        if not actual:
            continue

        pinfo = db_schema["properties"].get(actual)
        if not pinfo:
            continue

        ptype = pinfo["type"]
        if ptype == "rich_text":
            props[actual] = rich_text(str(value))
        elif ptype == "select":
            props[actual] = {"select": {"name": str(value)}}
        elif ptype == "multi_select":
            props[actual] = {"multi_select": [{"name": str(value)}]}
        elif ptype == "title":
            continue
        elif ptype == "date":
            props[actual] = {"date": {"start": now_iso}}

    return props


def load_property_config(path: Optional[str]) -> Dict[str, str]:
    if not path:
        return {}
    cfg = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(cfg, dict):
        raise RuntimeError("property-map json must be object")
    return {str(k): str(v) for k, v in cfg.items()}


def build_default_property_aliases(db: dict, title_prop: str) -> Dict[str, str]:
    aliases = {"title": title_prop}
    desired = [
        "API Name",
        "HTTP Method",
        "Endpoint",
        "Token Required",
        "Request",
        "Response",
        "Last Synced At",
        # backward compatibility
        "Method",
        "Path",
        "Auth Required",
        "Request Body",
        "Endpoint ID",
        "Spec Hash",
    ]
    db_props = db.get("properties", {})
    name_lut = {k.lower(): k for k in db_props.keys()}
    for d in desired:
        if d.lower() in name_lut:
            aliases[d] = name_lut[d.lower()]
    return aliases


def extract_existing_pages(client: NotionClient, database_id: str, prop_names: Dict[str, str]) -> List[ExistingPage]:
    title_prop = prop_names["title"]
    endpoint_id_prop = prop_names.get("Endpoint ID")
    spec_hash_prop = prop_names.get("Spec Hash")

    rows: List[ExistingPage] = []
    cursor = None
    while True:
        data = client.query_database(database_id, start_cursor=cursor)
        for row in data.get("results", []):
            props = row.get("properties", {})
            title = extract_plain_text(props.get(title_prop, {"type": "title", "title": []}))

            endpoint_id = ""
            if endpoint_id_prop and endpoint_id_prop in props:
                endpoint_id = extract_plain_text(props[endpoint_id_prop])

            spec_hash = ""
            if spec_hash_prop and spec_hash_prop in props:
                spec_hash = extract_plain_text(props[spec_hash_prop])

            rows.append(
                ExistingPage(
                    page_id=row["id"],
                    title=title,
                    endpoint_id=endpoint_id,
                    spec_hash=spec_hash,
                )
            )

        if not data.get("has_more"):
            break
        cursor = data.get("next_cursor")

    return rows


def sync_to_notion(
    client: NotionClient,
    database_id: str,
    db: dict,
    aliases: Dict[str, str],
    endpoints: List[Endpoint],
    archive_missing: bool,
    force_update: bool,
    profile: Dict[str, bool],
) -> None:
    existing_rows = extract_existing_pages(client, database_id, aliases)
    by_endpoint_id = {r.endpoint_id: r for r in existing_rows if r.endpoint_id}
    by_title = {r.title: r for r in existing_rows if r.title}

    seen_page_ids = set()
    created = 0
    updated = 0
    skipped = 0

    for ep in endpoints:
        props = map_properties(ep, db, aliases, profile)
        row = by_endpoint_id.get(ep.stable_id) or by_title.get(ep.endpoint_key)

        if row:
            seen_page_ids.add(row.page_id)
            if (not force_update) and row.spec_hash and row.spec_hash == ep.spec_hash:
                skipped += 1
                print(f"[skip] unchanged {ep.endpoint_key}")
                continue
            client.update_page(row.page_id, props)
            updated += 1
            print(f"[update] {ep.endpoint_key}")
        else:
            created_row = client.create_page(database_id, props)
            created += 1
            seen_page_ids.add(created_row["id"])
            print(f"[create] {ep.endpoint_key}")

    archived = 0
    if archive_missing:
        for row in existing_rows:
            if row.page_id in seen_page_ids:
                continue
            if not row.endpoint_id and not row.title:
                continue
            client.archive_page(row.page_id)
            archived += 1
            print(f"[archive] {row.title or row.endpoint_id}")

    print(
        "[done]"
        f" created={created}, updated={updated}, skipped={skipped},"
        f" archived={archived}"
    )


def _run_local_callback_server(host: str, port: int, timeout_seconds: int) -> Tuple[str, str]:
    received = {"code": "", "state": ""}

    class OAuthHandler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args) -> None:
            return

        def do_GET(self):
            parsed = urlparse(self.path)
            if parsed.path != "/callback":
                self.send_response(404)
                self.end_headers()
                return

            q = parse_qs(parsed.query)
            received["code"] = (q.get("code") or [""])[0]
            received["state"] = (q.get("state") or [""])[0]

            html = "<html><body><h3>Notion authentication complete.</h3><p>You can close this tab and return to terminal.</p></body></html>"
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(html.encode("utf-8"))))
            self.end_headers()
            self.wfile.write(html.encode("utf-8"))

            threading.Thread(target=self.server.shutdown, daemon=True).start()

    httpd = HTTPServer((host, port), OAuthHandler)
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()

    deadline = time.time() + timeout_seconds
    while time.time() < deadline and not received["code"]:
        time.sleep(0.1)

    if not received["code"]:
        httpd.shutdown()
        raise RuntimeError("OAuth callback timeout. Try login again.")

    return received["code"], received["state"]


def cmd_login(args: argparse.Namespace) -> None:
    direct_token = sanitize_user_text(resolve_setting(getattr(args, "notion_token", None), "NOTION_TOKEN", "notion_token") or "")
    if direct_token:
        if not direct_token.startswith("ntn_"):
            raise RuntimeError("Invalid NOTION_TOKEN format. It should start with 'ntn_'.")
        update_config({"notion_token": direct_token, "updated_at": datetime.now(timezone.utc).isoformat()})
        print("[login] token saved.")
        if not getattr(args, "no_connect", False):
            print("[login] starting database setup...")
            cmd_connect(args)
        return

    client_id = resolve_setting(args.client_id, "NOTION_CLIENT_ID", "client_id")
    client_secret = resolve_setting(args.client_secret, "NOTION_CLIENT_SECRET", "client_secret")
    redirect_uri = resolve_setting(args.redirect_uri, "NOTION_REDIRECT_URI", "redirect_uri") or "http://127.0.0.1:8765/callback"
    client_id = sanitize_user_text(client_id or "")
    client_secret = sanitize_user_text(client_secret or "")
    redirect_uri = sanitize_user_text(redirect_uri)

    if not client_id or not client_secret:
        mode = prompt_optional("Login mode (token/oauth)", "token").lower()
        # If user pasted the actual ntn_ token at mode prompt, accept it directly.
        if mode.startswith("ntn_"):
            notion_token = mode
            if not notion_token.startswith("ntn_"):
                raise RuntimeError("Invalid NOTION_TOKEN format. It should start with 'ntn_'.")
            update_config({"notion_token": notion_token, "updated_at": datetime.now(timezone.utc).isoformat()})
            print("[login] token saved.")
            if not getattr(args, "no_connect", False):
                print("[login] starting database setup...")
                cmd_connect(args)
            return

        if mode in ("token", "t", "1", ""):
            notion_token = prompt_secret("Paste NOTION_TOKEN (ntn_...)")
            if not notion_token.startswith("ntn_"):
                raise RuntimeError("Invalid NOTION_TOKEN format. It should start with 'ntn_'.")
            update_config({"notion_token": notion_token, "updated_at": datetime.now(timezone.utc).isoformat()})
            print("[login] token saved.")
            if not getattr(args, "no_connect", False):
                print("[login] starting database setup...")
                cmd_connect(args)
            return

        print("[login] first-time setup: open Notion integration page.")
        print(f"[login] if needed, create OAuth integration here: {NOTION_INTEGRATION_CREATE_URL}")
        webbrowser.open(NOTION_INTEGRATION_CREATE_URL)
        print("[login] set Redirect URI to: http://127.0.0.1:8765/callback")
        if not client_id:
            client_id = prompt_secret("Paste NOTION_CLIENT_ID")
        if not client_secret:
            client_secret = prompt_secret("Paste NOTION_CLIENT_SECRET")

    if len(client_id) < 10:
        raise RuntimeError("Invalid NOTION_CLIENT_ID format. Copy the exact client id from Notion integration settings.")
    if len(client_secret) < 20:
        raise RuntimeError("Invalid NOTION_CLIENT_SECRET format. Copy the exact client secret from Notion integration settings.")

    parsed = urlparse(redirect_uri)
    if parsed.scheme != "http" or parsed.hostname not in ("127.0.0.1", "localhost") or not parsed.port:
        raise RuntimeError("redirect-uri must be local callback (e.g. http://127.0.0.1:8765/callback)")

    state = secrets.token_urlsafe(24)
    auth_url = f"{NOTION_OAUTH_AUTHORIZE}?" + urlencode(
        {
            "owner": "user",
            "client_id": client_id,
            "response_type": "code",
            "redirect_uri": redirect_uri,
            "state": state,
        }
    )

    print("[login] opening browser for Notion authorization...")
    opened = webbrowser.open(auth_url)
    if not opened:
        print("[login] could not open browser automatically. Open this URL manually:")
        print(auth_url)

    code, got_state = _run_local_callback_server(parsed.hostname or "127.0.0.1", parsed.port, args.timeout)
    if got_state != state:
        raise RuntimeError("OAuth state mismatch. Aborting for safety.")

    basic = base64.b64encode(f"{client_id}:{client_secret}".encode("utf-8")).decode("utf-8")
    token_data = http_json(
        "POST",
        NOTION_OAUTH_TOKEN,
        headers={"Authorization": f"Basic {basic}"},
        form_payload={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
        },
        timeout=30,
    )
    access_token = token_data.get("access_token")
    if not access_token:
        raise RuntimeError("No access_token in Notion token response")

    update_config(
        {
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": redirect_uri,
            "notion_token": access_token,
            "workspace_name": token_data.get("workspace_name", ""),
            "workspace_id": token_data.get("workspace_id", ""),
            "owner_type": (token_data.get("owner") or {}).get("type", ""),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
    )

    print("[login] success. Token saved to ~/.justfine/config.json")
    if not getattr(args, "no_connect", False):
        print("[login] starting database setup...")
        cmd_connect(args)


def cmd_init(args: argparse.Namespace) -> None:
    notion_token = resolve_setting(args.notion_token, "NOTION_TOKEN", "notion_token")
    if not notion_token:
        raise RuntimeError("No Notion token found. Run 'justfine-api-sync login' first.")

    if not args.parent_page_id:
        raise RuntimeError("--parent-page-id is required. Use page URL ID where DB should be created.")

    client = NotionClient(notion_token)
    created = client.create_database(args.parent_page_id, args.database_title)
    db_id = created["id"].replace("-", "")

    update_config({"database_id": db_id})
    print(f"[init] database created: {db_id}")
    print("[init] saved database_id to ~/.justfine/config.json")


def cmd_connect(args: argparse.Namespace) -> None:
    notion_token = resolve_setting(getattr(args, "notion_token", None), "NOTION_TOKEN", "notion_token")
    if not notion_token:
        print("[connect] no token found. starting login flow first...")
        cmd_login(args)
        notion_token = resolve_setting(args.notion_token, "NOTION_TOKEN", "notion_token")
    if not notion_token:
        raise RuntimeError("Login failed. Could not get Notion token.")

    client = NotionClient(notion_token)

    page_keyword = getattr(args, "page_query", None) or prompt_optional("Page search keyword", "API")
    pages = client.search(page_keyword, "page", page_size=10)
    selected_page = pick_from_results("Select parent page to place API DB", pages)
    parent_page_id = (selected_page.get("id") or "").replace("-", "")

    db_keyword = getattr(args, "database_query", None) or prompt_optional("Existing DB search keyword", "API Spec")
    existing_dbs = client.search(db_keyword, "database", page_size=10)
    use_existing = prompt_optional("Use existing DB if found? (y/n)", "y").lower() == "y"
    selected_db_id = ""

    if use_existing and existing_dbs:
        selected_db = pick_from_results("Select existing database (or Ctrl+C to cancel)", existing_dbs)
        selected_db_id = (selected_db.get("id") or "").replace("-", "")
    else:
        db_title = getattr(args, "database_title", None) or prompt_optional("New database title", "API Spec")
        created = client.create_database(parent_page_id, db_title)
        selected_db_id = created["id"].replace("-", "")
        print(f"[connect] created database: {selected_db_id}")

    update_config({"database_id": selected_db_id, "updated_at": datetime.now(timezone.utc).isoformat()})
    print("[connect] completed. You can now run:")
    print("  justfine-api-sync sync")


def cmd_sync(args: argparse.Namespace) -> None:
    repo = Path(args.repo).expanduser().resolve()
    if not repo.exists():
        raise RuntimeError(f"repo path not found: {repo}")

    notion_token = resolve_setting(args.notion_token, "NOTION_TOKEN", "notion_token")
    database_id = resolve_setting(args.database_id, "NOTION_DATABASE_ID", "database_id")

    if not notion_token:
        raise RuntimeError("No Notion token found. Run 'justfine-api-sync login' first or set NOTION_TOKEN.")
    if not database_id:
        raise RuntimeError("No database id found. Run 'justfine-api-sync init' or pass --database-id.")

    try:
        parser = create_parser(args.framework)
    except ValueError as e:
        raise RuntimeError(str(e)) from e
    specs = parser.extract_endpoints(repo)
    print(f"[scan] framework={args.framework} endpoints={len(specs)}")

    if args.dry_run:
        for spec in specs:
            print("[dry-run]", json.dumps(spec, ensure_ascii=False))
        return

    client = NotionClient(notion_token)
    profile = get_spec_profile()
    property_map = load_property_config(args.property_map)

    adapter = NotionOutputAdapter(
        client=client,
        database_id=database_id,
        spec_profile=profile,
        property_map=property_map,
    )
    engine = SyncEngine()
    result = engine.sync(
        specs=specs,
        output=adapter,
        archive_missing=args.archive_missing,
        force_update=args.force,
    )

    print(
        "[done]"
        f" created={result.created}, updated={result.updated},"
        f" skipped={result.skipped}, archived={result.archived}"
    )


def cmd_ai(args: argparse.Namespace) -> None:
    instruction = sanitize_user_text(args.instruction or "")
    if not instruction:
        instruction = prompt_optional("요구사항 입력", "")
    if not instruction:
        raise RuntimeError("Instruction is required.")

    current = get_spec_profile()
    updated = local_rule_profile_update(instruction, current)
    ai_updated = None if args.local_only else openai_profile_update(instruction, updated)
    if ai_updated:
        updated = ai_updated

    save_spec_profile(updated)
    print("[ai] spec profile updated:")
    print(json.dumps(updated, ensure_ascii=False, indent=2))
    print("[ai] run: justfine-api-sync /sync --archive-missing --force")


def cmd_config_show(_args: argparse.Namespace) -> None:
    cfg = load_config()
    if not cfg:
        print("[config] no config found")
        return

    redacted = dict(cfg)
    if redacted.get("notion_token"):
        redacted["notion_token"] = "***"
    if redacted.get("client_secret"):
        redacted["client_secret"] = "***"
    print(json.dumps(redacted, ensure_ascii=False, indent=2))


def cmd_signup(_args: argparse.Namespace) -> None:
    print("[signup] opening onboarding page...")
    opened = webbrowser.open(JUSTFINE_SIGNUP_URL)
    if not opened:
        print("[signup] open this URL manually:")
    print(JUSTFINE_SIGNUP_URL)
    print("[signup] next: justfine-api-sync /login --notion-token \"실제_ntn_토큰\"")


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="justfine-api-sync",
        description="Install-style CLI: login to Notion, init DB, and sync backend API specs",
    )
    sub = ap.add_subparsers(dest="command", required=True)

    login = sub.add_parser("login", aliases=["/login"], help="Easy login (token recommended, oauth optional)")
    login.add_argument("--notion-token", help="Notion internal integration token (ntn_...)")
    login.add_argument("--client-id", help="Notion OAuth client ID")
    login.add_argument("--client-secret", help="Notion OAuth client secret")
    login.add_argument("--redirect-uri", help="OAuth redirect URI (default: http://127.0.0.1:8765/callback)")
    login.add_argument("--timeout", type=int, default=180, help="OAuth wait timeout seconds")
    login.add_argument("--no-connect", action="store_true", help="Only save token/login, skip DB setup")
    login.set_defaults(func=cmd_login)

    connect = sub.add_parser("connect", aliases=["/connect"], help="Interactive one-shot setup (login + pick/create DB)")
    connect.add_argument("--notion-token", help="Notion integration token")
    connect.add_argument("--client-id", help="Notion OAuth client ID")
    connect.add_argument("--client-secret", help="Notion OAuth client secret")
    connect.add_argument("--redirect-uri", help="OAuth redirect URI (default: http://127.0.0.1:8765/callback)")
    connect.add_argument("--timeout", type=int, default=180, help="OAuth wait timeout seconds")
    connect.add_argument("--page-query", help="Keyword to find parent page")
    connect.add_argument("--database-query", help="Keyword to find existing database")
    connect.add_argument("--database-title", help="Title when creating a new database")
    connect.set_defaults(func=cmd_connect)

    init = sub.add_parser("init", help="Create Notion API spec database and save database_id")
    init.add_argument("--notion-token", help="Notion integration token (optional if login done)")
    init.add_argument("--parent-page-id", required=True, help="Parent Notion page ID where DB will be created")
    init.add_argument("--database-title", default="API Spec", help="New Notion database title")
    init.set_defaults(func=cmd_init)

    sync = sub.add_parser("sync", aliases=["/sync"], help="Scan repo and sync API specs to Notion DB")
    sync.add_argument("--repo", default=".", help="Path to source repository (default: current dir)")
    available_frameworks = ", ".join(get_available_frameworks())
    sync.add_argument(
        "--framework",
        default="spring",
        help=f"Backend framework parser (available: {available_frameworks})",
    )
    sync.add_argument("--database-id", help="Notion database ID")
    sync.add_argument("--notion-token", help="Notion integration token")
    sync.add_argument("--property-map", help="JSON file mapping logical fields to Notion property names")
    sync.add_argument("--dry-run", action="store_true", help="Scan only and print extracted endpoints")
    sync.add_argument("--archive-missing", action="store_true", help="Archive Notion rows no longer in code")
    sync.add_argument("--force", action="store_true", help="Force update all endpoints even if unchanged")
    sync.set_defaults(func=cmd_sync)

    ai = sub.add_parser("ai", aliases=["/ai"], help="Apply natural-language spec format requirements")
    ai.add_argument("instruction", nargs="?", help="Example: response에 httpStatus 추가해줘")
    ai.add_argument("--local-only", action="store_true", help="Use local rule parser only (no remote AI call)")
    ai.set_defaults(func=cmd_ai)

    signup = sub.add_parser("signup", aliases=["/signup"], help="Open onboarding page to get required setup info")
    signup.set_defaults(func=cmd_signup)

    config_show = sub.add_parser("config", help="Show saved local config")
    config_show.set_defaults(func=cmd_config_show)

    return ap


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    try:
        args.func(args)
    except RuntimeError as e:
        print(str(e), file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
