"""Built-in sub_agent extension — delegate work to another session."""

from __future__ import annotations

from typing import Any

from . import handlers

_SUB_AGENT_PARAMS = {
    "type": "object",
    "properties": {
        "prompt": {
            "type": "string",
            "description": "Task prompt for the sub-agent session (user message).",
        },
        "session": {
            "type": "string",
            "description": (
                "Optional sub session name under .uzcode/sessions/<name>/. "
                "Auto-generated when omitted."
            ),
        },
    },
    "required": ["prompt"],
}

_SUB_DONE_PARAMS = {
    "type": "object",
    "properties": {
        "summary": {
            "type": "string",
            "description": "Concise outcome of the delegated task.",
        },
        "details": {
            "type": "string",
            "description": "Optional extra detail for the parent agent.",
        },
        "result": {
            "type": ["object", "array", "string"],
            "description": (
                "Optional structured result. When set, written as result.json "
                "(overrides the summary/details object shape)."
            ),
        },
    },
    "required": ["summary"],
}

_SUB_AGENT_DESC = (
    "Create a new uzcode sub-session with the given prompt. Writes "
    "session.toml with cfg_insert (main --cfg tokens plus subagent, or "
    "exts.sub_agent.cfg_insert). The user chooses run-later or deny and "
    "may edit session.toml before running the sub themselves. Returns "
    "pending; re-run this main session after the sub wrote result.json. "
    "Run the sub with uzcode --session <name> (cfg_insert in session.toml)."
)

_SUB_DONE_DESC = (
    "Call once when the delegated sub-agent task is done. Writes result.json "
    "in the current session directory for the parent agent to consume. "
    "Ends the agent loop after this turn."
)


def register(registry, config) -> None:
    registry.tool(
        "sub_agent",
        description=_SUB_AGENT_DESC,
        parameters=_SUB_AGENT_PARAMS,
        handler=handlers.sub_agent,
        ask=handlers.ask_sub_agent,
    )
    registry.tool(
        "sub_agent_done",
        description=_SUB_DONE_DESC,
        parameters=_SUB_DONE_PARAMS,
        handler=handlers.sub_agent_done,
    )

    def handle_request(ctx: dict[str, Any]) -> dict[str, Any]:
        return handlers.handle_request_hydrate(ctx)

    registry.on("handle_request", handle_request, order=50, name="sub_agent")
