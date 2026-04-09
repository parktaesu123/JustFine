from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any, Dict, List


@dataclass
class ApiSpec:
    name: str
    method: str
    endpoint: str
    params: List[Dict[str, Any]]
    request: Dict[str, Any]
    response: Dict[str, Any]
    auth_required: bool
    metadata: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
