# uzcode 實作計畫

本文件依 [idea_begin.md](./idea_begin.md) 轉成可執行的實作路線圖。  
**核心原則**：Keep it simple, give control to the user.

---

## 1. 目標與原則

打造一個**極簡、stateless** 的 AI coding agent（純 Python），讓使用者完全掌握每一次請求與回應。


| 原則           | 含義                                             |
| ------------ | ---------------------------------------------- |
| Stateless 第一 | 每次執行只依完整的 `req.toml`，無隱藏狀態                     |
| 使用者主導        | 可任意修改歷史訊息、tool results、甚至先前 AI 回應              |
| 極簡核心         | 引擎只負責必要流程                                      |
| 高度可擴充        | diff preview、logging、權限、多模型轉換等皆由 middleware 實作 |
| 不汙染工作目錄      | 無自動 git、無未經確認的檔案變更                             |
| Debug 友好     | 易於 replay、fork 不同 request 版本                   |


---

## 2. 目標目錄結構

### 2.1 套件（程式碼）

```text
src/uzcode/
├── __init__.py          # CodingAgent 公開 API
├── cli.py               # CLI 入口
├── data/
│   ├── __init__.py
│   ├── config.py        # 載入 .uzcode/cfg.toml
│   └── request.py       # 載入 / 寫回 req.toml
├── engine.py            # 薄核心：handle_request → LLM ↔ tools ↔ loop
├── skills/              # SkillRegistry + discover
├── tools/
│   ├── __init__.py
│   └── registry.py      # 薄註冊表（實作由 middleware 提供）
└── middleware/
    ├── __init__.py
    ├── base.py          # hooks + registry.tool() / skill()
    └── loader.py        # 從 .uzcode/mids/ 動態載入
```

### 2.2 工作目錄（執行時）

```text
{work_dir}/
├── .uzcode/
│   ├── cfg.toml             # 全域設定、loop、tool 權限、API Key
│   ├── skills/              # Skill 檔（使用者放置；僅 */SKILL.md）
│   │   └── deploy-app/
│   │       └── SKILL.md
│   ├── mids/                # 使用者自訂 middleware（外部；同名覆寫內建）
│   │   └── ...
│   └── history/             # （可選）歷史 request 快照（Phase 8）
├── req.toml                 # 本次請求（可由 CLI 指定其他檔案）
└── ... (專案檔案)

src/middlewares/             # 內建 middleware（隨套件）
├── logging/
├── file_cru/                # CRU tools + @{file|folder[:!]:...} mentions
├── skills/                  # skills + @{skill|skill!:...} mentions
├── shell/                   # sh tool
├── web/                     # web_* tools + @{search|fetch[:!]:...} mentions
└── ...
```

---

## 3. 分階段實作

### Phase 0 — 專案骨架

- 建立 Python package `uzcode`、CLI entry point（`uzcode`）
- TOML 讀寫輔助（config / request）
- 提供範例 `.uzcode/cfg.toml` 與 `req.toml`
- 可執行 `uzcode --workdir ... --req ...`（先印出載入結果即可）

**完成標準**：能從 CLI 指定 workdir / req，正確載入並顯示設定與 messages。

### Phase 1 — 薄引擎（無 tools）

執行流程：

1. 載入 config + request
2. Before LLM middleware（此階段可為 no-op）
3. 呼叫 OpenAI Chat Completions API（固定此協定）
4. 將 assistant 回應 append 進 messages
5. After middleware
6. （可選）把結果寫回主要 `req.toml` 或指定輸出檔

**完成標準**：單輪對話可跑通，結果可透明寫回 TOML。

### Phase 2 — Middleware 系統

可介入階段：

- LLM 呼叫前 / 後
- Tool 執行前 / 後（單個 tool）；整批 tools 後（`after_tools`）
- 最終結果
- 錯誤處理

雙路徑發現：`src/middlewares/`（內建）與 `{work_dir}/.uzcode/mids/`（外部；同名外部優先）。  
各 mid 的 `__init__.py` 以 `register(registry, config)` 自行 `registry.on(hook, fn, order=..., name=...)` 註冊；執行順序依每 hook 的 effective order，可被 `cfg.toml` 的 `[middleware.order.<hook>]` 覆寫。

