"""Discover and load middleware from internal + external roots."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

from uzcode.data import Config
from uzcode.middleware.base import HookRegistry


def _internal_middlewares_dir() -> Path:
    # src/uzcode/middleware/loader.py → parents[2] == src/
    return Path(__file__).resolve().parents[2] / "middlewares"


def _external_middlewares_dir(work_dir: Path) -> Path:
    return work_dir / ".uzcode" / "mids"


def _resolve_mid_file(root: Path, name: str) -> Path | None:
    package = root / name / "__init__.py"
    if package.is_file():
        return package
    module = root / f"{name}.py"
    if module.is_file():
        return module
    return None


def _discover_names(*roots: Path) -> list[str]:
    names: set[str] = set()
    for root in roots:
        if not root.is_dir():
            continue
        for child in root.iterdir():
            if child.name.startswith("_") or child.name.startswith("."):
                continue
            if child.is_dir() and (child / "__init__.py").is_file():
                names.add(child.name)
            elif child.is_file() and child.suffix == ".py":
                names.add(child.stem)
    return sorted(names)


def _parse_order_overrides(raw: Any) -> dict[str, dict[str, int]]:
    """Parse config.middleware['order'] → {hook: {name: int}}."""
    if not isinstance(raw, dict):
        return {}
    result: dict[str, dict[str, int]] = {}
    for hook, mapping in raw.items():
        if not isinstance(mapping, dict):
            continue
        result[str(hook)] = {str(k): int(v) for k, v in mapping.items()}
    return result


def _import_mid(name: str, path: Path):
    module_name = f"uzcode_mid_{name}"
    spec = importlib.util.spec_from_file_location(
        module_name,
        path,
        submodule_search_locations=[str(path.parent)] if path.name == "__init__.py" else None,
    )
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load middleware {name!r} from {path}")
    module = importlib.util.module_from_spec(spec)
    # Allow package-relative imports inside the mid folder
    sys.modules[module_name] = module
    if path.name == "__init__.py":
        sys.modules[module_name].__path__ = [str(path.parent)]  # type: ignore[attr-defined]
    spec.loader.exec_module(module)
    return module


def load_middleware(work_dir: Path | str, config: Config) -> HookRegistry:
    """Load mids from src/middlewares and {work_dir}/.uzcode/mids, then register."""
    work_dir = Path(work_dir).resolve()
    internal = _internal_middlewares_dir()
    external = _external_middlewares_dir(work_dir)

    mw_cfg = config.middleware if isinstance(config.middleware, dict) else {}
    order_overrides = _parse_order_overrides(mw_cfg.get("order"))
    registry = HookRegistry(order_overrides=order_overrides)

    discovered = _discover_names(internal, external)
    enable = mw_cfg.get("enable")
    if enable is not None:
        if not isinstance(enable, list):
            raise TypeError("middleware.enable must be a list of middleware names")
        enable_names = [str(n) for n in enable]
        missing = [n for n in enable_names if n not in discovered]
        if missing:
            raise FileNotFoundError(
                "Middleware not found: "
                + ", ".join(missing)
                + f" (searched {internal} and {external})"
            )
        names = enable_names
    else:
        names = discovered

    for name in names:
        path = _resolve_mid_file(external, name) or _resolve_mid_file(internal, name)
        if path is None:
            raise FileNotFoundError(
                f"Middleware {name!r} not found under {external} or {internal}"
            )
        module = _import_mid(name, path)
        register = getattr(module, "register", None)
        if register is None or not callable(register):
            raise AttributeError(
                f"Middleware {name!r} ({path}) must define register(registry, config)"
            )
        register(registry, config)

    return registry
