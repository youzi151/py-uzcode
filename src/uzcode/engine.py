"""Thin core engine: LangGraph workflow + LiteLLM + hook registry + tools."""

from __future__ import annotations

import json
import os
import re
import sys
from typing import Any, TypedDict

import litellm
from langgraph.graph import END, START, StateGraph

from uzcode.data import Config, Message, Session
from uzcode.extension.base import HookRegistry
from uzcode.tools.registry import tool_cfg, tool_enabled, tool_permission
from uzcode.cfg import PrepareMeta

_MENTION_RE = re.compile(r"@\{([^}:]+):([^}]*)\}")


def _ask_user_yn(tool_name: str, arguments: dict[str, Any]) -> bool:
    """Prompt on stderr/stdin: Enter or Y = yes, n = no."""
    print(
        f"Approve tool {tool_name!r} args={arguments!r}? (Y/n) ",
        file=sys.stderr,
        end="",
    )
    sys.stderr.flush()
    try:
        answer = input().strip().lower()
    except EOFError:
        return False
    return answer in ("", "y", "yes")


class AgentState(TypedDict):
    """LangGraph node I/O. Ext scratch lives in ``extra``."""

    messages: list[dict[str, Any]]
    messagelib: dict[str, dict[str, Any]]
    skills_enabled: list[str]
    mentions: list[dict[str, Any]]
    iteration: int
    stop_loop: bool
    extra: dict[str, Any]


class ToolCtx(TypedDict):
    """Per-tool ephemeral fields; only present on before_tool / after_tool / handlers."""

    name: str
    arguments: dict[str, Any]
    tool_call_id: str
    permission: str
    work_dir: str
    skip: bool
    result: str | None


def _copy_mentions(mentions: list[Any] | None) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for item in mentions or []:
        if not isinstance(item, dict):
            continue
        entry = dict(item)
        entry["handled"] = list(entry.get("handled") or [])
        out.append(entry)
    return out