**範例用途**：token/cost logging、多模型 request 轉換、自訂權限檢查；寫檔 confirm / preview 於 Phase 3 與 tools 一併驗收。

**完成標準**：不改核心即可從雙路徑載入並執行 middleware（至少繞 LLM）；before/after tool hooks 已定義，供 Phase 3 使用。

### Phase 3 — Tools（以 middleware 提供）

核心只保留薄 `ToolRegistry` + 一輪 tool 執行；**工具實作無特權**，由 middleware 註冊（內建 `file_cru`）。

`file_cru`（create / read / update）：


| Tool         | CRU    | 職責      |
| ------------ | ------ | ------- |
| `read_file`  | read   | 讀取檔案    |
| `list_dir`   | read   | 列出目錄    |
| `grep`       | read   | 簡單內容搜尋  |
| `write_file` | create | 建立／覆寫檔案 |
| `edit_file`  | update | 編輯／替換內容 |


雙層設定：

1. `middleware.enable` — 是否載入提供 tools 的 mid（如 `file_cru`）
2. `[tools.<name>]` — 每個要送給 LLM 的 tool：`enable`、`permission`（`ask`  `approve`  `custom`）、`preview_diff`、`retry`、`on_failure`
  （未在 cfg 定義 `permission` 時一律視為 `ask`；無依 tool 名稱硬編碼）  
  - `approve`：直接執行  
  - `ask`：引擎內建 `(Y/n)`  
  - `custom`：引擎不提問；預設拒絕，由 `before_tool` middleware 清 `skip` 核准或留下拒絕結果

每次 tool 執行走 `before_tool` →（若 `permission = "ask"` 則引擎 `(Y/n)`）→ execute → `after_tool`；`preview_diff` / `custom` UX 由 middleware 實作，handler 本身不做權限判斷。

**完成標準**：LLM 可發出 tool call；引擎經 middleware 執行後把 tool result 寫回 messages；可依 cfg 關閉單一 tool 或對寫檔 `permission = "ask"` 攔截，無需改引擎。

### Phase 4 — Loop 控制

- 依 config：`auto_loop`、`max_iterations`
- 啟用時：有 tool calls 就繼續，直到無 tool calls 或達上限
- 停止條件依最後一輪 assistant 是否含 `tool_calls`
- `auto_loop=false`：一輪 LLM + 至多一輪 tools（等同 Phase 3）
- `stop_loop` in AgentState：用來標記結束 **agent loop**；可於 per-tool/`after_tools` 中設
- 兩層：LangGraph 節點只傳 `AgentState`；middleware 呼叫用短期 `ctx`（`state`/`config`/`tool`/`error`），引擎只寫回 `ctx["state"]`

**完成標準**：一次 CLI 呼叫可完成多輪 tool 迴圈，過程全程可從 `req.toml` 重播。

### Phase 5 — Skills

**專項計畫（權威）**：[plan_feature_skill.md](./plan_feature_skill.md)（Agent Skills 合規套件 + 漸進載入）。若與本節舊述衝突，以專項為準。

兩條來源匯入同一 runtime skill 表；目錄（name + description）經 `system_messages` 注入，全文／附屬檔按需經 tools 載入：

1. **檔案**：`{work_dir}/.uzcode/skills/**/SKILL.md`（目錄名 = frontmatter `name`）
2. **程式**：middleware `registry.skill(...)`，執行期加入，**不**寫入 skills 目錄

**引擎契約（系統級）：**


| 欄位／節點                        | 職責                                                                                                             |
| ---------------------------- | -------------------------------------------------------------------------------------------------------------- |
| `handle_request`（一次）         | 引擎：req `system` → `system_messages`；依 `[skills].enable` 注入 `skills_enabled`；再跑 mid hooks（可改變 `skills_enabled`） |
| `system_messages: list[str]` | mids 只 append；`call_llm` 合併成單一 `role=system` 再送 API；寫回 req 亦用合併結果                                              |
| `skills_enabled: list[str]`  | 可見 skill 名稱；目錄與 `read_*` 皆以此為準                                                                                 |


**執行腳本**：一般 `sh` tool（mid `shell`）；cwd 固定 `work_dir`；skill 本身不可執行。

**分層：**


