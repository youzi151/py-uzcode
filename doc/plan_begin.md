# uzcode 實作計畫

本文件依 [idea_begin.md](./idea_begin.md) 轉成可執行的實作路線圖。  
**核心原則**：Keep it simple, give control to the user.

---

## 1. 目標與原則

打造一個**極簡、stateless** 的 AI coding agent（純 Python），讓使用者完全掌握每一次請求與回應。

| 原則 | 含義 |
|------|------|
| Stateless 第一 | 每次執行只依完整的 `req.toml`，無隱藏狀態 |
| 使用者主導 | 可任意修改歷史訊息、tool results、甚至先前 AI 回應 |
| 極簡核心 | 引擎只負責必要流程 |
| 高度可擴充 | diff preview、logging、權限、多模型轉換等皆由 middleware 實作 |
| 不汙染工作目錄 | 無自動 git、無未經確認的檔案變更 |
| Debug 友好 | 易於 replay、fork 不同 request 版本 |

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
├── engine.py            # 薄核心：LLM ↔ tools ↔ loop
├── tools/
│   ├── __init__.py
│   └── registry.py      # 薄註冊表（實作由 middleware 提供）
└── middleware/
    ├── __init__.py
    ├── base.py          # hook 介面 + registry.tool()
    └── loader.py        # 從 .uzcode/mids/ 動態載入
```

### 2.2 工作目錄（執行時）

```text
{work_dir}/
├── .uzcode/
│   ├── cfg.toml             # 全域設定、loop、tool 權限、API Key
│   ├── mids/                # 使用者自訂 middleware（外部；同名覆寫內建）
│   │   ├── preprocesser/
│   │   └── ...
│   └── history/             # （可選）歷史 request 快照
├── req.toml                 # 本次請求（可由 CLI 指定其他檔案）
└── ... (專案檔案)

src/middlewares/             # 內建 middleware（隨套件）
├── logging/
├── file_cru/                # read/list/grep + write/edit tools
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

| Tool | CRU | 職責 |
|------|-----|------|
| `read_file` | read | 讀取檔案 |
| `list_dir` | read | 列出目錄 |
| `grep` | read | 簡單內容搜尋 |
| `write_file` | create | 建立／覆寫檔案 |
| `edit_file` | update | 編輯／替換內容 |

雙層設定：

1. `middleware.enable` — 是否載入提供 tools 的 mid（如 `file_cru`）
2. `[tools.<name>]` — 每個要送給 LLM 的 tool：`enable`、`permission`（`ask` \| `approve` \| `custom`）、`preview_diff`、`retry`、`on_failure`  
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

### Phase 5 — 打磨與擴充入口

- 內建範例：`logging` middleware、`preprocesser`（`@file` / `@folder` 展開 stub）
- （可選）執行後快照到 `.uzcode/history/`
- 公開 Python API：

```python
from uzcode import CodingAgent

agent = CodingAgent(work_dir="./myproject")
result = agent.run(request_path="request.toml")
```

**完成標準**：文件與範例足以讓使用者自訂一個 middleware 並掛上。

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

[middleware]
enable = ["logging", "file_cru"]

[middleware.order.before_llm]
logging = 10

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
                    → Phase 5 範例與 API 打磨
```

---

**專案狀態**：Phase 0–4 完成（`auto_loop`：有 `tool_calls` 則繼續，無則停；達 `max_iterations` 亦停）；下一步 Phase 5  
**參考**：與 Aider、OpenHands 相比，uzcode 專注透明度、可控性與極簡，方便 debug / replay。
