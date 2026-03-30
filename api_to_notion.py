#!/usr/bin/env python3
import argparse
import hashlib
import json
import os
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import requests

NOTION_VERSION = "2022-06-28"


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
        self.base_url = "https://api.notion.com/v1"
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


def main() -> None:
    ap = argparse.ArgumentParser(description="Scan Spring endpoints and sync API specs into Notion DB")
    ap.add_argument("--repo", required=True, help="Path to source repository")
    ap.add_argument("--database-id", help="Notion database ID")
    ap.add_argument("--notion-token", default=os.getenv("NOTION_TOKEN"), help="Notion integration token")
    ap.add_argument("--property-map", help="JSON file mapping logical fields to Notion property names")
    ap.add_argument("--dry-run", action="store_true", help="Scan only and print extracted endpoints")
    ap.add_argument(
        "--archive-missing",
        action="store_true",
        help="Archive Notion rows that are no longer present in code",
    )
    args = ap.parse_args()

    repo = Path(args.repo).expanduser().resolve()
    if not repo.exists():
        raise RuntimeError(f"repo path not found: {repo}")

    endpoints = parse_java_endpoints(repo)
    print(f"[scan] found endpoints: {len(endpoints)}")

    if args.dry_run:
        for ep in endpoints:
            print("[dry-run]", json.dumps(asdict(ep), ensure_ascii=False))
        return

    if not args.notion_token:
        raise RuntimeError("Missing notion token. Pass --notion-token or set NOTION_TOKEN")
    if not args.database_id:
        raise RuntimeError("Missing --database-id")

    client = NotionClient(args.notion_token)
    db = client.get_database(args.database_id)
    title_prop = find_title_property(db)

    aliases = build_default_property_aliases(db, title_prop)
    aliases.update(load_property_config(args.property_map))

    sync_to_notion(
        client=client,
        database_id=args.database_id,
        db=db,
        aliases=aliases,
        endpoints=endpoints,
        archive_missing=args.archive_missing,
    )


if __name__ == "__main__":
    main()
