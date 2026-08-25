# uzcode

[English](../README.md)

一個用 Python 寫的**極簡** AI Coding Agent。核心是薄薄一層**無常駐進程引擎**；對話與策略都放在你可以檢視、編輯、重放、分叉的 TOML 裡——**沒有隱藏記憶**。

**保持簡單。把控制權交給使用者。**

| 原則 | 含義 |
| --- | --- |
| 沒有隱藏記憶 | 每次執行都從 cfg 層 + `session.toml` 重建。引擎在 CLI 呼叫之間不保留任何狀態。 |
| 使用者擁有對話紀錄 | 可編輯歷史、工具結果、甚至先前的Agent回合，然後再跑一次。 |
| 薄核心 | 引擎只負責載入設定、呼叫 LLM、執行工具、迴圈。 |
| 其餘交給擴充 | Diff 預覽、日誌、skills、web、子Agent、權限 UX。 |
| 不污染工作區 | 不會自動 git。寫檔遵守每個工具各自的權限。 |
| 除錯 / 重放 | 每次執行前有 `bak/`，本次追加回合有 `diff/`，結束後有完整的 `session.toml`。 |
| 使用 Python | 不使用 TypeScript |

和其他Agent相比，uzcode 用**透明與可控**換掉便利功能（RAG、索引、REPL、自動 git）。如果你想看每一則訊息、控制每一次寫入，並在編輯 TOML 後重放一次請求，這就是那個Agent。

