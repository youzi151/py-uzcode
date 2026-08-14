"""sub_agent / sub_agent_done tool handlers and pending hydration."""

from __future__ import annotations

import json
import re
import sys
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

import tomli_w

from uzcode.cfg import resolve_session_dir

RESULT_FILENAME = "result.json"
_TOOL_SUB = "sub_agent"
_SESSION_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_SUBAGENT_TOKEN = "subagent"


def ext_cfg(config: Any) -> dict[str, Any]:
    ext = getattr(config, "exts", None) or {}
    if not isinstance(ext, dict):
        return {}
    raw = ext.get("sub_agent")
    return raw if isinstance(raw, dict) else {}


def _normalize_insert_list(raw: Any) -> list[str] | None:
    if raw is None:
        return None
    if isinstance(raw, str):
        token = raw.strip()
        return [token] if token else None
    if isinstance(raw, list):
        out = [str(x).strip() for x in raw if str(x).strip()]
        return out or None
    raise ValueError(
        "exts.sub_agent.cfg_insert must be a string or list of strings"
    )

def default_cfg_insert(ctx: dict[str, Any] | None = None) -> list[str]:
    """Seed ``cfg_insert`` for the sub ``session.toml``.

    Default: main ``PrepareMeta.cfg_raw_inputs`` plus ``subagent``.
    Override with ``[exts.sub_agent] cfg_insert = [...]``.
    """
    config = None if ctx is None else ctx.get("config")
    override = _normalize_insert_list(
        ext_cfg(config).get("cfg_insert") if config is not None else None
    )
    if override is not None:
        return override
    
    meta = None if ctx is None else ctx.get("preparemeta")
    raw = getattr(meta, "cfg_raw_inputs", None) or []
    tokens = [str(t).strip() for t in raw if str(t).strip()]
    if _SUBAGENT_TOKEN not in tokens:
        tokens.append(_SUBAGENT_TOKEN)
    return tokens


def _work_dir(ctx: dict[str, Any]) -> Path:
    tool = ctx.get("tool") or {}
    raw = tool.get("work_dir")
    if raw is None:
        config = ctx.get("config")
        raw = getattr(config, "work_dir", None) if config is not None else None
    if raw is None:
        raise ValueError("work_dir missing from tool context")
    return Path(raw).resolve()


def _session_dir_from_ctx(ctx: dict[str, Any]) -> Path:
    session = ctx.get("session")
    path_attr = getattr(session, "path", None) if session is not None else None
    if path_attr is None:
        raise ValueError("session.path missing; cannot resolve current session dir")
    return Path(path_attr).resolve().parent


def parse_pending(content: str) -> dict[str, Any] | None:
    """Return pending payload if content is a sub_agent pending marker."""
    text = (content or "").strip()
    if not text:
        return None
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(data, dict):
        return None
    if str(data.get("status") or "") != "pending":
        return None
    sub = str(data.get("sub_session") or "").strip()
    if not sub:
        return None
    return data


def pending_payload(sub_session: str) -> str:
    return json.dumps(
        {"status": "pending", "sub_session": sub_session},
        ensure_ascii=False,
    )


def result_path(session_dir: Path) -> Path:
    return session_dir / RESULT_FILENAME


def read_result_json(session_dir: Path) -> str | None:
    path = result_path(session_dir)
    if not path.is_file():
        return None
    return path.read_text(encoding="utf-8")


def _sub_agent_call_ids(messages: list[dict[str, Any]]) -> set[str]:
    ids: set[str] = set()
    for msg in messages:
        if msg.get("role") != "assistant":
            continue
        for tc in msg.get("tool_calls") or []:
            if not isinstance(tc, dict):
                continue
            fn = tc.get("function") or {}
            if str(fn.get("name") or "") != _TOOL_SUB:
                continue
            call_id = str(tc.get("id") or "")
            if call_id:
                ids.add(call_id)
    return ids


def hydrate_pending_messages(
    messages: list[dict[str, Any]],
    work_dir: Path,
) -> tuple[list[dict[str, Any]], list[str], bool]:
    """Replace pending sub_agent tool results when result.json exists.

    Returns (messages, still_pending_sessions, any_hydrated).
    """
    call_ids = _sub_agent_call_ids(messages)
    still: list[str] = []
    hydrated = False
    out: list[dict[str, Any]] = []
    for msg in messages:
        entry = dict(msg)
        if entry.get("role") == "tool":
            call_id = str(entry.get("tool_call_id") or "")
            if call_id in call_ids:
                pending = parse_pending(str(entry.get("content") or ""))
                if pending is not None:
                    sub = str(pending["sub_session"])
                    try:
                        session_dir = resolve_session_dir(work_dir, sub)
                    except ValueError:
                        still.append(sub)
                        out.append(entry)
                        continue
                    body = read_result_json(session_dir)
                    if body is None:
                        still.append(sub)
                    else:
                        entry["content"] = body
                        hydrated = True
        out.append(entry)
    return out, still, hydrated


