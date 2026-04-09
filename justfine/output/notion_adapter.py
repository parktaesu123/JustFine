from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Dict, Set


class NotionOutputAdapter:
    """
    Output Layer for Notion.
    Expects client methods: get_database/query_database/create_page/update_page/archive_page
    """

    def __init__(
        self,
        client: Any,
        database_id: str,
        spec_profile: Dict[str, bool],
        property_map: Dict[str, str] | None = None,
    ):
        self.client = client
        self.database_id = database_id
        self.spec_profile = spec_profile
        self.property_map = property_map or {}
        self.db: Dict[str, Any] = {}
        self.aliases: Dict[str, str] = {}

    def prepare(self) -> None:
        self.db = self.client.get_database(self.database_id)
        title_prop = self._find_title_property(self.db)
        aliases = self._build_default_aliases(self.db, title_prop)
        aliases.update(self.property_map)
        self.aliases = aliases

    def fetch_existing(self) -> Dict[str, Dict[str, Any]]:
        title_prop = self.aliases["title"]
        spec_hash_prop = self.aliases.get("Spec Hash")

        existing: Dict[str, Dict[str, Any]] = {}
        cursor = None
        while True:
            data = self.client.query_database(self.database_id, start_cursor=cursor)
            for row in data.get("results", []):
                props = row.get("properties", {})
                title = self._extract_plain_text(props.get(title_prop, {}))
                if not title:
                    continue
                spec_hash = ""
                if spec_hash_prop and spec_hash_prop in props:
                    spec_hash = self._extract_plain_text(props[spec_hash_prop])
                existing[title] = {"page_id": row["id"], "spec_hash": spec_hash}

            if not data.get("has_more"):
                break
            cursor = data.get("next_cursor")

        return existing

    def upsert(self, key: str, spec: Dict[str, Any], spec_hash: str, existing_row: Dict[str, Any] | None) -> str:
        props = self._map_properties(key, spec, spec_hash)
        if existing_row:
            self.client.update_page(existing_row["page_id"], props)
            return "update"
        self.client.create_page(self.database_id, props)
        return "create"

    def archive_missing(self, existing: Dict[str, Dict[str, Any]], seen_keys: Set[str]) -> int:
        archived = 0
        for key, row in existing.items():
            if key in seen_keys:
                continue
            self.client.archive_page(row["page_id"])
            archived += 1
        return archived

    def _map_properties(self, key: str, spec: Dict[str, Any], spec_hash: str) -> Dict[str, Any]:
        now_iso = datetime.now(timezone.utc).isoformat()
        title_prop = self.aliases["title"]

        req_text = self._compact_request(spec)
        resp_text = self._compact_response(spec)

        mapping = {
            "API Name": spec.get("name", ""),
            "HTTP Method": spec.get("method", ""),
            "Endpoint": spec.get("endpoint", ""),
            "Token Required": "Yes" if spec.get("auth_required") else "No",
            "Request": req_text,
            "Response": resp_text,
            "Last Synced At": now_iso,
            "Spec Hash": spec_hash,
            # backward-compatible aliases
            "Method": spec.get("method", ""),
            "Path": spec.get("endpoint", ""),
            "Auth Required": "Yes" if spec.get("auth_required") else "No",
            "Request Body": req_text,
        }

        props: Dict[str, Any] = {
            title_prop: {"title": [{"type": "text", "text": {"content": key[:2000]}}]}
        }

        for logical, value in mapping.items():
            actual = self.aliases.get(logical)
            if not actual:
                continue
            pinfo = self.db["properties"].get(actual)
            if not pinfo:
                continue

            ptype = pinfo["type"]
            if ptype == "rich_text":
                props[actual] = self._rich_text(str(value))
            elif ptype == "select":
                props[actual] = {"select": {"name": str(value)}}
            elif ptype == "multi_select":
                props[actual] = {"multi_select": [{"name": str(value)}]}
            elif ptype == "date":
                props[actual] = {"date": {"start": now_iso}}

        return props

    def _compact_request(self, spec: Dict[str, Any]) -> str:
        req = spec.get("request", {}) or {}
        params = spec.get("params", []) or []
        parts = []
        if params:
            parts.append(f"params={json.dumps(params, ensure_ascii=False)}")
        if req.get("body_type"):
            parts.append(f"bodyType={req.get('body_type')}")
        if req.get("schema"):
            parts.append(f"schema={json.dumps(req.get('schema'), ensure_ascii=False)}")
        if self.spec_profile.get("request_include_headers") and req.get("headers"):
            parts.append(f"headers={json.dumps(req.get('headers'), ensure_ascii=False)}")
        return " | ".join(parts) if parts else "-"

    def _compact_response(self, spec: Dict[str, Any]) -> str:
        resp = spec.get("response", {}) or {}
        parts = []
        if resp.get("type"):
            parts.append(f"type={resp.get('type')}")
        if resp.get("schema"):
            parts.append(f"schema={json.dumps(resp.get('schema'), ensure_ascii=False)}")

        errors = []
        for ex in (resp.get("errors") or []):
            item = {}
            if self.spec_profile.get("response_include_exception_name") and ex.get("name"):
                item["name"] = ex.get("name")
            if self.spec_profile.get("response_include_error_code") and ex.get("error_code"):
                item["errorCode"] = ex.get("error_code")
            if self.spec_profile.get("response_include_http_status") and ex.get("http_status"):
                item["httpStatus"] = ex.get("http_status")
            if item:
                errors.append(item)

        if errors:
            parts.append(f"errors={json.dumps(errors, ensure_ascii=False)}")
        elif self.spec_profile.get("response_include_http_status") and resp.get("http_status"):
            parts.append(f"httpStatus={resp.get('http_status')}")

        return " | ".join(parts) if parts else "-"

    def _find_title_property(self, db: Dict[str, Any]) -> str:
        for prop_name, info in db.get("properties", {}).items():
            if info.get("type") == "title":
                return prop_name
        raise RuntimeError("No title property in Notion database")

    def _build_default_aliases(self, db: Dict[str, Any], title_prop: str) -> Dict[str, str]:
        aliases = {"title": title_prop}
        desired = [
            "API Name",
            "HTTP Method",
            "Endpoint",
            "Token Required",
            "Request",
            "Response",
            "Last Synced At",
            "Spec Hash",
            "Method",
            "Path",
            "Auth Required",
            "Request Body",
        ]
        name_lut = {k.lower(): k for k in db.get("properties", {}).keys()}
        for d in desired:
            if d.lower() in name_lut:
                aliases[d] = name_lut[d.lower()]
        return aliases

    def _extract_plain_text(self, prop: Dict[str, Any]) -> str:
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

    def _rich_text(self, value: str) -> Dict[str, Any]:
        safe = value or ""
        if not safe:
            return {"rich_text": []}
        return {"rich_text": [{"type": "text", "text": {"content": safe[:2000]}}]}
