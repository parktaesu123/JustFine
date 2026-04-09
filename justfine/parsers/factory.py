from __future__ import annotations

import os
from importlib import import_module
from typing import Dict, List, Type

from .base import BaseParser
from .django_parser import DjangoParser
from .express_parser import ExpressParser
from .nestjs_parser import NestJsParser
from .spring_parser import SpringParser

try:
    from importlib.metadata import entry_points
except Exception:  # pragma: no cover
    entry_points = None


_registry: Dict[str, Type[BaseParser]] = {}
_initialized = False


BUILTIN_PARSERS: List[Type[BaseParser]] = [
    SpringParser,
    NestJsParser,
    ExpressParser,
    DjangoParser,
]


def register_parser(framework: str, parser_cls: Type[BaseParser], override: bool = False) -> None:
    key = (framework or "").strip().lower()
    if not key:
        raise ValueError("framework must not be empty")
    if not issubclass(parser_cls, BaseParser):
        raise TypeError(f"{parser_cls} must inherit BaseParser")
    if key in _registry and not override:
        raise ValueError(f"Parser already registered for framework: {framework}")
    _registry[key] = parser_cls


def _register_builtins() -> None:
    for parser_cls in BUILTIN_PARSERS:
        framework = getattr(parser_cls, "framework", "").strip().lower()
        if not framework:
            continue
        _registry[framework] = parser_cls


def _load_entrypoint_plugins() -> None:
    if entry_points is None:
        return
    try:
        eps = entry_points()
        if hasattr(eps, "select"):
            group = eps.select(group="justfine.parsers")
        else:  # pragma: no cover (older Python compatibility)
            group = eps.get("justfine.parsers", [])

        for ep in group:
            try:
                parser_cls = ep.load()
                framework = getattr(parser_cls, "framework", ep.name).strip().lower()
                register_parser(framework, parser_cls, override=False)
            except Exception:
                continue
    except Exception:
        return


def _load_env_plugins() -> None:
    """
    Load parsers from JUSTFINE_PARSER_PLUGINS.
    Format: "package.module:ClassName,another.module:ParserClass"
    """
    raw = os.getenv("JUSTFINE_PARSER_PLUGINS", "").strip()
    if not raw:
        return

    for item in [x.strip() for x in raw.split(",") if x.strip()]:
        if ":" not in item:
            continue
        module_name, class_name = item.split(":", 1)
        try:
            mod = import_module(module_name)
            parser_cls = getattr(mod, class_name)
            framework = getattr(parser_cls, "framework", class_name).strip().lower()
            register_parser(framework, parser_cls, override=False)
        except Exception:
            continue


def _ensure_initialized() -> None:
    global _initialized
    if _initialized:
        return
    _register_builtins()
    _load_entrypoint_plugins()
    _load_env_plugins()
    _initialized = True


def create_parser(framework: str) -> BaseParser:
    _ensure_initialized()
    key = (framework or "spring").lower().strip()
    parser_cls = _registry.get(key)
    if not parser_cls:
        available = ", ".join(get_available_frameworks())
        raise ValueError(f"Unsupported framework: {framework}. Available: {available}")
    return parser_cls()


def get_available_frameworks() -> List[str]:
    _ensure_initialized()
    return sorted(_registry.keys())
