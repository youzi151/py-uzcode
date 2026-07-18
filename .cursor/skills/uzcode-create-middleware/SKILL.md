---
name: uzcode-create-middleware
description: Author uzcode middleware packages that register hooks and tools. Use when creating or editing middleware under src/middlewares/ or .uzcode/mids/, or when the user asks how to add hooks, tools, preview/confirm, or mid registration.
disable-model-invocation: true
---

# Create uzcode Middleware

## Concept

uzcode keeps a thin engine. All advanced behavior (logging, tools, preview/confirm, custom permission, request transforms) lives in **middleware** (mids).

Dual discovery (external wins on name clash):

| Root | Path |
|------|------|
| Built-in | `src/middlewares/<name>/` |
| User | `{work_dir}/.uzcode/mids/<name>/` |

Each mid is a package (`<name>/__init__.py`) or module (`<name>.py`) that exports:

```python
def register(registry, config) -> None: ...
```

Enable via `cfg.toml`:

```toml
[middleware]
enable = ["logging", "file_cru", "my_mid"]

[middleware.order.before_llm]
logging = 10
```

If `middleware.enable` is omitted, all discovered mids load. Order per hook uses registration `order`, overridable by `[middleware.order.<hook>]`.

## Engine flow

```text
START → before_llm → call_llm → after_llm → run_tools → after_tools
                                                              │
                    ┌──── auto_loop + last assistant has tool_calls ────┘
                    ↓
                 before_llm …
                    │
                    └─ else / stop_loop / max_iterations → on_result → write req.toml
Exception path → on_error (best-effort) then re-raise
```

## Two layers

| Layer | What | Lifetime |
|-------|------|----------|
| **AgentState** | LangGraph node I/O: `messages`, `iteration`, `stop_loop`, `extra` | Persists across nodes / turns |
| **HookContext (`ctx`)** | Built **per middleware call** (and tool handlers) | Dies when the hook returns |

```text
node --AgentState--> engine --ctx--> middleware --ctx--> engine --AgentState--> next node
```

Engine writes back **only** `ctx["state"]`. `config` / `tool` / `error` never enter the graph.

## Hooks

| Hook | When | Typical use |
|------|------|-------------|
| `before_llm` | Before each LLM call | preprocess messages, inject context |
| `after_llm` | After assistant message appended | log, transform response |
| `before_tool` | Per tool call, before execute | preview, custom permission (`ctx["tool"]`) |
| `after_tool` | Per tool call, after execute/skip | rewrite `tool.result`, audit; may set `state.stop_loop` |
| `after_tools` | After all tool_calls this turn | batch logic; may set/clear `state.stop_loop` |
| `on_result` | Graph succeeded, before writeback | final polish |
| `on_error` | Exception (best-effort) | error logging (`ctx["error"]`) |

Register with:

```python
registry.on("before_llm", fn, order=100, name="my_mid")
```

- `name` must be unique **per hook** (usually the mid package name).
- `fn(ctx) -> ctx` — always return the context dict.
- Effective order: `cfg` override if present, else `order`, then `name` as tiebreak.

## Context contract (one shape every hook)

```python
ctx = {
    "state": {                 # AgentState — only this is persisted
        "messages": [...],
        "iteration": int,
        "stop_loop": bool,     # end agent loop after this turn (batch still finishes)
        "extra": {},           # mid-owned scratch (not Message.extra)
    },
    "config": Config,
    "tool": ToolCtx | None,    # set for before_tool / after_tool / handlers
    "error": Exception | None, # set for on_error only
}
```

`ToolCtx` when present:

| Key | Notes |
|-----|-------|
| `name`, `arguments`, `tool_call_id` | current call |
| `permission` | `ask` \| `approve` \| `custom` from cfg |
| `work_dir` | agent work directory |
| `skip` | if true, engine does not execute the tool |
| `result` | skip message or tool output string |

```python
ctx["state"]["stop_loop"] = True
ctx["state"]["extra"]["flag"] = True
del ctx["state"]["extra"]["tmp"]
ctx["tool"]["skip"] = True          # only when tool is not None
```

Permission behavior (engine):

- **`approve`**: run unless a mid sets `tool["skip"]`
- **`ask`**: after `before_tool`, engine prompts `(Y/n)` if not already skipped
- **`custom`**: engine starts with `skip=True` and a deny `result`; mid must clear `skip` (and clear/set `result`) to approve — no Y/n

## Registering tools

Tools have no privilege in the core — mids register them:

```python
registry.tool(
    "my_tool",
    description="…",
    parameters={  # JSON Schema object
        "type": "object",
        "properties": {"path": {"type": "string"}},
        "required": ["path"],
    },
    handler=my_handler,  # (args: dict, ctx: dict) -> str
)
```

Per-tool cfg (`[tools.<name>]`): `enable`, `permission`, `preview_diff`, `retry`, `on_failure`. Default permission when omitted: `ask`. Handlers must not decide permission — use cfg + `before_tool`. To end the agent loop after this turn: `ctx["state"]["stop_loop"]=True`. Cross-turn mid data: `ctx["state"]["extra"]`.

## Authoring checklist

1. Create `{root}/my_mid/__init__.py` (built-in under `src/middlewares/`, or user under `.uzcode/mids/`).
2. Implement `register(registry, config)`.
3. Call `registry.on(...)` / `registry.tool(...)` with unique hook `name=`.
4. Add `"my_mid"` to `middleware.enable` in `.uzcode/cfg.toml`.
5. Optionally set `[middleware.order.<hook>]` and `[tools.<name>]`.

## Minimal example

```python
"""User mid: log after_tools to stderr."""

from __future__ import annotations

import sys
from typing import Any


def register(registry, config) -> None:
    def after_tools(ctx: dict[str, Any]) -> dict[str, Any]:
        state = ctx["state"]
        n = len(state.get("messages") or [])
        print(
            f"[my_mid] after_tools iteration={state.get('iteration')} messages={n}",
            file=sys.stderr,
        )
        return ctx

    registry.on("after_tools", after_tools, order=100, name="my_mid")
```

## Repo examples (read these)

- Hooks only: [`src/middlewares/logging/__init__.py`](../../../src/middlewares/logging/__init__.py) — `before_llm` / `after_llm`
- Tools + preview: [`src/middlewares/file_cru/__init__.py`](../../../src/middlewares/file_cru/__init__.py) — `registry.tool` + `before_tool`
- Contracts: [`src/uzcode/middleware/base.py`](../../../src/uzcode/middleware/base.py), [`src/uzcode/middleware/loader.py`](../../../src/uzcode/middleware/loader.py), [`src/uzcode/engine.py`](../../../src/uzcode/engine.py)

## Anti-patterns

- Missing or non-callable `register(registry, config)`
- Duplicate `name` on the same hook
- Permission / confirm logic inside tool handlers (use cfg + `before_tool`)
- Expecting engine Y/n when `permission = "custom"`
- Mutating `ctx` without returning it
- Hardcoding Windows-style paths in mid docs or imports
- Writing mid-private data outside `ctx["state"]["extra"]`
- Treating flat keys (`messages`, `tool_name`, …) as ctx — use `state` / `tool`
- Expecting `config` / `tool` / `error` to persist in LangGraph (only `state` does)