def _copy_messagelib(lib: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(lib, dict):
        return {}
    out: dict[str, dict[str, Any]] = {}
    for key, value in lib.items():
        if isinstance(value, dict):
            out[str(key)] = dict(value)
    return out


def _copy_state(state: dict[str, Any]) -> AgentState:
    return {
        "messages": [dict(m) for m in (state.get("messages") or [])],
        "messagelib": _copy_messagelib(state.get("messagelib")),
        "skills_enabled": list(state.get("skills_enabled") or []),
        "mentions": _copy_mentions(state.get("mentions")),
        "iteration": int(state.get("iteration", 0)),
        "stop_loop": bool(state.get("stop_loop", False)),
        "extra": dict(state.get("extra") or {}),
    }


def _mk_ctx(
    state: dict[str, Any],
    config: Config,
    session: Session,
    *,
    tool: ToolCtx | None = None,
    error: BaseException | None = None,
    prepare_meta: PrepareMeta | None = None,
) -> dict[str, Any]:
    """
    Short-lived extension ctx. Only ``ctx["state"]`` is written back to LangGraph.
    ``session`` is the run's Session (``session.toml`` path + messages).
    ``preparemeta`` is immutable prepare metadata (CLI --cfg tokens, paths).
    """
    return {
        "state": _copy_state(state),
        "config": config,
        "session": session,
        "preparemeta": prepare_meta,
        "tool": tool,
        "error": error,
    }


def _state_update(ctx: dict[str, Any]) -> AgentState:
    state = ctx["state"]
    if not isinstance(state.get("extra"), dict):
        raise TypeError("state.extra must be a dict")
    skills_enabled = state.get("skills_enabled")
    if skills_enabled is not None and not isinstance(skills_enabled, list):
        raise TypeError("state.skills_enabled must be a list")
    mentions = state.get("mentions")
    if mentions is not None and not isinstance(mentions, list):
        raise TypeError("state.mentions must be a list")
    return {
        "messages": [dict(m) for m in (state.get("messages") or [])],
        "messagelib": _copy_messagelib(state.get("messagelib")),
        "skills_enabled": [str(n) for n in (skills_enabled or [])],
        "mentions": _copy_mentions(mentions),
        "iteration": int(state.get("iteration", 0)),
        "stop_loop": bool(state.get("stop_loop", False)),
        "extra": dict(state.get("extra") or {}),
    }

def _messages_to_dicts(messages: list[Message]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for msg in messages:
        entry: dict[str, Any] = {}
        if msg.ref is not None:
            entry["ref"] = msg.ref
            if msg.role:
                entry["role"] = msg.role
            if msg.content:
                entry["content"] = msg.content
        else:
            entry["role"] = msg.role
            entry["content"] = msg.content
        if msg.name is not None:
            entry["name"] = msg.name
        if msg.tool_call_id is not None:
            entry["tool_call_id"] = msg.tool_call_id
        entry.update(msg.extra)
        result.append(entry)
    return result


def _skills_enable_cfg(config: Config) -> list[str] | None:
    """None = all registered; [] = none; list = whitelist."""
    raw = config.raw if isinstance(config.raw, dict) else {}
    skills_cfg = raw.get("skills")
    if not isinstance(skills_cfg, dict) or "enable" not in skills_cfg:
        return None
    enable = skills_cfg["enable"]
    if enable is None:
        return None
    if not isinstance(enable, list):
        raise TypeError("skills.enable must be a list of skill names")
    return [str(n) for n in enable]


def _seed_skills_enabled(config: Config, registry: HookRegistry) -> list[str]:
    registered = registry.skills.names()
    enable = _skills_enable_cfg(config)
    if enable is None:
        return list(registered)
    known = set(registered)
    for name in enable:
        if name not in known:
            print(
                f"[skills] warning: enable lists unknown skill {name!r}",
                file=sys.stderr,
            )
    allow = set(enable)
    return [n for n in registered if n in allow]


def _parse_mentions(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Parse ``@{cmd:text}`` from user message ``content`` into AgentState.mentions."""
    mentions: list[dict[str, Any]] = []
    for idx, msg in enumerate(messages):
        if msg.get("role") != "user":
            continue
        text = msg.get("content", "")
        for match in _MENTION_RE.finditer(text):
            cmd = match.group(1)
            body = match.group(2)
            mentions.append(
                {
                    "cmd": cmd,
                    "text": body,
                    "handled": [],
                    "raw": match.group(0),
                    "msg_index": idx,
                    "start": match.start(),
                    "replacement": None,
                }
            )
    return mentions


def _apply_mention_replacements(
    messages: list[dict[str, Any]], mentions: list[dict[str, Any]]
) -> None:
    """Apply ext-provided ``replacement`` strings onto message ``content``."""
    by_msg: dict[int, list[dict[str, Any]]] = {}
    for mention in mentions:
        replacement = mention.get("replacement")
        if replacement is None:
            continue
        try:
            msg_index = int(mention.get("msg_index", -1))
        except (TypeError, ValueError):
            continue
        if msg_index < 0 or msg_index >= len(messages):
            continue
        by_msg.setdefault(msg_index, []).append(mention)

    for msg_index, items in by_msg.items():
        msg = messages[msg_index]
        content = str(msg.get("content", ""))
        # Reverse by start so earlier offsets stay valid.
        ordered = sorted(
            items,
            key=lambda m: int(m.get("start", -1)),
            reverse=True,
        )
        for mention in ordered:
            raw_span = str(mention.get("raw", ""))
            if not raw_span:
                continue
            repl = str(mention["replacement"])
            start = mention.get("start")
            if isinstance(start, int) and start >= 0:
                end = start + len(raw_span)
                if content[start:end] == raw_span:
                    content = content[:start] + repl + content[end:]
                    continue
            # Fallback: replace first occurrence
            content = content.replace(raw_span, repl, 1)
        msg["content"] = content


def _api_message(msg: dict[str, Any]) -> dict[str, Any]:
    """Project an in-memory message to OpenAI/LiteLLM shape (no ``ref``)."""
    out: dict[str, Any] = {
        "role": msg.get("role", ""),
        "content": msg.get("content", ""),
    }
    if "name" in msg :
        out["name"] = msg["name"]
    if "tool_call_id" in msg:
        out["tool_call_id"] = msg["tool_call_id"]
    if "tool_calls" in msg:
        out["tool_calls"] = msg["tool_calls"]
    return out


def _resolve_message(
    msg: dict[str, Any],
    messagelib: dict[str, dict[str, Any]],
) -> dict[str, Any] | None:
    """Resolve ``ref``: extend from messagelib, then apply own fields."""

    ref = msg.get("ref")
    if ref is None or str(ref) == "":
        resolved = {k: v for k, v in msg.items() if k != "ref"}
        return resolved

    base = messagelib.get(ref)

    if not isinstance(base, dict):
        raise ValueError(f"messagelib ref {name!r} not found")

    own = {k: v for k, v in msg.items() if k != "ref"}
    resolved = {**dict(base), **own}
    if not "content" in resolved or resolved["content"] == "":
        return None
    if not "role" in resolved:
        resolved["role"] = ""
    return resolved


def _llm_messages(state: dict[str, Any]) -> list[dict[str, Any]]:
    """Resolve refs against messagelib, then project to API messages (order kept)."""
    lib = _copy_messagelib(state.get("messagelib"))
    out = []
    for m in (state.get("messages") or []):
        resolved = _resolve_message(m, lib)
        if resolved is None:
            continue
        out.append(_api_message(resolved))
    return out


def _assistant_tool_for_persist(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Serialize assistant/tool turns for disk (skip refs / system / user)."""
    out: list[dict[str, Any]] = []
    for msg in messages:
        role = str(msg.get("role", ""))
        if role not in {"assistant", "tool"}:
            continue
        entry: dict[str, Any] = {
            "role": role,
            "content": str(msg.get("content", "")),
        }
        if msg.get("name") is not None:
            entry["name"] = msg["name"]
        if msg.get("tool_call_id") is not None:
            entry["tool_call_id"] = msg["tool_call_id"]
        for key, value in msg.items():
            if key in {"role", "content", "name", "tool_call_id", "ref"}:
                continue
            entry[key] = value
        out.append(entry)
    return out


def _new_text_message(role: str, text: str, **extra: Any) -> dict[str, Any]:
    """Create a concrete text message."""
    entry: dict[str, Any] = {"role": role, "content": text}
    entry.update(extra)
    return entry


def _litellm_model(model: str) -> str:
    """Route OpenAI-compatible endpoints via the openai/ provider prefix."""
    known_prefixes = (
        "openai/",
        "azure/",
        "anthropic/",
        "bedrock/",
        "gemini/",
        "ollama/",
    )
    if model.startswith(known_prefixes):
        return model
    return f"openai/{model}"


def _tool_call_to_dict(tc: Any) -> dict[str, Any]:
    """Normalize a LiteLLM / OpenAI tool_call object to a plain dict."""
    if isinstance(tc, dict):
        return tc
    fn = getattr(tc, "function", None)
    function: dict[str, Any]
    if isinstance(fn, dict):
        function = {
            "name": fn.get("name", ""),
            "arguments": fn.get("arguments", "") or "",
        }
    elif fn is not None:
        function = {
            "name": getattr(fn, "name", "") or "",
            "arguments": getattr(fn, "arguments", "") or "",
        }
    else:
        function = {"name": "", "arguments": ""}
    return {
        "id": getattr(tc, "id", None) or "",
        "type": getattr(tc, "type", None) or "function",
        "function": function,
    }


def _parse_arguments(raw: Any) -> dict[str, Any]:
    if raw is None or raw == "":
        return {}
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid tool arguments JSON: {exc}") from exc
        if not isinstance(parsed, dict):
            raise ValueError("Tool arguments must be a JSON object")
        return parsed
    raise ValueError(f"Unsupported tool arguments type: {type(raw)!r}")


def _execute_with_retry(
    registry: HookRegistry,
    name: str,
    arguments: dict[str, Any],
    ctx: dict[str, Any],
    config: Config,
) -> str:
    opts = tool_cfg(config, name)
    retries = int(opts.get("retry", 0) or 0)
    on_failure = str(opts.get("on_failure", "abort")).strip().lower()
    attempts = max(0, retries) + 1
    last_error = ""
    for _ in range(attempts):
        try:
            return registry.tools.execute(name, arguments, ctx)
        except Exception as exc:  # noqa: BLE001 — surface as tool result / policy
            last_error = f"Error: {exc}"
            if on_failure == "continue":
                return last_error
            if on_failure == "ask":
                # Defer interactive retry UX to extension; surface error for now.
                return last_error
            # abort: keep retrying until attempts exhausted, then return error
            continue
    return last_error or f"Error: tool {name!r} failed"


def _to_jsonable(value: Any, *, omit_empty: bool = False) -> Any:
    """Convert LiteLLM / pydantic values to JSON-safe structures."""
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if hasattr(value, "model_dump") and callable(value.model_dump):
        try:
            dumped = value.model_dump(mode="json")
        except TypeError:
            dumped = value.model_dump()
        return _to_jsonable(dumped, omit_empty=omit_empty)
    if hasattr(value, "dict") and callable(value.dict):
        try:
            dumped = value.dict()
        except TypeError:
            dumped = None
        if dumped is not None:
            return _to_jsonable(dumped, omit_empty=omit_empty)
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for key, item in value.items():
            if key == "api_key":
                continue
            converted = _to_jsonable(item, omit_empty=omit_empty)
            if omit_empty and converted in (None, {}, []):
                continue
            out[str(key)] = converted
        return out
    if isinstance(value, (list, tuple)):
        items = [_to_jsonable(item, omit_empty=omit_empty) for item in value]
        if omit_empty:
            items = [item for item in items if item not in (None, {}, [])]
        return items
    return str(value)


def _serialize_llm_response(response: Any) -> dict[str, Any]:
    data = _to_jsonable(response)
    if not isinstance(data, dict):
        return {}
    data.pop("api_key", None)
    return data


def _pick_int(*candidates: Any) -> int:
    """First non-None value that converts to int, else 0."""
    for value in candidates:
        if value is None:
            continue
        try:
            return int(value)
        except (TypeError, ValueError):
            continue
    return 0


def usage_for_session(usage: Any) -> dict[str, Any]:
    """Last-call usage for ``[resp.usage]``: provider fields plus flattened cache ints."""
    data = _to_jsonable(usage, omit_empty=True)
    if not isinstance(data, dict):
        data = {}
    details = data.get("prompt_tokens_details")
    if not isinstance(details, dict):
        details = {}
    completion_details = data.get("completion_tokens_details")
    if not isinstance(completion_details, dict):
        completion_details = {}

    data["cached_tokens"] = _pick_int(
        details.get("cached_tokens"),
        data.get("cache_read_input_tokens"),
    )
    data["cache_read_tokens"] = _pick_int(
        data.get("cache_read_input_tokens"),
        details.get("cached_tokens"),
    )
    data["cache_write_tokens"] = _pick_int(
        data.get("cache_creation_input_tokens"),
        details.get("cache_write_tokens"),
        details.get("cache_creation_tokens"),
    )
    data["reasoning_tokens"] = _pick_int(completion_details.get("reasoning_tokens"))
    return data


def _build_graph(
    config: Config,
    registry: HookRegistry,
    session: Session,
    prepare_meta: PrepareMeta | None = None,
):
    last_llm_response: dict[str, Any] | None = None

    def _mk_ctx_within(
        state: dict[str, Any],
        *,
        tool: ToolCtx | None = None,
        error: BaseException | None = None,
    ) -> dict[str, Any]:
        """Redirect to ``_mk_ctx`` with ``config``, ``session``, ``preparemeta``."""
        return _mk_ctx(
            state,
            config,
            session,
            tool=tool,
            error=error,
            prepare_meta=prepare_meta,
        )

    def handle_request(state: AgentState) -> AgentState:
        working_state = _copy_state(state)
        working_state["skills_enabled"] = _seed_skills_enabled(config, registry)
        working_state["mentions"] = _parse_mentions(working_state["messages"])
        updated_state = _state_update(registry.run("handle_request", _mk_ctx_within(working_state)))
        _apply_mention_replacements(updated_state["messages"], updated_state["mentions"])
        return updated_state

    def before_llm(state: AgentState) -> AgentState:
        return _state_update(registry.run("before_llm", _mk_ctx_within(state)))

    def call_llm(state: AgentState) -> dict[str, Any]:
        nonlocal last_llm_response
        # Prefer llm.api_key in cfg; env via api_key_env is compatibility only.
        api_key = config.llm.api_key or os.environ.get(config.llm.api_key_env)
        if not api_key:
            raise RuntimeError(
                "API key not found: set llm.api_key in cfg "
                f"or environment variable {config.llm.api_key_env!r}"
            )
        iteration = int(state.get("iteration", 0)) + 1
        api_messages = _llm_messages(state)
        print(
            f"Calling LLM (iteration={iteration}) with messages={api_messages}",
            file=sys.stderr,
        )
        kwargs: dict[str, Any] = {
            "model": _litellm_model(config.llm.model),
            "messages": api_messages,
            "api_key": api_key,
            "api_base": config.llm.base_url,
        }
        tools = registry.tools.openai_tools(config)
        if tools:
            kwargs["tools"] = tools

        # Exportable payload for before_call_llm (no secrets). Side-effect only.
        llm_request: dict[str, Any] = {
            "model": kwargs["model"],
            "messages": kwargs["messages"],
            "api_base": kwargs["api_base"],
            "iteration": iteration,
        }
        if tools:
            llm_request["tools"] = tools
        hook_state = _copy_state(state)
        hook_state["iteration"] = iteration
        call_ctx = _mk_ctx_within(hook_state)
        call_ctx["llm_request"] = llm_request
        registry.run("before_call_llm", call_ctx)

        response = litellm.completion(**kwargs)
        last_llm_response = _serialize_llm_response(response)
        usage = getattr(response, "usage", None)
        if usage is None:
            usage = last_llm_response.get("usage")
        session.session_doc["resp"] = {"usage": usage_for_session(usage)}

        choice = response.choices[0].message
        content = getattr(choice, "content", None) or ""
        assistant = _new_text_message("assistant", content)

        raw_calls = getattr(choice, "tool_calls", None)
        if raw_calls:
            assistant["tool_calls"] = [_tool_call_to_dict(tc) for tc in raw_calls]

        return {
            "messages": [*state["messages"], assistant],
            "iteration": iteration,
        }

    def after_llm(state: AgentState) -> AgentState:
        ctx = _mk_ctx_within(state)
        if last_llm_response is not None:
            ctx["llm_response"] = last_llm_response
        return _state_update(registry.run("after_llm", ctx))

    def run_tools(state: AgentState) -> AgentState:
        """Execute each tool_call; finish the full batch even if stop_loop is set.

        ``stop_loop`` ends the *agent loop* after this turn (via routing), not
        remaining tool_calls in this batch. Ext mutates ``ctx["state"]``;
        per-call fields live on ``ctx["tool"]``.
        """
        working = _copy_state(state)
        messages = working["messages"]
        if not messages:
            return working

        last = messages[-1]
        if last.get("role") != "assistant":
            return working

        tool_calls = last.get("tool_calls") or []
        if not tool_calls:
            return working

        for tc in tool_calls:
            tc_dict = _tool_call_to_dict(tc)
            fn = tc_dict.get("function") or {}
            name = str(fn.get("name") or "")
            call_id = str(tc_dict.get("id") or "")

            try:
                arguments = _parse_arguments(fn.get("arguments"))
            except ValueError as exc:
                messages.append(
                    _new_text_message(
                        "tool",
                        f"Error: {exc}",
                        tool_call_id=call_id,
                    )
                )
                continue

            if not name or registry.tools.get(name) is None:
                messages.append(
                    _new_text_message(
                        "tool",
                        f"Error: unknown tool {name!r}",
                        tool_call_id=call_id,
                    )
                )
                continue

            if not tool_enabled(config, name):
                messages.append(
                    _new_text_message(
                        "tool",
                        f"Error: tool {name!r} is disabled in cfg",
                        tool_call_id=call_id,
                    )
                )
                continue

            permission = tool_permission(config, name)
            # custom: default deny until before_tool clears skip (engine will not Y/n).
            custom = permission == "custom"
            tool: ToolCtx = {
                "name": name,
                "arguments": arguments,
                "tool_call_id": call_id,
                "permission": permission,
                "work_dir": str(config.work_dir),
                "skip": custom,
                "result": (
                    f"Error: tool {name!r} requires custom extension approval"
                    if custom
                    else None
                ),
            }
            ctx = _mk_ctx_within(working, tool=tool)
            ctx = registry.run("before_tool", ctx)
            tool = ctx["tool"]

            if not tool.get("skip") and permission == "ask":
                spec = registry.tools.get(name)
                ask_fn = spec.ask if spec is not None else None
                approved = (
                    ask_fn(arguments, ctx)
                    if ask_fn is not None
                    else _ask_user_yn(name, arguments)
                )
                if approved:
                    tool["skip"] = False
                    tool["result"] = None
                else:
                    tool["skip"] = True
                    tool["result"] = f"Error: tool {name!r} denied by user"

            if tool.get("skip"):
                result = tool.get("result")
                if result is None:
                    result = f"Error: tool {name!r} was skipped"
                else:
                    result = str(result)
            else:
                result = _execute_with_retry(
                    registry, name, arguments, ctx, config
                )
                tool["result"] = result

            ctx = registry.run("after_tool", ctx)
            tool = ctx["tool"]
            result = str(tool.get("result", result))
            working = _state_update(ctx)
            messages = list(working["messages"])
            messages.append(
                _new_text_message("tool", result, tool_call_id=call_id)
            )
            working["messages"] = messages

        return working

    def after_tools(state: AgentState) -> AgentState:
        """Batch-level hook after all tool_calls in this turn.

        Extensions may set ``state["stop_loop"]=True`` to end the agent loop
        after this turn (not to skip remaining tool_calls).
        """
        return _state_update(registry.run("after_tools", _mk_ctx_within(state)))

    def route_after_tools(state: AgentState) -> str:
        """Continue only when auto_loop is on, under max_iterations, and last
        assistant message still had tool_calls (stop-on-no-tool-calls).

        ``stop_loop`` forces end of the agent loop (set in run_tools or after_tools).
        """
        if state.get("stop_loop"):
            print("Stopping: stop_loop set by extension/tool", file=sys.stderr)
            return "end"

        if not config.loop.auto_loop:
            return "end"

        iteration = int(state.get("iteration", 0))
        if iteration >= config.loop.max_iterations:
            print(
                f"Stopping: max_iterations={config.loop.max_iterations} reached",
                file=sys.stderr,
            )
            return "end"

        for msg in reversed(state["messages"]):
            if msg.get("role") == "assistant":
                if msg.get("tool_calls"):
                    return "before_llm"
                return "end"
        return "end"

    def route_after_handle_request(state: AgentState) -> str:
        """Allow handle_request to end the run (e.g. unresolved sub_agent pending)."""
        if state.get("stop_loop"):
            print(
                "Stopping: stop_loop set during handle_request",
                file=sys.stderr,
            )
            return "end"
        return "before_llm"

    graph = StateGraph(AgentState)
    graph.add_node("handle_request", handle_request)
    graph.add_node("before_llm", before_llm)
    graph.add_node("call_llm", call_llm)
    graph.add_node("after_llm", after_llm)
    graph.add_node("run_tools", run_tools)
    graph.add_node("after_tools", after_tools)
    graph.add_edge(START, "handle_request")
    graph.add_conditional_edges(
        "handle_request",
        route_after_handle_request,
        {"before_llm": "before_llm", "end": END},
    )
    graph.add_edge("before_llm", "call_llm")
    graph.add_edge("call_llm", "after_llm")
    graph.add_edge("after_llm", "run_tools")
    graph.add_edge("run_tools", "after_tools")
    graph.add_conditional_edges(
        "after_tools",
        route_after_tools,
        {"before_llm": "before_llm", "end": END},
    )
    return graph.compile()


def run(
    config: Config,
    session: Session,
    *,
    registry: HookRegistry | None = None,
    prepare_meta: PrepareMeta | None = None,
) -> tuple[Session, list[Message]]:
    """Run LLM ↔ tools loop; return session messages with this run's turns appended.

    Base messages (including prior assistant/tool turns) are taken from the final
    graph state so in-place mutations (e.g. sub_agent pending hydration) persist.
    Only newly appended assistant/tool turns are returned as ``appended``.
    ``messagelib`` refs are resolved after ``before_llm`` for the API only.
    No disk I/O.
    """
    reg = registry if registry is not None else HookRegistry()
    graph = _build_graph(config, reg, session, prepare_meta)

    messages = _messages_to_dicts(session.messages)
    base_len = len(messages)
    initial: AgentState = {
        "messages": messages,
        "messagelib": _copy_messagelib(
            config.raw.get("messagelib") if isinstance(config.raw, dict) else None
        ),
        "skills_enabled": [],
        "mentions": [],
        "iteration": 0,
        "stop_loop": False,
        "extra": {},
    }
    try:
        result = graph.invoke(initial)
        ctx = reg.run(
            "on_result",
            _mk_ctx(result, config, session, prepare_meta=prepare_meta),
        )
        final = _state_update(ctx)
    except Exception as exc:
        err_ctx = _mk_ctx(
            # state
            {
                "messages": messages,
                "messagelib": _copy_messagelib(
                    config.raw.get("messagelib")
                    if isinstance(config.raw, dict)
                    else None
                ),
                "skills_enabled": [],
                "mentions": [],
                "iteration": 0,
                "stop_loop": False,
                "extra": {},
            },
            config,
            session,
            error=exc,
            prepare_meta=prepare_meta,
        )
        try:
            reg.run("on_error", err_ctx)
        except Exception:
            pass
        raise

    final_msgs = final.get("messages") or []
    # Include in-place base mutations (e.g. sub_agent pending hydration).
    base_out = [Message.from_dict(m) for m in final_msgs[:base_len]]
    new_msgs = final_msgs[base_len:]
    appended = [
        Message.from_dict(m) for m in _assistant_tool_for_persist(new_msgs)
    ]
    session.messages = base_out + appended
    return session, appended
