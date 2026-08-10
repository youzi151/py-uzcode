---
name: uzcode-create-extension
description: Author uzcode extension packages that register hooks and tools. Use when creating or editing extensions under src/extensions/ or .uzcode/exts/, or when the user asks how to add hooks, tools, preview/confirm, or ext registration.
disable-model-invocation: true
---

# Create uzcode Extension

## Concept

uzcode keeps a thin engine. All advanced behavior (logging, tools, preview/confirm, custom permission, request transforms) lives in **extensions** (exts).

Dual discovery (external wins on name clash):

| Root | Path |
|------|------|
| Built-in | `src/extensions/<name>/` |
| User | `{work_dir}/.uzcode/exts/<name>/` |

Each ext is a package (`<name>/__init__.py`) or module (`<name>.py`) that exports:

```python
def register(registry, config) -> None: ...
```

Enable via `cfg.toml`:

```toml
[extension]
enable = ["logging", "file_cru", "my_ext"]

[extension.order.before_llm]
logging = 10

# Per-extension options (not system keys):
# [exts.my_ext]
# option = "value"
```

`[extension]` is uzcode’s extension feature (`enable`, `order`). Per-ext options live under `[exts.<name>]` (read via `config.exts.get("my_ext")`). If `extension.enable` is omitted, all discovered exts load. Order per hook uses registration `order`, overridable by `[extension.order.<hook>]`.

## Engine flow

```text
START → before_llm → call_llm → after_llm → run_tools → after_tools
                                                              │
          ┌──── auto_loop + last assistant has tool_calls ────┘
          ↓
       before_llm …
          │
          └─ else / stop_loop / max_iterations → on_result → write session artifacts
Exception path → on_error (best-effort) then re-raise
```

## Two layers

| Layer | What | Lifetime |
|-------|------|----------|
| **AgentState** | LangGraph node I/O: `messages`, `iteration`, `stop_loop`, `extra` | Persists across nodes / turns |
| **HookContext (`ctx`)** | Built **per extension call** (and tool handlers) | Dies when the hook returns |

```text
node --AgentState--> engine --ctx--> extension --ctx--> engine --AgentState--> next node
```

Engine writes back **only** `ctx["state"]`. `config` / `tool` / `error` never enter the graph.

## Hooks

| Hook | When | Typical use |
|------|------|-------------|
| `handle_request` | Once at start | mentions, seed skills, mutate request state |
| `before_llm` | Before each LLM call | preprocess messages, inject context |
| `before_call_llm` | After kwargs built, before send | audit/export `ctx["llm_request"]` (no `api_key`); `ctx["request"]` set |
| `after_llm` | After assistant message appended | log, transform response |
| `before_tool` | Per tool call, before execute | preview, custom permission (`ctx["tool"]`) |
| `after_tool` | Per tool call, after execute/skip | rewrite `tool.result`, audit; may set `state.stop_loop` |
| `after_tools` | After all tool_calls this turn | batch logic; may set/clear `state.stop_loop` |
| `on_result` | Graph succeeded, before writeback | final polish |
| `on_error` | Exception (best-effort) | error logging (`ctx["error"]`) |

Register with:

```python
registry.on("before_llm", fn, order=100, name="my_ext")
```

- `name` must be unique **per hook** (usually the ext package name).
- `fn(ctx) -> ctx` — always return the context dict.
- Effective order: `cfg` override if present, else `order`, then `name` as tiebreak.

## Context contract (one shape every hook)

```python
ctx = {
    "state": {                 # AgentState — only this is persisted
        "messages": [...],
        "iteration": int,
        "stop_loop": bool,     # end agent loop after this turn (batch still finishes)
        "extra": {},           # ext-owned scratch (not Message.extra)
    },
    "config": Config,
    "tool": ToolCtx | None,    # set for before_tool / after_tool / handlers
    "error": Exception | None, # set for on_error only
    # before_call_llm only:
    # "llm_request": {...},    # exportable LiteLLM kwargs (no api_key)
    # "request": Request,      # session path via request.path
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

- **`approve`**: run unless a ext sets `tool["skip"]`
- **`ask`**: after `before_tool`, if not already skipped, engine calls the tool’s optional `ask(arguments, ctx) -> bool` if registered; otherwise prompts default `(Y/n)`
- **`custom`**: engine starts with `skip=True` and a deny `result`; ext must clear `skip` (and clear/set `result`) to approve — no Y/n

## Registering tools

Tools have no privilege in the core — exts register them:

```python
def my_ask(arguments: dict, ctx: dict) -> bool:
    # Custom UX from args / tool_cfg(ctx["config"], "my_tool"); return True to approve
    ...