def handle_request_hydrate(ctx: dict[str, Any]) -> dict[str, Any]:
    """Hydrate pending sub_agent results; stop if any remain pending."""
    config = ctx.get("config")
    state = ctx.setdefault("state", {})
    work_dir = Path(getattr(config, "work_dir")).resolve()
    messages = list(state.get("messages") or [])
    new_messages, still, _hydrated = hydrate_pending_messages(messages, work_dir)
    state["messages"] = new_messages
    if still:
        names = ", ".join(still)
        print(
            f"[sub_agent] waiting for result.json in session(s): {names}",
            file=sys.stderr,
        )
        state["stop_loop"] = True
    return ctx


def _normalize_session_name(raw: str | None) -> str:
    name = (raw or "").strip()
    if not name:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        short = uuid.uuid4().hex[:8]
        name = f"sub_{stamp}_{short}"
    if not _SESSION_NAME_RE.fullmatch(name):
        raise ValueError(
            f"Invalid session name {name!r}. Use letters, digits, ., _, - "
            "(must start alphanumeric)."
        )
    return name


def _draft_session_doc(prompt: str, cfg_insert: list[str]) -> dict[str, Any]:
    tokens = [str(t).strip() for t in cfg_insert if str(t).strip()]
    if not tokens:
        raise ValueError("cfg_insert tokens must not be empty")
    return {
        "cfg_insert": tokens,
        "req": {
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are a sub-agent for a delegated task. Complete the "
                        "user request, then call tool sub_agent_done exactly "
                        f"once to write {RESULT_FILENAME} before finishing."
                    ),
                },
                {"role": "user", "content": prompt},
            ]
        }
    }


def create_sub_session(
    work_dir: Path,
    session_name: str,
    prompt: str,
    *,
    cfg_insert: list[str] | None = None,
) -> Path:
    """Create draft ``session.toml`` under the sub session dir.

    ``cfg_insert`` defaults to ``["subagent"]``; the user can edit before
    running with ``uzcode --session <name>``.
    """
    session_dir = resolve_session_dir(work_dir, session_name)
    session_path = session_dir / "session.toml"
    if session_path.is_file():
        raise FileExistsError(
            f"Sub session already exists: {session_path}. "
            "Choose a new session name or remove the old session."
        )
    session_dir.mkdir(parents=True, exist_ok=True)
    doc = _draft_session_doc(
        prompt, cfg_insert if cfg_insert is not None else [_SUBAGENT_TOKEN]
    )
    text = tomli_w.dumps(doc).rstrip() + "\n"
    session_path.write_text(text, encoding="utf-8")
    return session_dir


def ask_sub_agent(arguments: dict[str, Any], ctx: dict[str, Any]) -> bool:
    """Prompt: later / deny. True runs later (create draft + pending)."""
    prompt = str(arguments.get("prompt") or "")
    preview = prompt.replace("\n", " ")
    if len(preview) > 120:
        preview = preview[:117] + "..."
    session = str(arguments.get("session") or "").strip() or "(auto)"
    print(
        f"[sub_agent] session={session!r} prompt={preview!r}\n"
        "  [l]ater / [d]eny: ",
        file=sys.stderr,
        end="",
    )
    sys.stderr.flush()
    try:
        answer = input().strip().lower()
    except EOFError:
        return False
    return answer in ("l", "later", "y", "yes")


def sub_agent(args: dict[str, Any], ctx: dict[str, Any]) -> str:
    prompt = str(args.get("prompt") or "").strip()
    if not prompt:
        raise ValueError("prompt is required")
    session_name = _normalize_session_name(
        str(args.get("session") or "") or None
    )
    work_dir = _work_dir(ctx)
    session_dir = create_sub_session(
        work_dir,
        session_name,
        prompt,
        cfg_insert=default_cfg_insert(ctx),
    )
    session_path = session_dir / "session.toml"
    print(
        f"[sub_agent] created {session_path} "
        f"(edit cfg_insert / req before run)",
        file=sys.stderr,
    )

    state = ctx.setdefault("state", {})
    state["stop_loop"] = True
    print(
        f"[sub_agent] pending — then:\n"
        f"  uzcode --workdir {work_dir} --session {session_name}",
        file=sys.stderr,
    )
    return pending_payload(session_name)


def sub_agent_done(args: dict[str, Any], ctx: dict[str, Any]) -> str:
    """Write result.json under the current session directory."""
    if "result" in args and args.get("result") is not None:
        payload: Any = args["result"]
    else:
        payload = {
            k: v
            for k, v in args.items()
            if k not in {"result"} and v is not None
        }
        if "summary" not in payload or not str(payload.get("summary") or "").strip():
            raise ValueError("summary is required (or pass result=…)")

    session_dir = _session_dir_from_ctx(ctx)
    path = result_path(session_dir)
    if isinstance(payload, (dict, list)):
        text = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
    else:
        text = json.dumps({"summary": str(payload)}, indent=2, ensure_ascii=False) + "\n"
    path.write_text(text, encoding="utf-8")

    state = ctx.setdefault("state", {})
    state["stop_loop"] = True
    print(f"[sub_agent] wrote {path}", file=sys.stdout)
    return f"Wrote {RESULT_FILENAME} ({path.name})."
