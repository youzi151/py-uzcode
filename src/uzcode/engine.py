"""Thin core engine: LangGraph workflow + LiteLLM + hook registry + tools."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, TypedDict

import litellm
from langgraph.graph import END, START, StateGraph

from uzcode.data import Config, Message, Request
from uzcode.middleware.base import HookRegistry
from uzcode.tools.registry import tool_cfg, tool_enabled, tool_permission


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
    messages: list[dict[str, Any]]


def _messages_to_dicts(messages: list[Message]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for msg in messages:
        entry: dict[str, Any] = {"role": msg.role, "content": msg.content}
        if msg.name is not None:
            entry["name"] = msg.name
        if msg.tool_call_id is not None:
            entry["tool_call_id"] = msg.tool_call_id
        entry.update(msg.extra)
        result.append(entry)
    return result


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
                # Defer interactive retry UX to middleware; surface error for now.
                return last_error
            # abort: keep retrying until attempts exhausted, then return error
            continue
    return last_error or f"Error: tool {name!r} failed"


def _build_graph(config: Config, registry: HookRegistry):
    def before_llm(state: AgentState) -> dict[str, Any]:
        ctx: dict[str, Any] = {"messages": state["messages"], "config": config}
        ctx = registry.run("before_llm", ctx)
        return {"messages": ctx["messages"]}

    def call_llm(state: AgentState) -> dict[str, Any]:
        # Prefer llm.api_key in cfg; env via api_key_env is compatibility only.
        api_key = config.llm.api_key or os.environ.get(config.llm.api_key_env)
        if not api_key:
            raise RuntimeError(
                "API key not found: set llm.api_key in cfg.toml "
                f"or environment variable {config.llm.api_key_env!r}"
            )
        print(f"Calling LLM with messages={state['messages']}", file=sys.stderr)
        kwargs: dict[str, Any] = {
            "model": _litellm_model(config.llm.model),
            "messages": state["messages"],
            "api_key": api_key,
            "api_base": config.llm.base_url,
        }
        tools = registry.tools.openai_tools(config)
        if tools:
            kwargs["tools"] = tools

        response = litellm.completion(**kwargs)
        choice = response.choices[0].message
        content = getattr(choice, "content", None) or ""
        assistant: dict[str, Any] = {"role": "assistant", "content": content}

        raw_calls = getattr(choice, "tool_calls", None)
        if raw_calls:
            assistant["tool_calls"] = [_tool_call_to_dict(tc) for tc in raw_calls]

        return {"messages": [*state["messages"], assistant]}

    def after_llm(state: AgentState) -> dict[str, Any]:
        ctx: dict[str, Any] = {"messages": state["messages"], "config": config}
        ctx = registry.run("after_llm", ctx)
        return {"messages": ctx["messages"]}

    def run_tools(state: AgentState) -> dict[str, Any]:
        messages = list(state["messages"])
        if not messages:
            return {"messages": messages}

        last = messages[-1]
        if last.get("role") != "assistant":
            return {"messages": messages}

        tool_calls = last.get("tool_calls") or []
        if not tool_calls:
            return {"messages": messages}

        for tc in tool_calls:
            tc_dict = _tool_call_to_dict(tc)
            fn = tc_dict.get("function") or {}
            name = str(fn.get("name") or "")
            call_id = str(tc_dict.get("id") or "")

            try:
                arguments = _parse_arguments(fn.get("arguments"))
            except ValueError as exc:
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call_id,
                        "content": f"Error: {exc}",
                    }
                )
                continue

            if not name or registry.tools.get(name) is None:
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call_id,
                        "content": f"Error: unknown tool {name!r}",
                    }
                )
                continue

            if not tool_enabled(config, name):
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call_id,
                        "content": f"Error: tool {name!r} is disabled in cfg.toml",
                    }
                )
                continue

            permission = tool_permission(config, name)
            # custom: default deny until before_tool clears skip (engine will not Y/n).
            custom = permission == "custom"
            ctx: dict[str, Any] = {
                "messages": messages,
                "config": config,
                "work_dir": config.work_dir,
                "tool_name": name,
                "arguments": arguments,
                "tool_call_id": call_id,
                "permission": permission,
                "skip": custom,
                "result": (
                    f"Error: tool {name!r} requires custom middleware approval"
                    if custom
                    else None
                ),
            }
            ctx = registry.run("before_tool", ctx)

            if not ctx.get("skip") and permission == "ask":
                if _ask_user_yn(name, arguments):
                    ctx["skip"] = False
                    ctx["result"] = None
                else:
                    ctx["skip"] = True
                    ctx["result"] = f"Error: tool {name!r} denied by user"

            if ctx.get("skip"):
                result = ctx.get("result")
                if result is None:
                    result = f"Error: tool {name!r} was skipped"
                else:
                    result = str(result)
            else:
                result = _execute_with_retry(
                    registry, name, arguments, ctx, config
                )
                ctx["result"] = result

            ctx = registry.run("after_tool", ctx)
            result = str(ctx.get("result", result))
            messages = list(ctx.get("messages") or messages)
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call_id,
                    "content": result,
                }
            )

        return {"messages": messages}

    graph = StateGraph(AgentState)
    graph.add_node("before_llm", before_llm)
    graph.add_node("call_llm", call_llm)
    graph.add_node("after_llm", after_llm)
    graph.add_node("run_tools", run_tools)
    graph.add_edge(START, "before_llm")
    graph.add_edge("before_llm", "call_llm")
    graph.add_edge("call_llm", "after_llm")
    graph.add_edge("after_llm", "run_tools")
    graph.add_edge("run_tools", END)
    return graph.compile()


def run(
    config: Config,
    request: Request,
    *,
    out_path: str | Path | None = None,
    registry: HookRegistry | None = None,
) -> Request:
    """Run one LLM turn, execute any tool_calls once, write results to TOML."""
    reg = registry if registry is not None else HookRegistry()
    graph = _build_graph(config, reg)

    messages = _messages_to_dicts(request.messages)
    try:
        result = graph.invoke({"messages": messages})
        messages = result["messages"]
        ctx: dict[str, Any] = {"messages": messages, "config": config}
        ctx = reg.run("on_result", ctx)
        messages = ctx["messages"]
    except Exception as exc:
        err_ctx: dict[str, Any] = {
            "messages": messages,
            "config": config,
            "error": exc,
        }
        try:
            reg.run("on_error", err_ctx)
        except Exception:
            pass
        raise

    request.messages = [Message.from_dict(m) for m in messages]
    request.write(out_path)
    return request