Python **≥ 3.11**。LLM 呼叫走 [LiteLLM](https://docs.litellm.ai/)（OpenAI Chat Completions 形狀）。設定合併使用 [overdict](https://github.com/youzi151/py-overdict)。

---

## 現況

uzcode 仍在開發中。核心引擎已完成，但擴充尚未全部實作，可能不穩定。
目前也還沒有任何安全機制。當 LLM 試圖透過 tool calls 執行 `run_shell` 或 `read_file` 時請小心。

---

## 安裝

從倉庫安裝（建議）：

```bash
uv sync
```

或可編輯安裝：

```bash
pip install -e .
```

`overdict` 會從 Git 拉取（[py-overdict](https://github.com/youzi151/py-overdict)）。請設定與你的 cfg 相符的 API key（預設 `OPENAI_API_KEY`，或 `llm.api_key` / `llm.api_key_env`）。

進入點：`uzcode` → `uzcode.cli:main`。

---

## 快速開始

```bash
# 1. 建立一個 session（最後一層 cfg；可包含 cfg_insert + [req]）
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

# 2. 執行。若 session.toml 已有 cfg_insert，--cfg 可省略。
uzcode --workdir . --session demo
# 等價寫法：
uzcode --workdir . --cfg @dev --session demo
```

每次執行會：

1. 複製 `session.toml` → `bak/session_<stamp>.toml`
2. 在記憶體中跑Agent迴圈
3. 把本次追加的回合寫到 `diff/diff_<stamp>.toml`
4. 覆寫 `session.toml`（保留你撰寫的 refs/messages；追加 assistant/tool 回合）

手動編輯 `session.toml` 再跑一次即可**重放**或**分叉**。複製整個 session 目錄即可分支出另一段對話。

---

## 工作區佈局

```text
{work_dir}/
├── .uzcode/
│   ├── cfgs/                  # 專案 cfg 層（可選）
│   │   ├── <name>.toml        # 一般 cfg 層
│   │   └── @<name>.toml       # 檔名以 '@' 開頭的組合 cfg 層，用 cfg_insert 把其他層插入此檔
│   ├── skills/                # Agent Skills 包（*/SKILL.md）
│   ├── exts/                  # 你的擴充（同名會覆寫內建）
│   └── sessions/<name>/
│       ├── session.toml       # 持久化對話紀錄 + 可選的 cfg_insert / [req]
│       ├── bak/               # 執行前快照
│       ├── diff/              # 本次執行追加的訊息
│       ├── sent/              # 送給 LLM 的請求
│       └── recv/              # 從 LLM 收到的回應
└── ...                        # 你的專案
```

引擎除了透過你啟用的工具寫檔外，不會寫到 session 目錄以外的地方（子Agent則會在子 session 旁寫 `result.json`）。

---

## CLI

```text
uzcode [--workdir DIR] [--cfg NAME_OR_PATH ...] --session NAME [--act ACTION ...]
uzcode act [--workdir DIR] [--cfg ...] --session NAME ACTION [ACTION ...]
```

| 旗標 | 作用 |
| --- | --- |
| `--workdir` | 專案根目錄（預設 `.`）。工具與 skills 都相對此路徑。 |
| `--cfg` | 依合併順序的 cfg 名稱或路徑。省略則只用 `session.toml`（含其中的 `cfg_insert`）。Session **永遠**是最後一層。 |
| `--session` | 必填。目錄 `{workdir}/.uzcode/sessions/<NAME>/`。名稱：`[A-Za-z0-9][A-Za-z0-9._-]*`。 |
| `--act` | 準備完成後，先跑具名擴充 action，再進入 LLM 迴圈。 |
| `--debug-litellm` | 開啟LiteLLM 除錯模式。 |

`uzcode act …` 只跑 action（不呼叫 LLM）。適合像 `file-changed` 這類會先改寫 `session.messages`、再由你決定要不要呼叫模型的場景。

CLI 會印出合併後的設定、cfg 層路徑，以及簡短結果。持久化（`bak` / `diff` / `session.toml`）由 CLI 負責；`CodingAgent.run` 只在記憶體中執行。

---

## 設定層

cfg 依此順序解析（第一個存在的檔案勝出）：

1. 使用者路徑（cwd 或 workdir，`.toml` 可省略）
2. `{workdir}/.uzcode/cfgs/{name}.toml`
3. 內建 `uzcode/cfgs/{name}.toml`

`cfg_insert` 會把其他 cfg **拼接到**目前檔案其餘內容**之前**。僅含別名的檔案（只有 `cfg_insert`）本身不構成一層。允許巢狀插入；循環會報錯。

```toml
# 內建 @dev.toml — 別名
cfg_insert = ["base", "programming"]
```

合併使用 overdict（後者覆蓋前者；`__merge` 控制覆蓋方式）。合併之後：

- `[req]` 會被剝離進 `Session`
- 其餘成為 `Config`（`llm`、`loop`、`tools`、`extension`、`exts`，以及給 `[skills]`、`[messagelib]` 等用的 `raw`）

`session.toml` 是**普通的最後一層 cfg 檔**。它可以貢獻 `cfg_insert`、`[llm]`、`[req]` 等。

### 內建 cfg

| Token | 用途 |
| --- | --- |
| `base` | 本機 OpenAI 相容 LLM、`__system` / `__skill` messagelib、日誌 + `llm_log`、停用 `sub_agent_done` |
| `programming` | `auto_loop`、檔案工具、shell、`sub_agent`、`task_summary` |
| `@dev` | `cfg_insert = ["base", "programming"]` |
| `gemini` | 經 LiteLLM 使用 Gemini（`gemini/…`，`GOOGLE_GENERATIVE_AI_API_KEY`） |
| `subagent` | 為子 session 啟用 `sub_agent_done` |

### LLM

```toml
[llm]
base_url = "https://api.openai.com/v1"
api_key_env = "OPENAI_API_KEY"   # 或設定 llm.api_key
model = "gpt-4o"
```

裸模型名會加上 `openai/` 前綴給 LiteLLM。已知前綴（`openai/`、`azure/`、`anthropic/`、`bedrock/`、`gemini/`、`vertex_ai/`、`ollama/`）維持原樣。

### 迴圈

```toml
[loop]
auto_loop = true          # false = 一次 LLM 呼叫 + 最多一批工具
max_iterations = 20
```

當最後一則助手訊息沒有 `tool_calls`、達到 `max_iterations`，或設定了 `state.stop_loop`（每個工具 / `after_tools` / `handle_request`）時停止。目前這批工具一定會跑完才結束迴圈。

### 工具（按名稱）

```toml
[tools.write_file]
enable = true             # 省略時預設 true；false = 不送給 LLM
permission = "ask"        # ask | approve | custom  （預設 ask）
preview_diff = true       # 由擴充消費（例如 file_cru）
retry = 0
on_failure = "abort"      # abort | continue | ask
```

| `permission` | 引擎行為 |
| --- | --- |
| `approve` | 執行 handler |
| `ask` | 內建 `(Y/n)`，除非該工具註冊了自訂 `ask` callback |
| `custom` | 預設**拒絕**（`skip=true`）。必須有 `before_tool` 擴充清掉 `skip` 才允許執行 |

沒有任何權限是依工具名稱寫死的。

### 擴充

```toml
[extension]
enable = ["logging", "file_cru", "skills", "shell", "web", "sub_agent"]
# 省略 enable = 載入所有發現的內建 + 專案擴充

[extension.order.before_llm]
logging = 10
skills = 20
```

`.uzcode/exts/` 下同名的專案擴充會**覆寫**內建。`extension.order.<hook>.<name>` 會覆寫傳給 `registry.on(...)` 的順序。

---

## Session 契約

`session.toml` 是持久化的真相來源。典型形狀：

```toml
cfg_insert = ["@dev"]

[req]
[[req.messages]]
ref = "__system"

[[req.messages]]
role = "user"
content = "Read @{file:README.md} and outline next steps"

# 執行後，assistant / tool 訊息會追加在這裡。
```

### 訊息

| 欄位 | 作用 |
| --- | --- |
| `role` | `system` / `user` / `assistant` / `tool` |
| `content` | 文字。磁碟上 mention 保持你撰寫的 `@{cmd:text}`。 |
| `ref` | `[messagelib.<ref>]` 藍圖名稱。先套用 lib 欄位，再由訊息欄位覆寫。 |
| `tool_call_id` / `name` / extras | 工具結果與供應商欄位（例如 `tool_calls`） |

`messagelib` 存在合併後的 cfg（`config.raw`）。內建 `base` 定義 `__system` 與 `__skill`。Skills 會在執行時把目錄寫進 `messagelib.__skill`（標記為 `<!-- uzcode:skills-catalog -->`）；這段展開**不會**寫回磁碟。

解析後 `content` 為空的訊息會從 API payload 中丟棄（因此空目錄時 `ref = "__skill"` 會被略過）。

寫回規則：

- 原始的 `ref` / user / system 行會保留
- 只追加本次執行的 assistant/tool 回合
- Mention 替換與目錄文字只留在記憶體
- 最後一次呼叫的 usage 存為 `[resp.usage]`

---

## 引擎（一次 CLI 呼叫）

引擎是**無常駐進程**的：一次呼叫就是 `f(cfg, session, workdir)`。Session 與 cfg 是顯式狀態；`AgentState` 只存在於該次執行。

```text
handle_request
  從 [skills].enable 種下 skills_enabled
  解析 user 訊息上的 @{cmd:text} → state.mentions
  跑 handle_request hooks（hydrate 待處理的子Agent等）
  把 mention.replacement 套到 content 的工作副本
  → stop_loop? 結束
before_llm → call_llm（LiteLLM + tools schema）→ after_llm
run_tools（before_tool → ask/execute → after_tool，整批）
after_tools
  → 還有 tool_calls 且 auto_loop 且未達 max_iterations？
     是 → before_llm
     否  → on_result → persist
```

LangGraph 節點只傳遞 `AgentState`。擴充看到的是短命的 `ctx`：`state`、`config`、`session`、`preparemeta`，以及可選的 `tool` / `error`。只有 `ctx["state"]` 會被寫回。

`CodingAgent.run` **不**碰磁碟。CLI（或你的呼叫端）必須自行 `copy_session_to_bak` / `persist_session`。

---

## Mentions

引擎會解析**使用者** `content` 裡的 `@{cmd:text}`。擴充精確匹配 `cmd`，並設定 `mention.replacement` 和／或預呼叫工具。替換套用在送給 LLM 的工作副本上；磁碟保留原始 `@{…}`。

| 語法 | 擴充 | 行為 |
| --- | --- | --- |
| `@{file:path}` / `@{folder:path}` | `file_cru` | 短索引 → `replacement` |
| `@{file!:path}` / `@{folder!:path}` | `file_cru` | 索引 + 預呼叫 `read_file` / `list_dir` |
| `@{skill:name}` | `skills` | `[skill: name]`（描述若 &lt; 50 字元則附上） |
| `@{skill!:name}` | `skills` | 同上 + 預呼叫 `read_skill` |
| `@{search:query}` / `@{fetch:url}` | `web` | 短索引（標題／連結；不含本文） |
| `@{search!:…}` / `@{fetch!:…}` | `web` | 索引 + 預呼叫 `web_search` / `web_fetch` |

引擎不解釋 `!`；它是 `cmd` 的一部分。找不到目標時會提示 `Continue? (y/N)`。

---

## Skills

包格式遵循 [Agent Skills spec](https://agentskills.io/specification)。uzcode 只尋找 `{workdir}/.uzcode/skills/**/SKILL.md`。目錄名**必須**等於 frontmatter 的 `name`。

```text
.uzcode/skills/deploy-app/
├── SKILL.md              # YAML frontmatter + markdown 正文
├── scripts/              # 可選；透過 sh 執行，不是 skill 自己跑
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

`name`：≤64，`[a-z0-9]+(-[a-z0-9]+)*`。`description`：必填，≤1024。未知 frontmatter 鍵會被忽略。不合規的包會被略過並在 stderr 發出警告。

漸進揭露：

| 層級 | 內容 | 方式 |
| --- | --- | --- |
| 1 Metadata | `name` + `description` 目錄 | `before_llm` → `messagelib.__skill` |
| 2 Instructions | 完整 `SKILL.md` 正文 | 工具 `read_skill` |
| 3 Resources | skill 根目錄下的檔案 | 工具 `read_file_in_skill`；腳本走 `sh` |

沒有 `skills:` API 欄位，也沒有 `invoke_skill`。Skills 不可執行；`scripts/` 只是普通檔案。

```toml
[skills]
# 省略 = 所有已註冊名稱
# enable = []                 # 無（目錄為空；read_* 拒絕）
# enable = ["deploy-app"]     # 白名單 ∩ 已註冊
```

引擎在 `handle_request` 中種下 `state.skills_enabled`。其他擴充可以改這個清單（ban），或呼叫 `registry.skill(...)`（僅執行時；不寫入磁碟）。後註冊的同名勝出。若你在 `handle_request` 裡註冊，請自行把名稱加進 `skills_enabled`（引擎播種已經跑過了）。

`read_file_in_skill` 的路徑相對 skill 根目錄（拒絕 `..` / 絕對路徑）。回傳值對 `sh` 使用**相對 workdir** 的路徑（cwd 永遠是 `work_dir`）。不會把絕對路徑回給 LLM。

---

## 內建工具（經由擴充）

核心只提供薄薄的 `ToolRegistry`。Handler 來自擴充。

| 工具 | 擴充 | 作用 |
| --- | --- | --- |
| `read_file` / `list_dir` / `grep` | `file_cru` | 讀取 |
| `write_file` / `edit_file` | `file_cru` | 建立 / 更新 |
| `read_skill` / `read_file_in_skill` | `skills` | 漸進載入 skill |
| `sh` | `shell` | Shell；cwd = `work_dir` |
| `web_search` / `web_fetch` | `web` | `ddgs` + `httpx` / `trafilatura` |
| `sub_agent` / `sub_agent_done` | `sub_agent` | 委派給另一個 session |

web：沒有 JS 渲染、付費搜尋 API、快取或二進位下載。

---

## 子Agent

子Agent是**另一個普通 session**，不是行程內巢狀的大腦。主 LLM 提出；你控制；子Agent必須呼叫 `sub_agent_done` 才能寫出 `result.json`。最後一則助手訊息**不是**結果。沒有 session `status` 欄位。

```text
main: tool sub_agent(prompt, session?)
  → ask: run-later | deny
  → later: 建立 .uzcode/sessions/<sub>/session.toml
            cfg_insert = [*main --cfg names_or_paths, "subagent"]
            tool result = {"status":"pending","sub_session":"<name>"}
            stop_loop
you:  必要時編輯子 session.toml
      uzcode --workdir <work> --session <name>    # --cfg 可選
      子Agent呼叫 sub_agent_done → result.json
you:  再跑一次主 session
      handle_request 從 result.json hydrate pending
      若仍 pending → 在 LLM 之前停止（不要捏造結果）
```

`sub_agent` 上的 `permission = "approve"` 視為 later（草稿 + pending）。`[exts.sub_agent] cfg_insert` 可以替換子Agent的層清單。你可以再呼叫 `sub_agent` 來巢狀（又一個 session；沒有深度計數器）。

---

## 自訂擴充

發現方式：

- 內建：`src/extensions/<name>/`（或 `<name>.py`）
- 專案：`{workdir}/.uzcode/exts/<name>/`（名稱衝突時優先）

每個模組必須匯出：

```python
def register(registry, config) -> None:
    ...
```

### Hooks

| Hook | 時機 |
| --- | --- |
| `handle_request` | 每次執行一次：種下 skills、解析 mentions、hydrate pending |
| `before_llm` | 每次 LLM 呼叫前（skills 目錄等） |
| `before_call_llm` | 僅副作用；`ctx["llm_request"]` 不含密鑰 |
| `after_llm` | completion 之後（若有則為 `ctx["llm_response"]`） |
| `before_tool` / `after_tool` | 每個工具呼叫（`ctx["tool"]`：name、arguments、skip、result、…） |
| `after_tools` | 整批之後；可設定 `stop_loop` |
| `on_result` / `on_error` | 執行結束 / 發生例外 |

```python
def register(registry, config):
    def before_llm(ctx):
        # 只改 ctx["state"]；回傳 ctx
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

`registry.action` 就是 `--act` / `uzcode act` / `CodingAgent.act` 會呼叫的東西。Action 可以改寫 `session.messages`；CLI 在持久化前會把它們同步進 `session_doc`。

---

## Python API

```python
from uzcode import CodingAgent

agent = CodingAgent(work_dir="./myproject")
config, session, meta = agent.prepare(["@dev"], "sfeature_aaa")
registry = agent.load_registry(config)

# 可選：擴充 action（不呼叫 LLM）
session, act_appended = agent.act(
    config, session, ["file-changed"], registry=registry
)

# LLM ↔ 工具迴圈；無磁碟 I/O
session, appended = agent.run(
    config, session, registry=registry, prepare_meta=meta
)

# 像 CLI 一樣持久化：
from uzcode.data.session import copy_session_to_bak, persist_session

stamp = "20260814_103000"
copy_session_to_bak(meta.session_dir, stamp)
persist_session(meta.session_dir, session, appended, stamp=stamp)
```

`prepare` → `cfg.prepare`：展開層、合併、建立 `Config` + `Session`。
`PrepareMeta` 帶有 `session_dir`、`session_path`、解析後的 `cfg_paths`，以及原始 `--cfg` 名稱或路徑（`cfg_raw_inputs`），供 `sub_agent` 這類擴充使用。
