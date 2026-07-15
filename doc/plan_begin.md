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
│   ├── registry.py
│   ├── read_file.py
│   ├── write_file.py
│   ├── edit_file.py
│   ├── list_dir.py
│   └── grep.py
└── middleware/
    ├── __init__.py
    ├── base.py          # hook 介面
    └── loader.py        # 從 .uzcode/mids/ 動態載入
```

### 2.2 工作目錄（執行時）

```text
{work_dir}/
├── .uzcode/
│   ├── cfg.toml             # 全域設定、loop、tool 權限、API Key
│   ├── mids/                # 使用者自訂 middleware
│   │   ├── preprocesser/
│   │   ├── logging/
│   │   └── ...
│   └── history/             # （可選）歷史 request 快照
├── req.toml                 # 本次請求（可由 CLI 指定其他檔案）
└── ... (專案檔案)
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

### Phase 2 — 內建 Tools

基礎集合（不內建 RAG / indexing）：

| Tool | 職責 |
|------|------|
| `read_file` | 讀取檔案 |
| `write_file` | 寫入檔案 |
| `edit_file` | 編輯／替換內容 |
| `list_dir` | 列出目錄 |
| `grep` | 簡單內容搜尋 |

行為由 `cfg.toml` 控制：`require_confirm`、`preview_diff`、`retry`、`on_failure`。  
核心尊重權限設定；preview / confirm 的 UX 留給 middleware。

**完成標準**：LLM 可發出 tool call，引擎執行後把 tool result 寫回 messages，並可繼續下一輪。

### Phase 3 — Middleware 系統

可介入階段：

- LLM 呼叫前 / 後
- Tool 執行前 / 後
- 最終結果
- 錯誤處理

從 `.uzcode/mids/` 依 config 順序動態載入。

**範例用途**：diff preview + 使用者確認、token/cost logging、多模型 request 轉換、自訂權限檢查。

**完成標準**：不改核心即可用 middleware 攔截 `write_file` / `edit_file` 做確認。

### Phase 4 — Loop 控制

- 依 config：`auto_loop`、`max_iterations`
- 啟用時：有 tool calls 就繼續，直到無 tool calls 或達上限

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
require_confirm = false

[tools.write_file]
require_confirm = true
preview_diff = true
retry = 0
on_failure = "abort"   # abort | continue | ask

[middleware]
order = ["preprocesser", "logging"]
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
        → Phase 2 Tools
            → Phase 3 Middleware
                → Phase 4 auto_loop
                    → Phase 5 範例與 API 打磨
```

---

**專案狀態**：Phase 0 完成；Phase 1 實作中（LangGraph 工作流 + LiteLLM）  
**參考**：與 Aider、OpenHands 相比，uzcode 專注透明度、可控性與極簡，方便 debug / replay。
