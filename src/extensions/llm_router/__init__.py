"""Built-in llm_router — pick an LLM key unit (weighted shuffle or budget)."""

from __future__ import annotations

import random
import time
from typing import Any

_NAME = "llm_router"


def _ext_cfg(config: Any) -> dict[str, Any]:
    exts = getattr(config, "exts", None) or {}
    if not isinstance(exts, dict):
        return {}
    raw = exts.get(_NAME)
    return dict(raw) if isinstance(raw, dict) else {}


def _as_int(value: Any, *, field: str) -> int:
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be an integer, got {value!r}") from exc


def _as_float(value: Any, *, field: str) -> float:
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be a number, got {value!r}") from exc


def parse_units(raw: Any) -> list[dict[str, Any]]:
    """Normalize ``[exts.llm_router.units.<name>]`` tables (unique, mergeable)."""
    if raw is None:
        return []
    if not isinstance(raw, dict):
        raise TypeError(
            "exts.llm_router.units must be a table keyed by unit name "
            "(not an array of tables)"
        )

    units: list[dict[str, Any]] = []
    for key, item in raw.items():
        name = str(key).strip()
        if not isinstance(item, dict):
            raise TypeError(
                f"exts.llm_router.units.{name} must be a table, got {type(item).__name__}"
            )
        if not name or "." in name:
            raise ValueError(
                f"exts.llm_router unit name must be a single segment, got {name!r}"
            )
        unit: dict[str, Any] = {"name": name}
        for field in ("base_url", "model", "api_key", "api_key_env"):
            if field in item:
                val = item[field]
                unit[field] = None if val is None else str(val)
        if "shuffle_weight" in item and item["shuffle_weight"] is not None:
            unit["shuffle_weight"] = _as_float(
                item["shuffle_weight"], field="shuffle_weight"
            )
        else:
            unit["shuffle_weight"] = 1.0
        if "budget_limit" in item and item["budget_limit"] is not None:
            unit["budget_limit"] = _as_int(
                item["budget_limit"], field="budget_limit"
            )
        if "budget_reset" in item and item["budget_reset"] is not None:
            unit["budget_reset"] = _as_int(
                item["budget_reset"], field="budget_reset"
            )
        units.append(unit)
    return units


def storage_key(name: str) -> str:
    return f"{_NAME}.{name}"


def load_record(storage: Any, name: str) -> dict[str, int]:
    raw = {}
    if storage is not None:
        loaded = storage.load(storage_key(name), default={})
        if isinstance(loaded, dict):
            raw = loaded
    used = 0
    last_call = 0
    try:
        used = int(raw.get("used") or 0)
    except (TypeError, ValueError):
        used = 0
    try:
        last_call = int(raw.get("last_call") or 0)
    except (TypeError, ValueError):
        last_call = 0
    return {"used": used, "last_call": last_call}


def pick_shuffle(units: list[dict[str, Any]]) -> dict[str, Any]:
    weighted = [
        (u, float(u.get("shuffle_weight") or 0))
        for u in units
        if float(u.get("shuffle_weight") or 0) > 0
    ]
    if not weighted:
        raise RuntimeError("llm_router: no units with shuffle_weight > 0")
    population = [u for u, _ in weighted]
    weights = [w for _, w in weighted]
    return random.choices(population, weights=weights, k=1)[0]


def unit_exhausted(
    unit: dict[str, Any],
    record: dict[str, int],
    now: int,
) -> bool:
    limit = unit.get("budget_limit")
    if limit is None:
        return False
    if int(record.get("used") or 0) < int(limit):
        return False
    reset = unit.get("budget_reset")
    if reset is None:
        return True
    last_call = int(record.get("last_call") or 0)
    return (now - last_call) < int(reset)