| 層               | 職責                                                                                                                                |
| --------------- | --------------------------------------------------------------------------------------------------------------------------------- |
| 核心（薄）           | `SkillRegistry`／`discover`；`registry.skill(...)`；注入 `skills_enabled`；合併 `system_messages`                                         |
| 內建 mid `skills` | 載入檔案 skills；註冊 `read_skill`／`read_file_in_skill`；`before_llm` 將目錄 append 到 `system_messages`（標記 `<!-- uzcode:skills-catalog -->`） |
| 內建 mid `shell`  | 註冊 `sh`                                                                                                                           |
| 其他 mid          | `registry.skill(...)`；於 `handle_request` 改變 `skills_enabled`                                                                      |


**Cfg 草圖：**

```toml
[middleware]
enable = ["logging", "file_cru", "skills", "shell"]

[skills]
# 省略 = 全部；enable = [] 全關；enable = ["demo-skill"] 白名單
```

**本階段不做**：智慧匹配、skill 內嵌 tools、`src/skills/` pack、mid 寫檔、多根 Cursor／Claude 掃描。

**完成標準**：見 [plan_feature_skill.md](./plan_feature_skill.md) §9。

### Phase 6 — Mention

引擎在 `handle_request` **解析** `@{cmd:text}` → `AgentState.mentions`；mid 以 **exact `cmd` match** 處理並設 `mention.replacement`／預載 tools；引擎再把 `replacement` 套到 `message.content`。TOML 只存 `content`（`raw` 僅 runtime）。

| 語法 | Mid | 行為 |
| --- | --- | --- |
| `@{file:path}` / `@{folder:path}` | `file_cru` | 短索引 → `replacement` |
| `@{file!:path}` / `@{folder!:path}` | `file_cru` | 短索引 + 預載 `read_file`／`list_dir` |
| `@{skill:name}` | `skills` | `[skill: name]` or `[skill: name | desc: …]` (desc only if under 50 chars) |
| `@{skill!:name}` | `skills` | same index + precall `read_skill` |

- Message：`content`（TOML／送 LLM）；runtime `raw` = 原始（含 `@{...}`），寫回前還原進 `content`
- Mention 欄位：`{cmd, text, handled, raw, msg_index, replacement}`
- 對象不存在時 `Continue? (y/N)`（空／`n` = 中止）

**完成標準**：req 含上述 mention 時，送入 LLM 前 `content` 已展開或 tool result 已預載；寫回 TOML 的 `content` 仍為原始（含 `@{...}`）。

### Phase 7 — Web Search/Fetch

分層：

| 層 | 職責 |
| --- | ---- |
| 內建 mid **`web`** | 註冊 `web_search`／`web_fetch` tools；`handle_request` 處理 `@{search\|fetch[:!]:...}` |
| 引擎 | 只解析 `@{cmd:text}` 結構 |

| Tool | 職責 |
| --- | ---- |
| `web_search` | 關鍵字搜尋，回傳標題／URL／摘要列表 |
| `web_fetch` | 抓取單一 URL，抽出可讀正文（markdown／text），截斷後回傳 |

**依賴選擇（建議）：**

| 用途 | 套件 | 理由 |
| --- | ---- | ---- |
| Search | **`ddgs`**（原 `duckduckgo-search`，已更名） | 免 API key；text search API 穩定；v9+ 為 metasearch（可選 backend）。**不要**再裝舊名 `duckduckgo-search` |
| Fetch HTTP | **`httpx`** | 現代 HTTP client；timeout／redirect 好控 |
| HTML → 正文 | **`trafilatura`** | 去導覽／廣告、可輸出 markdown；比裸 `html2text` 更適 LLM |

**不採用（v1）：** Tavily／SerpAPI／Brave Search API（需 key／付費）；Playwright／瀏覽器渲染（過重）；自幹 DuckDuckGo HTML scrape。

**Mention（`web` mid，exact `cmd`）：**

```text
@{search:python for loop}     → replacement 短索引（需 tool）
@{search!:python for loop}    → 預載 web_search
@{fetch:https://example.com}  → replacement 短索引
@{fetch!:https://example.com} → 預載 web_fetch
```

`cmd` 含 `!` 與否由 mid 全字串比對決定；引擎不解釋 bang。tool 未註冊時 skip／stderr 提示。

**Cfg 草圖：**

