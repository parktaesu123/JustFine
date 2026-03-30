#!/usr/bin/env python3
import argparse
import hashlib
import json
import os
import re
import secrets
import threading
import time
import webbrowser
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib.parse import parse_qs, urlencode, urlparse

import requests

NOTION_VERSION = "2022-06-28"
NOTION_API_BASE = "https://api.notion.com/v1"
NOTION_OAUTH_AUTHORIZE = "https://api.notion.com/v1/oauth/authorize"
NOTION_OAUTH_TOKEN = "https://api.notion.com/v1/oauth/token"
CONFIG_DIR = Path.home() / ".justfine"
CONFIG_PATH = CONFIG_DIR / "config.json"
NOTION_INTEGRATION_CREATE_URL = "https://www.notion.so/profile/integrations"


@dataclass
class Endpoint:
    method: str
    path: str
    controller: str
    summary: str
    params: List[Dict[str, str]]
    request_body: str
    response: str
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
            "controller": self.controller,
            "summary": self.summary,
            "params": self.params,
            "request_body": self.request_body,
            "response": self.response,
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
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Authorization": f"Bearer {token}",
                "Notion-Version": NOTION_VERSION,
                "Content-Type": "application/json",
            }
        )

    def _request(self, method: str, path: str, payload: Optional[dict] = None) -> dict:
        url = f"{self.base_url}{path}"
        resp = self.session.request(method, url, json=payload, timeout=30)
        if resp.status_code >= 400:
            raise RuntimeError(f"Notion API error {resp.status_code}: {resp.text}")
        return resp.json()

    def get_database(self, database_id: str) -> dict:
        return self._request("GET", f"/databases/{database_id}")

    def create_database(self, parent_page_id: str, title: str) -> dict:
        payload = {
            "parent": {"type": "page_id", "page_id": parent_page_id},
            "title": [{"type": "text", "text": {"content": title}}],
            "properties": {
                "Name": {"title": {}},
                "Method": {"select": {"options": [{"name": "GET"}, {"name": "POST"}, {"name": "PUT"}, {"name": "DELETE"}, {"name": "PATCH"}]}},
                "Path": {"rich_text": {}},
                "Controller": {"rich_text": {}},
                "Summary": {"rich_text": {}},
                "Params": {"rich_text": {}},
                "Request Body": {"rich_text": {}},
                "Response": {"rich_text": {}},
                "Source": {"rich_text": {}},
                "Endpoint ID": {"rich_text": {}},
                "Spec Hash": {"rich_text": {}},
                "Status": {"select": {"options": [{"name": "Active"}, {"name": "Deprecated"}]}},
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


def resolve_setting(cli_value: Optional[str], env_key: str, cfg_key: str) -> Optional[str]:
    if cli_value:
        return cli_value
    env = os.getenv(env_key)
    if env:
        return env
    cfg = load_config()
    return cfg.get(cfg_key)


def prompt_secret(label: str) -> str:
    value = input(f"{label}: ").strip()
    if not value:
        raise RuntimeError(f"{label} is required")
    return value


def prompt_optional(label: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    value = input(f"{label}{suffix}: ").strip()
    return value or default


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
    m = re.search(r"\b([A-Za-z0-9_<>\[\]?]+)\s+([A-Za-z0-9_]+)\s*\(", line)
    if not m:
        return "", ""
    return m.group(1), m.group(2)


def parse_params(signature_block: str) -> Tuple[List[Dict[str, str]], str]:
    inside = ""
    m = re.search(r"\((.*)\)", signature_block, flags=re.S)
    if m:
        inside = m.group(1)

    parts = [p.strip() for p in inside.split(",") if p.strip()]
    params: List[Dict[str, str]] = []
    request_body = ""

    for p in parts:
        if "@PathVariable" in p:
            name = re.search(r"\b([A-Za-z0-9_]+)\s*$", p)
            params.append({"in": "path", "name": name.group(1) if name else "unknown", "type": "string"})
        elif "@RequestParam" in p:
            name = re.search(r"\b([A-Za-z0-9_]+)\s*$", p)
            params.append({"in": "query", "name": name.group(1) if name else "unknown", "type": "string"})
        elif "@RequestBody" in p:
            t = re.search(r"@RequestBody\s+([A-Za-z0-9_<>\[\].]+)", p)
            request_body = t.group(1) if t else "object"

    return params, request_body


def parse_java_endpoints(root: Path) -> List[Endpoint]:
    endpoints: List[Endpoint] = []
    java_files = [p for p in root.rglob("*.java") if p.is_file()]

    for f in java_files:
        text = f.read_text(encoding="utf-8", errors="ignore")
        if "Mapping" not in text:
            continue

        controller_match = re.search(r"class\s+([A-Za-z0-9_]+)", text)
        controller_name = controller_match.group(1) if controller_match else f.stem

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
                while j < len(lines) and (
                    lines[j].strip().startswith("@") or ("(" in ann_block and ")" not in ann_block)
                ):
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
                _, method_name = parse_method_signature(sig)
                params, request_body = parse_params(sig)
                full_path = normalize_path(class_mapping, local_path)

                endpoints.append(
                    Endpoint(
                        method=method,
                        path=full_path,
                        controller=controller_name,
                        summary=method_name or "",
                        params=params,
                        request_body=request_body or "",
                        response="",
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


def map_properties(ep: Endpoint, db_schema: dict, prop_names: Dict[str, str]) -> dict:
    now_iso = datetime.now(timezone.utc).isoformat()
    props = {}

    title_prop = prop_names["title"]
    props[title_prop] = {
        "title": [{"type": "text", "text": {"content": ep.endpoint_key[:2000]}}]
    }

    mapping = {
        "Method": ep.method,
        "Path": ep.path,
        "Controller": ep.controller,
        "Summary": ep.summary,
        "Params": json.dumps(ep.params, ensure_ascii=False),
        "Request Body": ep.request_body,
        "Response": ep.response,
        "Source": ep.source_file,
        "Endpoint ID": ep.stable_id,
        "Spec Hash": ep.spec_hash,
        "Status": "Active",
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
        "Method",
        "Path",
        "Controller",
        "Summary",
        "Params",
        "Request Body",
        "Response",
        "Source",
        "Endpoint ID",
        "Spec Hash",
        "Status",
        "Last Synced At",
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
) -> None:
    existing_rows = extract_existing_pages(client, database_id, aliases)
    by_endpoint_id = {r.endpoint_id: r for r in existing_rows if r.endpoint_id}
    by_title = {r.title: r for r in existing_rows if r.title}

    seen_page_ids = set()
    created = 0
    updated = 0
    skipped = 0

    for ep in endpoints:
        props = map_properties(ep, db, aliases)
        row = by_endpoint_id.get(ep.stable_id) or by_title.get(ep.endpoint_key)

        if row:
            seen_page_ids.add(row.page_id)
            if row.spec_hash and row.spec_hash == ep.spec_hash:
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
    client_id = resolve_setting(args.client_id, "NOTION_CLIENT_ID", "client_id")
    client_secret = resolve_setting(args.client_secret, "NOTION_CLIENT_SECRET", "client_secret")
    redirect_uri = resolve_setting(args.redirect_uri, "NOTION_REDIRECT_URI", "redirect_uri") or "http://127.0.0.1:8765/callback"

    if not client_id or not client_secret:
        print("[login] first-time setup: open Notion integration page.")
        print(f"[login] if needed, create OAuth integration here: {NOTION_INTEGRATION_CREATE_URL}")
        webbrowser.open(NOTION_INTEGRATION_CREATE_URL)
        print("[login] set Redirect URI to: http://127.0.0.1:8765/callback")
        if not client_id:
            client_id = prompt_secret("Paste NOTION_CLIENT_ID")
        if not client_secret:
            client_secret = prompt_secret("Paste NOTION_CLIENT_SECRET")

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

    token_resp = requests.post(
        NOTION_OAUTH_TOKEN,
        auth=(client_id, client_secret),
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
        },
        timeout=30,
    )
    if token_resp.status_code >= 400:
        raise RuntimeError(f"Token exchange failed: {token_resp.status_code} {token_resp.text}")

    token_data = token_resp.json()
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
    notion_token = resolve_setting(args.notion_token, "NOTION_TOKEN", "notion_token")
    if not notion_token:
        print("[connect] no token found. starting login flow first...")
        cmd_login(args)
        notion_token = resolve_setting(args.notion_token, "NOTION_TOKEN", "notion_token")
    if not notion_token:
        raise RuntimeError("Login failed. Could not get Notion token.")

    client = NotionClient(notion_token)

    page_keyword = args.page_query or prompt_optional("Page search keyword", "API")
    pages = client.search(page_keyword, "page", page_size=10)
    selected_page = pick_from_results("Select parent page to place API DB", pages)
    parent_page_id = (selected_page.get("id") or "").replace("-", "")

    db_keyword = args.database_query or prompt_optional("Existing DB search keyword", "API Spec")
    existing_dbs = client.search(db_keyword, "database", page_size=10)
    use_existing = prompt_optional("Use existing DB if found? (y/n)", "y").lower() == "y"
    selected_db_id = ""

    if use_existing and existing_dbs:
        selected_db = pick_from_results("Select existing database (or Ctrl+C to cancel)", existing_dbs)
        selected_db_id = (selected_db.get("id") or "").replace("-", "")
    else:
        db_title = args.database_title or prompt_optional("New database title", "API Spec")
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

    endpoints = parse_java_endpoints(repo)
    print(f"[scan] found endpoints: {len(endpoints)}")

    if args.dry_run:
        for ep in endpoints:
            print("[dry-run]", json.dumps(asdict(ep), ensure_ascii=False))
        return

    client = NotionClient(notion_token)
    db = client.get_database(database_id)
    title_prop = find_title_property(db)

    aliases = build_default_property_aliases(db, title_prop)
    aliases.update(load_property_config(args.property_map))

    sync_to_notion(
        client=client,
        database_id=database_id,
        db=db,
        aliases=aliases,
        endpoints=endpoints,
        archive_missing=args.archive_missing,
    )


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


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="justfine-api-sync",
        description="Install-style CLI: login to Notion, init DB, and sync Spring API specs",
    )
    sub = ap.add_subparsers(dest="command", required=True)

    login = sub.add_parser("login", aliases=["/login"], help="OAuth login via browser redirect")
    login.add_argument("--client-id", help="Notion OAuth client ID")
    login.add_argument("--client-secret", help="Notion OAuth client secret")
    login.add_argument("--redirect-uri", help="OAuth redirect URI (default: http://127.0.0.1:8765/callback)")
    login.add_argument("--timeout", type=int, default=180, help="OAuth wait timeout seconds")
    login.set_defaults(func=cmd_login)

    connect = sub.add_parser("connect", help="Interactive one-shot setup (login + pick/create DB)")
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

    sync = sub.add_parser("sync", help="Scan repo and sync API specs to Notion DB")
    sync.add_argument("--repo", default=".", help="Path to source repository (default: current dir)")
    sync.add_argument("--database-id", help="Notion database ID")
    sync.add_argument("--notion-token", help="Notion integration token")
    sync.add_argument("--property-map", help="JSON file mapping logical fields to Notion property names")
    sync.add_argument("--dry-run", action="store_true", help="Scan only and print extracted endpoints")
    sync.add_argument("--archive-missing", action="store_true", help="Archive Notion rows no longer in code")
    sync.set_defaults(func=cmd_sync)

    config_show = sub.add_parser("config", help="Show saved local config")
    config_show.set_defaults(func=cmd_config_show)

    return ap


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
