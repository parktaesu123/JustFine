from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Dict, List, Any


class BaseParser(ABC):
    framework: str

    @abstractmethod
    def extract_endpoints(self, repo_path: Path) -> List[Dict[str, Any]]:
        """Return unified API spec JSON list."""
        raise NotImplementedError
