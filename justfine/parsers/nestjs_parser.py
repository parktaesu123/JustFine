from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List

from .base import BaseParser


class NestJsParser(BaseParser):
    framework = "nestjs"

    def extract_endpoints(self, repo_path: Path) -> List[Dict[str, Any]]:
        ts_files = [p for p in repo_path.rglob("*.ts") if p.is_file()]
        out: List[Dict[str, Any]] = []
        for f in ts_files:
            text = f.read_text(encoding="utf-8", errors="ignore")
            if "@Controller" not in text:
                continue
            base = ""
            cm = re.search(r"@Controller\((?:'|\")?([^'\")]+)", text)
            if cm:
                base = cm.group(1)
            for m in re.finditer(r"@(Get|Post|Put|Delete|Patch)\((?:'|\")?([^'\")}]*)", text):
                method = m.group(1).upper()
                sub = m.group(2) or ""
                endpoint = "/" + "/".join([base.strip("/"), sub.strip("/")]).strip("/")
                auth = "@UseGuards" in text or "AuthGuard" in text or "Bearer" in text
                out.append(
                    {
                        "name": f"{method} {endpoint}",
                        "method": method,
                        "endpoint": endpoint if endpoint != "" else "/",
                        "params": [],
                        "request": {},
                        "response": {},
                        "auth_required": auth,
                        "metadata": {"framework": "nestjs", "source_file": str(f)},
                    }
                )
        unique: Dict[str, Dict[str, Any]] = {}
        for s in out:
            unique[f"{s['method']} {s['endpoint']}"] = s
        return list(unique.values())