def pick_budget(
    units: list[dict[str, Any]],
    records: dict[str, dict[str, int]],
    now: int,
) -> tuple[dict[str, Any], bool]:
    """Return (unit, reset_used). reset_used means cooldown elapsed; start used at 0."""
    for unit in units:
        name = str(unit["name"])
        rec = records.get(name) or {"used": 0, "last_call": 0}
        if not unit_exhausted(unit, rec, now):
            limit = unit.get("budget_limit")
            reset = unit.get("budget_reset")
            used = int(rec.get("used") or 0)
            last_call = int(rec.get("last_call") or 0)
            reset_used = (
                limit is not None
                and used >= int(limit)
                and reset is not None
                and (now - last_call) >= int(reset)
            )
            return unit, reset_used
    names = ", ".join(str(u["name"]) for u in units)
    raise RuntimeError(f"llm_router: all units exhausted ({names})")


def apply_unit(config: Any, unit: dict[str, Any], baseline: dict[str, Any]) -> None:
    llm = getattr(config, "llm", None)
    if llm is None:
        return
    llm.base_url = unit["base_url"] if "base_url" in unit else baseline["base_url"]
    llm.model = unit["model"] if "model" in unit else baseline["model"]
    if "api_key" in unit or "api_key_env" in unit:
        llm.api_key = unit.get("api_key")
        llm.api_key_env = (
            unit["api_key_env"] if "api_key_env" in unit else baseline["api_key_env"]
        )
    else:
        llm.api_key = baseline["api_key"]
        llm.api_key_env = baseline["api_key_env"]


def _usage_tokens(ctx: dict[str, Any]) -> int:
    response = ctx.get("llm_response")
    if not isinstance(response, dict):
        return 0
    usage = response.get("usage")
    if not isinstance(usage, dict):
        return 0
    try:
        return int(usage.get("total_tokens") or 0)
    except (TypeError, ValueError):
        return 0


def _storage(ctx: dict[str, Any]) -> Any:
    storage = ctx.get("storage")
    if storage is not None:
        return storage
    config = ctx.get("config")
    work_dir = getattr(config, "work_dir", None)
    if work_dir is None:
        return None
    from uzcode.storage import Storage

    return Storage(work_dir)


def register(registry, config) -> None:
    opts = _ext_cfg(config)
    strategy = str(opts.get("strategy") or "shuffle").strip()
    if strategy not in ("shuffle", "budget"):
        raise ValueError(
            f"exts.llm_router.strategy must be 'shuffle' or 'budget', got {strategy!r}"
        )
    units = parse_units(opts.get("units"))
    llm = getattr(config, "llm", None)
    baseline = {
        "base_url": getattr(llm, "base_url", None),
        "model": getattr(llm, "model", None),
        "api_key": getattr(llm, "api_key", None),
        "api_key_env": getattr(llm, "api_key_env", None),
    }

    def before_llm(ctx: dict[str, Any]) -> dict[str, Any]:
        if not units:
            return ctx
        state = ctx.setdefault("state", {})
        extra = state.setdefault("extra", {})
        if not isinstance(extra, dict):
            extra = {}
            state["extra"] = extra
        storage = _storage(ctx)
        now = int(time.time())
        if strategy == "shuffle":
            unit = pick_shuffle(units)
            reset_used = False
        else:
            records = {u["name"]: load_record(storage, u["name"]) for u in units}
            unit, reset_used = pick_budget(units, records, now)
        print(f"llm_router: picked unit {unit['name']} (reset_used={reset_used})")
        apply_unit(ctx.get("config"), unit, baseline)
        extra[_NAME] = {"name": unit["name"], "reset_used": reset_used}
        return ctx

    def after_llm(ctx: dict[str, Any]) -> dict[str, Any]:
        if not units:
            return ctx
        extra = ((ctx.get("state") or {}).get("extra") or {})
        if not isinstance(extra, dict):
            return ctx
        info = extra.get(_NAME)
        if not isinstance(info, dict) or not info.get("name"):
            return ctx
        name = str(info["name"])
        storage = _storage(ctx)
        if storage is None:
            return ctx
        rec = load_record(storage, name)
        used = 0 if info.get("reset_used") else rec["used"]
        used += _usage_tokens(ctx)
        storage.save(
            storage_key(name),
            {"used": used, "last_call": int(time.time())},
        )
        return ctx

    registry.on("before_llm", before_llm, order=50, name=_NAME)
    registry.on("after_llm", after_llm, order=50, name=_NAME)
