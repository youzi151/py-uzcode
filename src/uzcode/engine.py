"""Thin core engine: LangGraph workflow + LiteLLM (Phase 1)."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, TypedDict

import litellm
from langgraph.graph import END, START, StateGraph

from uzcode.data import Config, Message, Request
from uzcode.middleware.base import Middleware


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


def _run_middleware_chain(
    middlewares: list[Middleware],
    hook: str,
    ctx: dict[str, Any],
) -> dict[str, Any]:
    for mw in middlewares:
        fn = getattr(mw, hook, None)
        if fn is not None:
            ctx = fn(ctx)
    return ctx


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


def _build_graph(config: Config, middlewares: list[Middleware]):
    def before_llm(state: AgentState) -> dict[str, Any]:
        ctx: dict[str, Any] = {"messages": state["messages"], "config": config}
        ctx = _run_middleware_chain(middlewares, "before_llm", ctx)
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
        ctx = _run_middleware_chain(middlewares, "after_llm", ctx)
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
    middlewares: list[Middleware] | None = None,
) -> Request:
    """Run one LLM turn (no tools) and write results back to TOML."""
    mws = middlewares if middlewares is not None else []
    graph = _build_graph(config, mws)

    initial: AgentState = {"messages": _messages_to_dicts(request.messages)}
    result = graph.invoke(initial)

    request.messages = [Message.from_dict(m) for m in result["messages"]]
    request.write(out_path)
    return request
