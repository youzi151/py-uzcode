# uzcode

[中文](doc/README_zh.md)

A **minimal** AI coding agent in Python. Thin **stateless engine**; conversation and policy live in TOML you can inspect, edit, replay, and fork — **no hidden memory**.

**Keep it simple. Give control to the user.**

| Principle | Meaning |
| --- | --- |
| No hidden memory | Each run is rebuilt from cfg layers + `session.toml`. The engine keeps nothing between CLI invocations. |
| User-owned transcript | Edit history, tool results, even prior assistant turns, then re-run. |
| Thin core | The engine only loads config, calls the LLM, runs tools, and loops. |
| Extensions do the rest | Diff preview, logging, skills, web, sub-agents, permissions UX. |
| No workspace pollution | No automatic git. File writes respect per-tool permission. |
| Debug / replay | `bak/` before each run, `diff/` of appended turns, full `session.toml` after. |
| Use Python | not TypeScript |

Compared with other agents, uzcode trades convenience features (RAG, indexing, REPL, auto-git) for **transparency and control**. If you want to see every message, gate every write, and replay a request after editing TOML, this is the agent.

Python **≥ 3.11**. LLM calls go through [LiteLLM](https://docs.litellm.ai/) (OpenAI Chat Completions shape). Config merge uses [overdict](https://github.com/youzi151/py-overdict).

---

## Status

uzcode is still in development. The core engine is complete, but the extensions are not yet fully implemented. it might not be stable.
and there is no any security features yet. be careful when LLM trying to tool calls run_shell or read_file.

---

## Install

From the repo (recommended):

```bash
uv sync
```

Or editable install:

```bash
pip install -e .
```

`overdict` is pulled from Git ([py-overdict](https://github.com/youzi151/py-overdict)). Set an API key matching your cfg (`OPENAI_API_KEY` by default, or `llm.api_key` / `llm.api_key_env`).

Entry point: `uzcode` → `uzcode.cli:main`.

---

## Quick start

```bash
# 1. Create a session (last cfg layer; may include cfg_insert + [req])
mkdir -p .uzcode/sessions/demo
cat > .uzcode/sessions/demo/session.toml << 'EOF'
cfg_insert = ["@dev"]

[req]
[[req.messages]]
ref = "__system"

[[req.messages]]
role = "user"
content = "List the files in this directory and summarize README.md"
EOF

# 2. Run. --cfg is optional when session.toml already has cfg_insert.
uzcode --workdir . --session demo
# equivalent:
uzcode --workdir . --cfg @dev --session demo
```

Each run:

1. Copies `session.toml` → `bak/session_<stamp>.toml`
2. Runs the agent loop in memory
3. Writes appended turns to `diff/diff_<stamp>.toml`
4. Overwrites `session.toml` (authored refs/messages kept; assistant/tool turns appended)

Hand-edit `session.toml` and run again to **replay** or **fork**. Copy the session directory to branch a conversation.

---

## Workspace layout

```text
{work_dir}/
├── .uzcode/
│   ├── cfgs/                  # project cfg layers (optional)
│   │   ├── <name>.toml        # regular cfg layer
│   │   └── @<name>.toml     # combined cfg layers with '@' at the beginning, use cfg_insert to insert other layers into this file
│   ├── skills/                # Agent Skills packs (*/SKILL.md)
│   ├── exts/                  # your extensions (same name overrides built-in)
│   └── sessions/<name>/
│       ├── session.toml       # durable transcript + optional cfg_insert / [req]
│       ├── bak/               # pre-run snapshots
│       ├── diff/              # this-run appended messages
│       ├── sent/              # sent requests to the LLM
│       └── recv/              # received responses from the LLM
└── ...                        # your project
```

The engine never writes outside the session directory except through tools you enable (and, for sub-agents, `result.json` next to the sub session).

---

## CLI

```text
uzcode [--workdir DIR] [--cfg NAME_OR_PATH ...] --session NAME [--act ACTION ...]
uzcode act [--workdir DIR] [--cfg ...] --session NAME ACTION [ACTION ...]
```

| Flag | Role |
| --- | --- |
| `--workdir` | Project root (default `.`). Tools and skills are relative to this. |
| `--cfg` | Cfg names or paths in merge order. Omit to use only `session.toml` (including its `cfg_insert`). Session is **always** the last layer. |
| `--session` | Required. Directory `{workdir}/.uzcode/sessions/<NAME>/`. Name: `[A-Za-z0-9][A-Za-z0-9._-]*`. |
| `--act` | After prepare, run named extension actions, then the LLM loop. |
| `--debug-litellm` | Enable LiteLLM debug logging. |

`uzcode act …` runs actions only (no LLM). Use this for things like `file-changed` that mutate `session.messages` before you decide to call the model.

The CLI prints the merged config, cfg layer paths, and a short result. Persistence (`bak` / `diff` / `session.toml`) is CLI-owned; `CodingAgent.run` is in-memory only.

---

## Config layers

Tokens resolve in this order (first existing file wins):

1. User path (cwd or workdir, `.toml` optional)
2. `{workdir}/.uzcode/cfgs/{name}.toml`
3. Built-in `uzcode/cfgs/{name}.toml`

`cfg_insert` splices other cfgs **before** the rest of the current file. Alias-only files (only `cfg_insert`) add no layer of their own. Nested inserts are allowed; cycles raise.

```toml
# built-in @dev.toml — alias
cfg_insert = ["base", "programming"]
```

Merge is overdict (later layers win; `__merge` controls merge method). After merge:

- `[req]` is peeled off into the `Session`
- Everything else becomes `Config` (`llm`, `loop`, `tools`, `extension`, `exts`, plus `raw` for `[skills]`, `[messagelib]`, …)

`session.toml` is a **normal last cfg file**. It can contribute `cfg_insert`, `[llm]`, `[req]`, etc.

### Built-in cfgs

| Token | Purpose |
| --- | --- |
| `base` | Local OpenAI-compatible LLM, `__system` / `__skill` messagelib, logging + `llm_log`, `sub_agent_done` disabled |
| `programming` | `auto_loop`, file tools, shell, `sub_agent`, `task_summary` |
| `@dev` | `cfg_insert = ["base", "programming"]` |
| `gemini` | Gemini via LiteLLM (`gemini/…`, `GOOGLE_GENERATIVE_AI_API_KEY`) |
| `subagent` | Enables `sub_agent_done` for child sessions |

### LLM

```toml
[llm]
base_url = "https://api.openai.com/v1"
api_key_env = "OPENAI_API_KEY"   # or set llm.api_key
model = "gpt-4o"
```

Bare model names are prefixed `openai/` for LiteLLM. Known prefixes (`openai/`, `azure/`, `anthropic/`, `bedrock/`, `gemini/`, `vertex_ai/`, `ollama/`) are left as-is.

### Loop

```toml
[loop]
auto_loop = true          # false = one LLM call + at most one tool batch
max_iterations = 20
```

Stop when the last assistant message has no `tool_calls`, `max_iterations` is reached, or `state.stop_loop` is set (per-tool / `after_tools` / `handle_request`). The current tool batch always finishes before the loop ends.

### Tools (per name)

```toml
[tools.write_file]
enable = true             # default true if omitted; false = not sent to the LLM
permission = "ask"        # ask | approve | custom  (default ask)
preview_diff = true       # consumed by extensions (e.g. file_cru)
retry = 0
on_failure = "abort"      # abort | continue | ask
```

| `permission` | Engine behavior |
| --- | --- |
| `approve` | Run the handler |
| `ask` | Built-in `(Y/n)` unless the tool registered a custom `ask` callback |
| `custom` | Default **deny** (`skip=true`). A `before_tool` extension must clear `skip` to allow |

No permission is hardcoded by tool name.

### Extensions

```toml
[extension]
enable = ["logging", "file_cru", "skills", "shell", "web", "sub_agent"]
# omit enable = load every discovered built-in + project ext

[extension.order.before_llm]
logging = 10
skills = 20
```

Same-name project ext under `.uzcode/exts/` **overrides** the built-in. `extension.order.<hook>.<name>` overrides the order passed to `registry.on(...)`.

---

## Session contract

`session.toml` is the durable source of truth. Typical shape:

```toml
cfg_insert = ["@dev"]

[req]
[[req.messages]]
ref = "__system"

[[req.messages]]
role = "user"
content = "Read @{file:README.md} and outline next steps"

# After a run, assistant / tool messages are appended here.
```

### Messages

| Field | Role |
| --- | --- |
| `role` | `system` / `user` / `assistant` / `tool` |
| `content` | Text. Mentions stay as authored `@{cmd:text}` on disk. |
| `ref` | Name of a `[messagelib.<ref>]` blueprint. Lib fields first; message fields override. |
| `tool_call_id` / `name` / extras | Tool results and provider fields (e.g. `tool_calls`) |

`messagelib` lives in merged cfg (`config.raw`). Built-in `base` defines `__system` and `__skill`. Skills write the catalog into `messagelib.__skill` at runtime (marked `<!-- uzcode:skills-catalog -->`); that expansion is **not** written back.

Empty resolved `content` drops the message from the API payload (so `ref = "__skill"` with an empty catalog is skipped).

Write-back rules:

- Original `ref` / user / system lines are preserved
- Only this run’s assistant/tool turns are appended
- Mention replacements and catalog text stay in-memory
- Last-call usage is stored as `[resp.usage]`

---

## Engine (one CLI invocation)

The engine is **stateless**: one invocation is `f(cfg, session, workdir)`. Session and cfg are the explicit state; `AgentState` exists only for that run.

```text
handle_request
  seed skills_enabled from [skills].enable
  parse @{cmd:text} on user messages → state.mentions
  run handle_request hooks (hydrate pending sub-agents, etc.)
  apply mention.replacement onto a working copy of content
  → stop_loop? end
before_llm → call_llm (LiteLLM + tools schema) → after_llm
run_tools (before_tool → ask/execute → after_tool, full batch)
after_tools
  → more tool_calls and auto_loop and under max_iterations?
     yes → before_llm
     no  → on_result → persist
```

LangGraph nodes pass `AgentState` only. Extensions see a short-lived `ctx`: `state`, `config`, `session`, `preparemeta`, optional `tool` / `error`. Only `ctx["state"]` is written back.

`CodingAgent.run` does **not** touch disk. The CLI (or your caller) must `copy_session_to_bak` / `persist_session`.

---

## Mentions

The engine parses `@{cmd:text}` in **user** `content`. Extensions match `cmd` exactly and set `mention.replacement` and/or pre-call tools. Replacements apply to the working copy sent to the LLM; disk keeps the raw `@{…}`.

| Syntax | Extension | Behavior |
| --- | --- | --- |
| `@{file:path}` / `@{folder:path}` | `file_cru` | Short index → `replacement` |
| `@{file!:path}` / `@{folder!:path}` | `file_cru` | Index + pre-call `read_file` / `list_dir` |
| `@{skill:name}` | `skills` | `[skill: name]` (description if &lt; 50 chars) |
| `@{skill!:name}` | `skills` | Same + pre-call `read_skill` |
| `@{search:query}` / `@{fetch:url}` | `web` | Short index (title/link; no body) |
| `@{search!:…}` / `@{fetch!:…}` | `web` | Index + pre-call `web_search` / `web_fetch` |

The engine does not interpret `!`; that is part of `cmd`. Missing targets prompt `Continue? (y/N)`.

---

## Skills

Pack format follows the [Agent Skills spec](https://agentskills.io/specification). uzcode only discovers `{workdir}/.uzcode/skills/**/SKILL.md`. Directory name **must** equal frontmatter `name`.

```text
.uzcode/skills/deploy-app/
├── SKILL.md              # YAML frontmatter + markdown body
├── scripts/              # optional; run via sh, not by the skill itself
├── references/
└── assets/
```

```markdown
---
name: deploy-app
description: Deploy the app to staging or production. Use when deploying, releasing, or changing environments.
---

# Deploy App
…
```

`name`: ≤64, `[a-z0-9]+(-[a-z0-9]+)*`. `description`: required, ≤1024. Unknown frontmatter keys are ignored. Non-compliant packs are skipped with a stderr warning.

Progressive disclosure:

| Level | What | How |
| --- | --- | --- |
| 1 Metadata | `name` + `description` catalog | `before_llm` → `messagelib.__skill` |
| 2 Instructions | Full `SKILL.md` body | tool `read_skill` |
| 3 Resources | files under the skill root | tool `read_file_in_skill`; scripts via `sh` |

There is no `skills:` API field and no `invoke_skill`. Skills are not executable; `scripts/` are ordinary files.

```toml
[skills]
# omit = all registered names
# enable = []                 # none (catalog empty; read_* refuse)
# enable = ["deploy-app"]     # whitelist ∩ registered
```

The engine seeds `state.skills_enabled` in `handle_request`. Other extensions may mutate that list (ban) or call `registry.skill(...)` (runtime-only; not written to disk). Later same-name registration wins. If you register in `handle_request`, append the name to `skills_enabled` yourself (engine seeding already ran).

`read_file_in_skill` paths are relative to the skill root (`..` / absolute rejected). Return values use **workdir-relative** paths for `sh` (cwd is always `work_dir`). No absolute paths are returned to the LLM.

---

## Built-in tools (via extensions)

Core ships a thin `ToolRegistry`. Handlers come from extensions.

| Tool | Ext | Role |
| --- | --- | --- |
| `read_file` / `list_dir` / `grep` | `file_cru` | Read |
| `write_file` / `edit_file` | `file_cru` | Create / update |
| `read_skill` / `read_file_in_skill` | `skills` | Progressive skill load |
| `sh` | `shell` | Shell; cwd = `work_dir` |
| `web_search` / `web_fetch` | `web` | `ddgs` + `httpx` / `trafilatura` |
| `sub_agent` / `sub_agent_done` | `sub_agent` | Delegate to another session |

web: no JS rendering, paid search APIs, cache, or binary download.

---

## Sub-agent

A sub-agent is **another normal session**, not an in-process nested brain. The main LLM proposes; you gate; the child must call `sub_agent_done` to write `result.json`. The last assistant message is **not** the result. There is no session `status` field.

```text
main: tool sub_agent(prompt, session?)
  → ask: run-later | deny
  → later: create .uzcode/sessions/<sub>/session.toml
            cfg_insert = [*main --cfg names_or_paths, "subagent"]
            tool result = {"status":"pending","sub_session":"<name>"}
            stop_loop
you:  edit sub session.toml if needed
      uzcode --workdir <work> --session <name>    # --cfg optional
      child calls sub_agent_done → result.json
you:  re-run main
      handle_request hydrates pending from result.json
      if still pending → stop before LLM (do not invent a result)
```

`permission = "approve"` on `sub_agent` is treated as later (draft + pending). `[exts.sub_agent] cfg_insert` can replace the child’s layer list. You may nest by calling `sub_agent` again (another session; has no depth counter).

---

## Custom extensions

Discovery:

- Built-in: `src/extensions/<name>/` (or `<name>.py`)
- Project: `{workdir}/.uzcode/exts/<name>/` (wins on name clash)

Each module must export:

```python
def register(registry, config) -> None:
    ...
```

### Hooks

| Hook | When |
| --- | --- |
| `handle_request` | Once per run: seed skills, parse mentions, hydrate pending |
| `before_llm` | Before each LLM call (skills catalog, etc.) |
| `before_call_llm` | Side-effect only; `ctx["llm_request"]` has no secrets |
| `after_llm` | After the completion (`ctx["llm_response"]` when present) |
| `before_tool` / `after_tool` | Per tool call (`ctx["tool"]`: name, arguments, skip, result, …) |
| `after_tools` | After the full batch; may set `stop_loop` |
| `on_result` / `on_error` | End of run / on exception |

```python
def register(registry, config):
    def before_llm(ctx):
        # mutate ctx["state"] only; return ctx
        return ctx

    registry.on("before_llm", before_llm, order=20, name="my_ext")
    registry.tool(
        "my_tool",
        description="…",
        parameters={"type": "object", "properties": {}},
        handler=lambda args, ctx: "ok",
    )
    registry.skill(
        "team-conventions",
        description="Apply team Python conventions when editing this repo.",
        body="Prefer pathlib; never commit secrets.",
    )
    registry.action("file-changed", on_file_changed, order=0)
```

`registry.action` is what `--act` / `uzcode act` / `CodingAgent.act` invoke. Actions may mutate `session.messages`; CLI syncs them into `session_doc` before persist.

---

## Python API

```python
from uzcode import CodingAgent

agent = CodingAgent(work_dir="./myproject")
config, session, meta = agent.prepare(["@dev"], "sfeature_aaa")
registry = agent.load_registry(config)

# optional: extension actions (no LLM)
session, act_appended = agent.act(
    config, session, ["file-changed"], registry=registry
)

# LLM ↔ tools loop; no disk I/O
session, appended = agent.run(
    config, session, registry=registry, prepare_meta=meta
)

# persist like the CLI:
from uzcode.data.session import copy_session_to_bak, persist_session

stamp = "20260814_103000"
copy_session_to_bak(meta.session_dir, stamp)
persist_session(meta.session_dir, session, appended, stamp=stamp)
```

`prepare` → `cfg.prepare`: expand layers, merge, build `Config` + `Session`.
`PrepareMeta` carries `session_dir`, `session_path`, resolved `cfg_paths`, and raw `--cfg` names or paths (`cfg_raw_inputs`) for extensions such as `sub_agent`.