```toml
[middleware]
enable = ["logging", "file_cru", "skills", "shell", "web"]

[tools.web_search]
enable = true
permission = "approve"
# max_results = 5
# backend = "auto"

[tools.web_fetch]
enable = true
permission = "approve"
# max_chars = 32768
# timeout_sec = 30
```

**本階段不做**：JS 渲染、付費搜尋 API、本機快取／index、跳脫、下載二進位。

**完成標準**：啟用 `web` 後 LLM 可呼叫 `web_*`；req 含 `@{search!:...}`／`@{fetch!:...}` 時預載 tool result；寫回可 replay。

### Phase 8 — History

執行成功後可選快照 request 到 `.uzcode/history/`（時間戳或 hash 複本）。掛點：`on_result` mid，或 `engine.run` 成功後的薄 helper。須經 cfg 開啟。

**完成標準**：開啟後每次成功執行在 `.uzcode/history/` 留下可 replay 的 request 複本。

### Pending（未排期）

- 公開 API 打磨：`CodingAgent(work_dir).run(request_path=...)`
- README（安裝、CLI、cfg / req 契約、自訂 middleware）

---

## 4. 資料契約

### 4.1 `cfg.toml`（草圖）

```toml
[llm]
base_url = "https://api.openai.com/v1"
api_key_env = "OPENAI_API_KEY"
model = "gpt-4o"

[loop]
auto_loop = true
max_iterations = 20

[tools.read_file]
enable = true
permission = "approve"   # approve | ask | custom

[tools.list_dir]
enable = true
permission = "approve"

[tools.grep]
enable = true
permission = "approve"

[tools.write_file]
enable = true
permission = "ask"
preview_diff = true
retry = 0
on_failure = "abort"   # abort | continue | ask

[tools.edit_file]
enable = true
permission = "ask"
preview_diff = true

[tools.web_search]
enable = true
permission = "approve"

[tools.web_fetch]
enable = true
permission = "approve"

[middleware]
enable = ["logging", "file_cru", "skills", "shell", "web"]

[skills]
# omit = all discovered; empty = inject none
# enable = ["my_skill"]

[middleware.order.before_llm]
logging = 10
skills = 20

[middleware.order.after_llm]
logging = 100

[middleware.order.before_tool]
file_cru = 50
```

### 4.2 `req.toml`（草圖）

```toml
[[messages]]
role = "system"
content = "You are a coding agent..."

[[messages]]
role = "user"
content = "請讀取 README 並摘要"

# 執行後可 append assistant / tool messages，供下次提問與 replay
```

### 4.3 CLI

```bash
uzcode --workdir ./myproject --req request.toml
uzcode --req request_v1.toml          # 可指定輸出路徑以利版本控制
```

---

## 5. 錯誤與安全（v1）

- Tool 失敗依 config 的 `retry` / `on_failure`
- Preview / Confirm 由 middleware 實作，核心不硬編碼互動 UX
- 核心不執行危險操作，除非設定明確允許
- 不自動 git commit / push

---

## 6. v1 明確不做

- RAG / codebase indexing
- 核心內建多模型（留給 middleware）
- 自動 git 操作
- 完整 CLI REPL（列為未來擴充）

---

## 7. 驗收標準（整體）

1. 一次 CLI 執行：載入 `req.toml` → LLM + tools 迴圈 → 結果透明寫回（或指定輸出檔）
2. 使用者可手改 `req.toml` 後直接 replay / fork
3. Middleware 可攔截寫檔類 tool，實作 confirm / preview，無需改引擎
4. 工作目錄無未確認變更、無自動 git 副作用

---

## 8. 建議實作順序（摘要）

```text
Phase 0 骨架
    → Phase 1 單輪 LLM
        → Phase 2 Middleware
            → Phase 3 Tools
                → Phase 4 auto_loop
                    → Phase 5 Skills
                        → Phase 6 Mention (engine parse + file_cru/skills)
                            → Phase 7 Web (web tools + search/fetch mentions)
                                → Phase 8 History
Pending: CodingAgent API、README、內建 skill pack、智慧匹配 …
```

---

**專案狀態**：Phase 0–6 完成（Mention）；下一步 Phase 7 Web Search/Fetch（`ddgs` + `httpx`/`trafilatura`）
**參考**：與 Aider、OpenHands 相比，uzcode 專注透明度、可控性與極簡，方便 debug / replay。