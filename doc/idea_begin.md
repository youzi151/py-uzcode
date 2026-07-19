# uzcode

一個極簡、stateless 的 AI coding agent，以純 Python 實作，強調**使用者完全控制權**與**可擴充性**。

## 設計理念

- **Stateless 第一**：每次執行都基於完整的 `request.toml`，無隱藏狀態。
- **使用者主導**：使用者可以任意修改歷史訊息、tool results、甚至 AI 之前的回應。
- **極簡核心**：骨幹保持最小，只負責必要流程。
- **高度可擴充**：所有進階行為（diff preview、logging、權限、多模型轉換等）都透過 middleware 實現。
- **不汙染工作目錄**：無自動 git 操作、無未經確認的檔案變更。
- **Debug 友好**：易於 replay、fork 不同 request 版本。

## 專案結構

```bash
{work_dir}/
├── .uzcode/
│   ├── cfg.toml             # 全域設定、loop 策略、tool 權限、API Key
│   ├── skills/              # Skill 檔
│   │   ├── my_skill/
│   │   │   └── SKILL.md
│   │   └── ...
│   ├── mids/                # 使用者自訂 middleware
│   │   ├── preprocesser     # 自動展開 `@file`、`@folder` 等標記
│   │   │   └─ __init__.py
│   │   ├── logging
│   │   │   └─ __init__.py
│   │   ├── tool_websearch
│   │   │   └─ __init__.py
│   │   └── ...
│   └── history/             # (可選) 歷史 request 快照
├── req.toml                 # 本次請求（可由 CLI 指定其他檔案）
└── ... (你的專案檔案)
```

## 核心元件

### 1. Config (` .uzcode/cfg.toml`)
- LLM 設定（固定使用 OpenAI Chat Completions API）
- Loop 設定（`auto_loop`、`max_iterations` 等）
- 各 Tool 的權限與行為（`require_confirm`、`preview_diff`、`retry`、`on_failure`）
- Middleware 載入順序與設定

### 2. Request (`req.toml`)
- 存放 要送給LLM的資訊
- 完整 `messages` 陣列（system、user、assistant、tool）
- 執行後可以從output中提取下次提問所需相關資訊與紀錄，如 user message, llm response, etc.，更新進req.toml中

### 3. Middleware 系統
最強大的擴充機制。可在以下階段介入：
- LLM 呼叫前後
- Tool 執行前後
- 最終結果
- 錯誤處理
- etc.

**用途範例**：
- Diff preview + 使用者確認
- Token / cost / logging
- Skills 注入、`@file` / `@folder` 展開
- 未來多模型轉換（middleware 轉換 request）
- 自訂權限檢查

### 4. Skills（檔案 + runtime 註冊）
- **檔案**：`.uzcode/skills/**/SKILL.md`（[Agent Skills](https://agentskills.io/specification) 合規；目錄名 = `name`）
- **程式**：middleware 以 `registry.skill(...)` 在執行期加入（不寫檔）
- 內建 `skills` mid：`before_llm` 注入目錄（name + description）；全文／附屬檔經 `read_skill`／`read_file_in_skill`；腳本經 `sh`
- 詳見 [plan_feature_skill.md](./plan_feature_skill.md)

### 5. Agent Engine（核心極薄）
執行流程：
1. 載入 config + request
2. Before LLM middleware
3. 呼叫 OpenAI Chat Completions（帶 tools）
4. 處理 tool calls（尊重 config 權限）
5. 如啟用 auto_loop 則繼續直到無 tool calls
6. After middleware
7. (可選) 把重要結果 save 回主要 req.toml

### 6. Tools（基礎集合）
- `read_file` / `write_file` / `edit_file` / `list_dir` / `grep`
- `read_skill` / `read_file_in_skill`（skills mid）
- `sh`（shell mid；cwd = work_dir）

不內建 RAG、codebase indexing 等複雜功能。

### 7. 錯誤與安全性
- Tool 失敗處理依 config 中的 retry / on_failure 設定
- Preview / Confirm 機制交由 middleware 實作
- 核心不執行危險操作，除非明確設定

## 使用方式

```bash
# 基本執行
uzcode --workdir ./myproject --req request.toml

# 指定輸出（推薦用於版本控制）
uzcode --req request_v1.toml 
```

也可作為 Python package 使用：

```python
from uzcode import CodingAgent

agent = CodingAgent(work_dir="./myproject")
result = agent.run(request_path="request.toml")
```

## 未來擴充方向

- Skills（`.uzcode/skills/`）／Preprocessor（`@file` / `@folder`）／History 快照（見 plan Phase 5–7）
- 多模型支援（透過 middleware）
- 更多基礎 tools
- 簡單 CLI REPL（可選）

## 為什麼 uzcode？

與 Aider、OpenHands 等工具相比，uzcode 更專注在**透明度**、**可控性**與**極簡**，適合希望完全掌握每一步、並能輕鬆 debug / replay 的開發者。

---

**專案狀態**：Phase 0–5 完成（Skills + \sh\uff1b見 plan_feature_skill）；下一步 Phase 6 Preprocessor
**核心原則**：Keep it simple, give control to the user.