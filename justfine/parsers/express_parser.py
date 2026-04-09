from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List

from .base import BaseParser


class ExpressParser(BaseParser):
    framework = "express"

    def extract_endpoints(self, repo_path: Path) -> List[Dict[str, Any]]:
        js_files = [p for p in repo_path.rglob("*.js") if p.is_file()] + [p for p in repo_path.rglob("*.ts") if p.is_file()]
        out: List[Dict[str, Any]] = []
        pattern = re.compile(r"(?:app|router)\.(get|post|put|delete|patch)\s*\(\s*['\"]([^'\"]+)['\"]", re.I)
        for f in js_files:
            text = f.read_text(encoding="utf-8", errors="ignore")
            for m in pattern.finditer(text):
                method = m.group(1).upper()
                endpoint = m.group(2)
                auth = "authorization" in text.lower() or "jwt" in text.lower() or "bearer" in text.lower()
                out.append(
                    {
                        "name": f"{method} {endpoint}",
                        "method": method,
                        "endpoint": endpoint,
                        "params": [],
                        "request": {},
                        "response": {},
                        "auth_required": auth,
                        "metadata": {"framework": "express", "source_file": str(f)},
                    }
                )
        unique: Dict[str, Dict[str, Any]] = {}
        for s in out:
            unique[f"{s['method']} {s['endpoint']}"] = s
        return list(unique.values())