registry.tool(
    "my_tool",
    description="…",
    parameters={  # JSON Schema object
        "type": "object",
        "properties": {"path": {"type": "string"}},
        "required": ["path"],
    },
    handler=my_handler,  # (args: dict, ctx: dict) -> str
    ask=my_ask,  # optional; used only when permission=ask
)
```

Per-tool cfg (`[tools.<name>]`): `enable`, `permission`, `preview_diff`, `retry`, `on_failure`. Default permission when omitted: `ask`. Handlers must not decide permission — use cfg + `before_tool` / optional `ask`. To end the agent loop after this turn: `ctx["state"]["stop_loop"]=True`. Cross-turn ext data: `ctx["state"]["extra"]`.

## Registering actions

Actions are CLI/API side-effects run **after** `prepare`, **before** an optional LLM `run`. They are not LangGraph hooks.

```python
def my_action(ctx: dict) -> dict:
    # ctx: config, request, registry, action, appended (list)
    request = ctx["request"]
    # mutate request.messages; append new Message objects to ctx["appended"]
    return ctx

registry.action("my-action", my_action, order=10)
```

CLI:

| Invocation | Behaviour |
|---|---|
| `uzcode --cfg … --session … --act NAME [NAME…]` | action-then-run |
| `uzcode act NAME [NAME…] --cfg … --session …` | action-only (no LLM) |

Built-in `file_cru` actions: `file-changed`, `file-updated` (mark past `read_file` as `CHANGED`; inject `file_status` as `LATEST`/`MISSING`). Version is keyed by content hash. Tool `file_status` reports current disk (`LATEST` | `MISSING`).

## Authoring checklist

1. Create `{root}/my_ext/__init__.py` (built-in under `src/extensions/`, or user under `.uzcode/exts/`).
2. Implement `register(registry, config)`.
3. Call `registry.on(...)` / `registry.tool(...)` / `registry.action(...)` with unique names.
4. Add `"my_ext"` to `extension.enable` in `.uzcode/cfg.toml`.
5. Optionally set `[extension.order.<hook>]`, `[exts.my_ext]`, and `[tools.<name>]`.

## Minimal example

```python
"""User ext: log after_tools to stderr."""

from __future__ import annotations

import sys
from typing import Any


def register(registry, config) -> None:
    def after_tools(ctx: dict[str, Any]) -> dict[str, Any]:
        state = ctx["state"]
        n = len(state.get("messages") or [])
        print(
            f"[my_ext] after_tools iteration={state.get('iteration')} messages={n}",
            file=sys.stderr,
        )
        return ctx

    registry.on("after_tools", after_tools, order=100, name="my_ext")
```

## Repo examples (read these)

- Hooks only: [`src/extensions/logging/__init__.py`](../../../src/extensions/logging/__init__.py) — `before_llm` / `after_llm`
- Tools + preview: [`src/extensions/file_cru/__init__.py`](../../../src/extensions/file_cru/__init__.py) — `registry.tool` + `before_tool`
- Contracts: [`src/uzcode/extension/base.py`](../../../src/uzcode/extension/base.py), [`src/uzcode/extension/loader.py`](../../../src/uzcode/extension/loader.py), [`src/uzcode/engine.py`](../../../src/uzcode/engine.py)

## Anti-patterns

- Missing or non-callable `register(registry, config)`
- Duplicate `name` on the same hook
- Permission / confirm logic inside tool handlers (use cfg + `before_tool`)
- Expecting engine Y/n when `permission = "custom"`
- Mutating `ctx` without returning it
- Hardcoding Windows-style paths in ext docs or imports
- Writing ext-private data outside `ctx["state"]["extra"]`
- Treating flat keys (`messages`, `tool_name`, …) as ctx — use `state` / `tool`
- Expecting `config` / `tool` / `error` to persist in LangGraph (only `state` does)
