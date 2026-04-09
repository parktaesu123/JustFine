from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Tuple

from .base import BaseParser


class SpringParser(BaseParser):
    framework = "spring"

    def extract_endpoints(self, repo_path: Path) -> List[Dict[str, Any]]:
        java_files = [p for p in repo_path.rglob("*.java") if p.is_file()]
        specs: List[Dict[str, Any]] = []

        for f in java_files:
            text = f.read_text(encoding="utf-8", errors="ignore")
            if "Mapping" not in text:
                continue

            controller_name = self._controller_name(text, f)
            class_mapping = self._class_mapping(text)
            lines = text.splitlines()

            i = 0
            while i < len(lines):
                line = lines[i]
                if not re.search(r"@(GetMapping|PostMapping|PutMapping|DeleteMapping|PatchMapping|RequestMapping)", line):
                    i += 1
                    continue

                ann_block, j = self._collect_annotation_block(lines, i)
                sig, k = self._collect_method_signature(lines, j)
                if "class " in sig:
                    i += 1
                    continue

                method, local_path = self._extract_mapping_value(ann_block)
                return_type, method_name = self._parse_method_signature(sig)
                params, request_body, auth_from_param = self._parse_params(sig)
                full_path = self._normalize_path(class_mapping, local_path)
                auth_required = self._detect_auth(text, ann_block, sig, params, auth_from_param)
                response_status = self._extract_response_status(ann_block, sig)
                response_errors = self._extract_errors(lines, k)

                spec = {
                    "name": method_name or f"{method} {full_path}",
                    "method": method,
                    "endpoint": full_path,
                    "params": params,
                    "request": {
                        "body_type": request_body or "",
                        "schema": {"type": request_body} if request_body else {},
                    },
                    "response": {
                        "type": return_type or "",
                        "http_status": response_status,
                        "errors": response_errors,
                    },
                    "auth_required": auth_required,
                    "metadata": {
                        "framework": "spring",
                        "controller": controller_name,
                        "source_file": str(f),
                    },
                }
                specs.append(spec)
                i = k
            i += 1

        unique: Dict[str, Dict[str, Any]] = {}
        for s in specs:
            unique[f"{s['method']} {s['endpoint']}"] = s
        return list(unique.values())

    def _normalize_path(self, base: str, sub: str) -> str:
        joined = "/".join([base.strip("/"), sub.strip("/")]).strip("/")
        return "/" + joined if joined else "/"

    def _controller_name(self, text: str, f: Path) -> str:
        m = re.search(r"class\s+([A-Za-z0-9_]+)", text)
        return m.group(1) if m else f.stem

    def _class_mapping(self, text: str) -> str:
        for cm in re.finditer(r"@RequestMapping\((.*?)\)\s*(?:public\s+)?class", text, flags=re.S):
            _, pth = self._extract_mapping_value(cm.group(0))
            return pth
        return "/"

    def _collect_annotation_block(self, lines: List[str], start: int) -> Tuple[str, int]:
        ann_block = lines[start]
        j = start + 1
        while j < len(lines) and (lines[j].strip().startswith("@") or ("(" in ann_block and ")" not in ann_block)):
            ann_block += "\n" + lines[j]
            if ")" in lines[j] and not lines[j].strip().startswith("@"):
                break
            j += 1
        return ann_block, j

    def _collect_method_signature(self, lines: List[str], start: int) -> Tuple[str, int]:
        sig = ""
        k = start
        while k < len(lines) and "{" not in lines[k]:
            sig += " " + lines[k].strip()
            if ")" in lines[k]:
                break
            k += 1
        return sig, k

    def _extract_mapping_value(self, annotation_block: str) -> Tuple[str, str]:
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

    def _parse_method_signature(self, line: str) -> Tuple[str, str]:
        m = re.search(r"\b([A-Za-z0-9_<>\[\]?.,]+)\s+([A-Za-z0-9_]+)\s*\(", line)
        if not m:
            return "", ""
        return m.group(1).strip(), m.group(2).strip()

    def _parse_params(self, signature_block: str) -> Tuple[List[Dict[str, Any]], str, bool]:
        inside = ""
        m = re.search(r"\((.*)\)", signature_block, flags=re.S)
        if m:
            inside = m.group(1)

        parts = [p.strip() for p in inside.split(",") if p.strip()]
        params: List[Dict[str, Any]] = []
        request_body = ""
        auth_from_param = False

        for p in parts:
            pname_match = re.search(r"\b([A-Za-z0-9_]+)\s*$", p)
            pname = pname_match.group(1) if pname_match else "unknown"
            ptype_match = re.search(r"(?:@[A-Za-z0-9_()\"=,\s]+\s+)*([A-Za-z0-9_<>\[\].]+)\s+[A-Za-z0-9_]+\s*$", p)
            ptype = ptype_match.group(1).split(".")[-1] if ptype_match else "string"

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

    def _detect_auth(self, class_text: str, ann_block: str, signature: str, params: List[Dict[str, Any]], auth_from_param: bool) -> bool:
        combined = "\n".join([class_text, ann_block, signature]).lower()
        needs = auth_from_param or any(
            key in combined
            for key in ("@preauthorize", "@secured", "@rolesallowed", "@authenticationprincipal", "bearer", "jwt")
        )
        if any(p.get("in") == "header" and ("authorization" in p.get("name", "").lower() or "token" in p.get("name", "").lower()) for p in params):
            needs = True
        return needs

    def _extract_response_status(self, ann_block: str, signature: str) -> str:
        m = re.search(r"@ResponseStatus\(\s*HttpStatus\.([A-Z_]+)", ann_block + " " + signature)
        if not m:
            return ""
        status_map = {
            "OK": "200",
            "CREATED": "201",
            "NO_CONTENT": "204",
            "BAD_REQUEST": "400",
            "UNAUTHORIZED": "401",
            "FORBIDDEN": "403",
            "NOT_FOUND": "404",
            "CONFLICT": "409",
            "INTERNAL_SERVER_ERROR": "500",
        }
        return status_map.get(m.group(1), m.group(1))

    def _extract_errors(self, lines: List[str], body_start: int) -> List[Dict[str, str]]:
        errors: Dict[str, Dict[str, str]] = {}
        brace_depth = 0
        i = body_start
        while i < len(lines):
            line = lines[i]
            brace_depth += line.count("{")
            brace_depth -= line.count("}")
            m = re.search(r"throw\s+new\s+([A-Za-z0-9_]+)", line)
            if m:
                ex = m.group(1)
                errors[ex] = {"name": ex, "error_code": "", "http_status": ""}
            if brace_depth <= 0 and "}" in line:
                break
            i += 1
        return list(errors.values())
