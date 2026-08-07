# uzcode

一個極簡、stateless 的 AI coding agent，以純 Python 實作，強調**使用者完全控制權**與**可擴充性**。

## 設計理念

- **Stateless 第一**：每次執行都基於完整的 `request.toml`，無隱藏狀態。
- **使用者主導**：使用者可以任意修改歷史訊息、tool results、甚至 AI 之前的回應。
- **極簡核心**：骨幹保持最小，只負責必要流程。
- **高度可擴充**：所有進階行為（diff preview、logging、權限、多模型轉換等）都透過 extension 實現。
- **不汙染工作目錄**：無自動 git 操作、無未經確認的檔案變更。
- **Debug 友好**：易於 replay、fork 不同 request 版本。

## 專案結構

```bash
{work_dir}/
├── .uzcode/
│   ├── cfgs/                # 專案 cfg 疊層（可選）
│   ├── skills/              # Skill 檔
│   │   ├── my_skill/
│   │   │   └── SKILL.md
│   │   └── ...
│   ├── exts/                # 使用者自訂 extension
│   │   ├── file_cru         # 含 @{file|folder[:!]:...} mention
│   │   ├── skills           # 含 @{skill|skill!:...} mention
│   │   ├── web              # web_* tools + @{search|fetch[:!]:...}
│   │   ├── logging
│   │   │   └─ __init__.py
│   │   └── ...
│   └── sessions/            # 互動紀錄（session）
│       └── <name>/
│           ├── request.toml # 完整 transcript（使用者可手改）
│           ├── reqbak/      # 每次執行前的 request 備份
│           └── diffs/       # 每次執行新增的 messages
└── ... (你的專案檔案)
```

## 核心元件

### 1. Config (`--cfg` 疊層)
- LLM 設定（固定使用 OpenAI Chat Completions API）
- Loop 設定（`auto_loop`、`max_iterations` 等）
- 各 Tool 的權限與行為（`require_confirm`、`preview_diff`、`retry`、`on_failure`）
- Extension 載入順序與設定
- 可含 `[request]`：與其他層一樣經 overdict merge（常用于注入 prompt／messages）

### 2. Session (` .uzcode/sessions/<name>/request.toml`)
- 作為 **最後一層 cfg** 參與 merge（與一般 `--cfg` 檔相同）
- 存放 durable transcript；執行前 `reqbak/`，執行後覆寫並寫入 `diffs/`
- 使用者可手改後再跑，做 replay / fork

### 3. Extension 系統
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
- 未來多模型轉換（extension 轉換 request）
- 自訂權限檢查

### 4. Skills（檔案 + runtime 註冊）
- **檔案**：`.uzcode/skills/**/SKILL.md`（[Agent Skills](https://agentskills.io/specification) 合規；目錄名 = `name`）
- **程式**：extension 以 `registry.skill(...)` 在執行期加入（不寫檔）
- 內建 `skills` ext：`before_llm` 注入目錄（name + description）；全文／附屬檔經 `read_skill`／`read_file_in_skill`；腳本經 `sh`
- 詳見 [plan_feature_skill.md](./plan_feature_skill.md)

### 5. Agent Engine（核心極薄）
執行流程：
1. 載入 config + request
2. Before LLM extension
3. 呼叫 OpenAI Chat Completions（帶 tools）
4. 處理 tool calls（尊重 config 權限）
5. 如啟用 auto_loop 則繼續直到無 tool calls
6. After extension
7. 寫回 session：`reqbak/` + `diffs/` + 覆寫 `request.toml`

### 6. Tools（基礎集合）
- `read_file` / `write_file` / `edit_file` / `list_dir` / `grep`
- `read_skill` / `read_file_in_skill`（skills ext）
- `sh`（shell ext；cwd = work_dir）
- `web_search` / `web_fetch`（web ext；`ddgs` + `httpx`/`trafilatura`）

不內建 RAG、codebase indexing 等複雜功能。

### 7. 錯誤與安全性
- Tool 失敗處理依 config 中的 retry / on_failure 設定
- Preview / Confirm 機制交由 extension 實作
- 核心不執行危險操作，除非明確設定

## 使用方式

```bash
# 基本執行（cfg 疊層 + session 互動紀錄）
uzcode --workdir ./myproject --cfg @dev --session sfeature_aaa
```

也可作為 Python package 使用：

```python
from uzcode import CodingAgent

agent = CodingAgent(work_dir="./myproject")
# config, request, meta = agent.prepare(["@dev"], "sfeature_aaa")
# request, appended = agent.run(config, request)
# CLI persists session files (reqbak / diffs / request.toml)
```

## 未來擴充方向

- Skills／Mention／Web Search-Fetch（見 plan Phase 5–7）；History 由 sessions 取代
- 多模型支援（透過 extension）
- 更多基礎 tools
- 簡單 CLI REPL（可選）

## 為什麼 uzcode？

與 Aider、OpenHands 等工具相比，uzcode 更專注在**透明度**、**可控性**與**極簡**，適合希望完全掌握每一步、並能輕鬆 debug / replay 的開發者。

---

**專案狀態**：Phase 0–7 完成；Phase 8 History 由 `.uzcode/sessions/` 取代
**核心原則**：Keep it simple, give control to the user.