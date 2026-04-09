from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List

from .base import BaseParser


class DjangoParser(BaseParser):
    framework = "django"

    def extract_endpoints(self, repo_path: Path) -> List[Dict[str, Any]]:
        url_files = [p for p in repo_path.rglob("urls.py") if p.is_file()]
        out: List[Dict[str, Any]] = []
        for f in url_files:
            text = f.read_text(encoding="utf-8", errors="ignore")
            for m in re.finditer(r"path\(\s*['\"]([^'\"]+)['\"]\s*,\s*([A-Za-z0-9_\.]+)", text):
                endpoint = "/" + m.group(1).lstrip("/")
                view_name = m.group(2).split(".")[-1]
                out.append(
                    {
                        "name": view_name,
                        "method": "GET",
                        "endpoint": endpoint,
                        "params": [],
                        "request": {},
                        "response": {},
                        "auth_required": False,
                        "metadata": {"framework": "django", "source_file": str(f)},
                    }
                )
        unique: Dict[str, Dict[str, Any]] = {}
        for s in out:
            unique[f"{s['method']} {s['endpoint']}"] = s
        return list(unique.values())
