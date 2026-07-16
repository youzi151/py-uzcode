"""Thin core engine: LangGraph workflow + LiteLLM + hook registry."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, TypedDict

import litellm
from langgraph.graph import END, START, StateGraph

from uzcode.data import Config, Message, Request
from uzcode.middleware.base import HookRegistry


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

        response = litellm.completion(
            model=_litellm_model(config.llm.model),
            messages=state["messages"],
            api_key=api_key,
            api_base=config.llm.base_url,
        )
        choice = response.choices[0].message
        content = getattr(choice, "content", None) or ""
        assistant = {"role": "assistant", "content": content}
        return {"messages": [*state["messages"], assistant]}

    def after_llm(state: AgentState) -> dict[str, Any]:
        ctx: dict[str, Any] = {"messages": state["messages"], "config": config}
        ctx = registry.run("after_llm", ctx)
        return {"messages": ctx["messages"]}

    graph = StateGraph(AgentState)
    graph.add_node("before_llm", before_llm)
    graph.add_node("call_llm", call_llm)
    graph.add_node("after_llm", after_llm)
    graph.add_edge(START, "before_llm")
    graph.add_edge("before_llm", "call_llm")
    graph.add_edge("call_llm", "after_llm")
    graph.add_edge("after_llm", END)
    return graph.compile()


def run(
    config: Config,
    request: Request,
    *,
    out_path: str | Path | None = None,
    registry: HookRegistry | None = None,
) -> Request:
    """Run one LLM turn (no tools) and write results back to TOML."""
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
