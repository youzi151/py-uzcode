"""Discover and load extensions from internal + external roots."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

from uzcode.data import Config
from uzcode.extension.base import HookRegistry


def _internal_extensions_dir() -> Path:
    # src/uzcode/extension/loader.py → parents[2] == src/
    return Path(__file__).resolve().parents[2] / "extensions"


def _external_extensions_dir(work_dir: Path) -> Path:
    return work_dir / ".uzcode" / "exts"


def _resolve_ext_file(root: Path, name: str) -> Path | None:
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
            if child.name in names:
                continue
            if child.name.startswith("_") or child.name.startswith("."):
                continue
            if child.is_dir() and (child / "__init__.py").is_file():
                names.add(child.name)
            elif child.is_file() and child.suffix == ".py":
                names.add(child.stem)
    return sorted(names)


def _parse_order_overrides(raw: Any) -> dict[str, dict[str, int]]:
    """Parse config.extension['order'] → {hook: {name: int}}."""
    if not isinstance(raw, dict):
        return {}
    result: dict[str, dict[str, int]] = {}
    for hook, mapping in raw.items():
        if not isinstance(mapping, dict):
            continue
        result[str(hook)] = {str(k): int(v) for k, v in mapping.items()}
    return result


def _import_ext(name: str, path: Path):
    module_name = f"uzcode_ext_{name}"
    spec = importlib.util.spec_from_file_location(
        module_name,
        path,
        submodule_search_locations=[str(path.parent)] if path.name == "__init__.py" else None,
    )
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load extension {name!r} from {path}")
    module = importlib.util.module_from_spec(spec)
    # Allow package-relative imports inside the ext folder
    sys.modules[module_name] = module
    if path.name == "__init__.py":
        sys.modules[module_name].__path__ = [str(path.parent)]  # type: ignore[attr-defined]
    spec.loader.exec_module(module)
    return module


def load_extensions(work_dir: Path | str, config: Config) -> HookRegistry:
    """Load exts from src/extensions and {work_dir}/.uzcode/exts, then register."""
    work_dir = Path(work_dir).resolve()
    internal = _internal_extensions_dir()
    external = _external_extensions_dir(work_dir)

    ext_cfg = config.extension if isinstance(config.extension, dict) else {}
    order_overrides = _parse_order_overrides(ext_cfg.get("order"))
    registry = HookRegistry(order_overrides=order_overrides)

    discovered = _discover_names(internal, external)
    enable = ext_cfg.get("enable")
    if enable is not None:
        if not isinstance(enable, list):
            raise TypeError("extension.enable must be a list of extension names")
        # make sure each enable name is unique
        enable = list(set(enable))
        enable_names = [str(n) for n in enable]
        missing = [n for n in enable_names if n not in discovered]
        if missing:
            raise FileNotFoundError(
                "Extension not found: "
                + ", ".join(missing)
                + f" (searched {internal} and {external})"
            )
        names = enable_names
    else:
        names = discovered

    for name in names:
        path = _resolve_ext_file(external, name) or _resolve_ext_file(internal, name)
        if path is None:
            raise FileNotFoundError(
                f"Extension {name!r} not found under {external} or {internal}"
            )
        module = _import_ext(name, path)
        register = getattr(module, "register", None)
        if register is None or not callable(register):
            raise AttributeError(
                f"Extension {name!r} ({path}) must define register(registry, config)"
            )
        register(registry, config)

    return registry
