from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Dict, List, Protocol, Set


class OutputAdapter(Protocol):
    def prepare(self) -> None: ...
    def fetch_existing(self) -> Dict[str, Dict[str, Any]]: ...
    def upsert(self, key: str, spec: Dict[str, Any], spec_hash: str, existing_row: Dict[str, Any] | None) -> str: ...
    def archive_missing(self, existing: Dict[str, Dict[str, Any]], seen_keys: Set[str]) -> int: ...


@dataclass
class SyncResult:
    created: int = 0
    updated: int = 0
    skipped: int = 0
    archived: int = 0


class SyncEngine:
    def compute_spec_hash(self, spec: Dict[str, Any]) -> str:
        raw = json.dumps(spec, ensure_ascii=False, sort_keys=True)
        return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]

    def spec_key(self, spec: Dict[str, Any]) -> str:
        method = str(spec.get("method", "")).upper()
        endpoint = str(spec.get("endpoint", ""))
        return f"{method} {endpoint}".strip()

    def sync(
        self,
        specs: List[Dict[str, Any]],
        output: OutputAdapter,
        archive_missing: bool,
        force_update: bool,
    ) -> SyncResult:
        output.prepare()
        existing = output.fetch_existing()
        result = SyncResult()
        seen_keys: Set[str] = set()

        for spec in specs:
            key = self.spec_key(spec)
            spec_hash = self.compute_spec_hash(spec)
            seen_keys.add(key)
            row = existing.get(key)

            if row and (not force_update) and row.get("spec_hash") == spec_hash:
                result.skipped += 1
                print(f"[skip] unchanged {key}")
                continue

            action = output.upsert(key, spec, spec_hash, row)
            if action == "create":
                result.created += 1
                print(f"[create] {key}")
            else:
                result.updated += 1
                print(f"[update] {key}")

        if archive_missing:
            result.archived = output.archive_missing(existing, seen_keys)
            if result.archived:
                print(f"[archive] {result.archived} pages archived")

        return result
