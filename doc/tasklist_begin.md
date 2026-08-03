# uzcode 任務清單

依 [plan_begin.md](./plan_begin.md) 拆成可勾選任務。  
狀態：`[x]` 完成 · `[ ]` 未做

---

## Phase 0 — 專案骨架

**完成標準**：CLI 指定 workdir / req，正確載入並顯示設定與 messages。

- [x] `src/uzcode` 套件骨架（uv src layout）
- [x] `pyproject.toml`：套件 metadata、`uzcode` CLI entry point、依賴
- [x] `data/config.py`：載入 `.uzcode/cfg.toml`
- [x] `data/request.py`：載入 / 寫回 `req.toml`
- [x] `cli.py`：`--workdir` / `--req`，印出 config 與 messages
- [x] 範例 workdir：`examples/sample/.uzcode/cfg.toml` + `req.toml`
- [x] stub：`engine.py`、`tools/`、`extension/`
- [x] 本地驗證：`uv sync` 後執行  
  `uzcode --workdir examples/sample --req req.toml`

---

## Phase 1 — 薄引擎（無 tools）

**完成標準**：單輪對話可跑通，結果可透明寫回 TOML。

- [x] `engine.py`：LangGraph 流程（handle_request → before_llm → call_llm → after_llm → …）→ 呼叫 LLM → append assistant message
- [x] LiteLLM client（`base_url` / `api_key_env` / `model` 來自 cfg；OpenAI-compatible 走 `openai/` prefix）
- [x] Before / after LLM extension hook 點（此階段可 no-op）
- [x] 寫回 `req.toml`，或 CLI 指定輸出路徑（`--out`）
- [x] CLI 改為真正跑引擎（不再只印載入結果）
- [x] 手動驗收：一輪 user → assistant，TOML 可見完整 messages

---

## Phase 2 — Extension 系統

**完成標準**：不改核心即可從 `src/extensions/` 與 `.uzcode/exts/` 載入並執行 extension（至少繞 LLM）；before/after tool hooks 已定義。

- [x] `extension/base.py`：`HookRegistry`（`on(hook, fn, order=, name=)` / `run`）  
  （handle_request、before/after LLM、before/after tool、after_tools、on_result、on_error；非 Protocol）
- [x] `extension/loader.py`：雙路徑發現（internal `src/extensions` + external `.uzcode/exts`）；各 ext `register(registry, config)`
- [x] 引擎各階段串接 registry（LLM + on_result / on_error 活著；tool hooks 就緒待 Phase 3）
- [x] 範例 extension：`src/extensions/logging`；cfg 可 `enable` + 每 hook `extension.order.*` 覆寫
- [x] 手動驗收：掛上 extension 後 LLM 路徑會被攔截／記錄，無需改引擎

---

## Phase 3 — Tools（`file_cru` extension）

**完成標準**：LLM 可 tool call；經 extension 執行後寫回 tool result；每 tool 可在 cfg 開關／ask｜approve｜custom。

- [x] `tools/registry.py`：薄註冊表（register / openai_tools(config) / execute）
- [x] `HookRegistry.tool(...)`：ext 可註冊 tools
- [x] 內建 ext `file_cru`：`read_file` / `list_dir` / `grep`（read）、`write_file`（create）、`edit_file`（update）
- [x] 引擎：tools schema 傳給 LLM；解析 tool_calls；before/after tool → append tool messages（一輪，無 auto_loop）
- [x] 尊重 `cfg.toml`：每 tool `enable`、`permission`（ask｜approve｜custom）、`preview_diff`、`retry`、`on_failure`
- [x] `file_cru` `before_tool`：`preview_diff` stub（`ask` 由引擎 Y/n；`custom` 由其他 ext）
- [x] 手動驗收：讀檔 request 可跑通；`enable=false` 不上送 LLM；`permission=ask` 寫檔會被攔截

---

## Phase 4 — Loop 控制

**完成標準**：一次 CLI 可完成多輪 tool 迴圈；過程可從 `req.toml` 檢視。

無須revert，revert應由git處理.

停止條件（僅此）：最後一輪 assistant **無** `tool_calls`，或達 `max_iterations`；`auto_loop=false` 時維持一輪 LLM + 至多一輪 tools。無專用 stop/report tool。`stop_loop=True`（per-tool ctx / handler / `after_tools`）強制結束 **agent loop**（當輪 tool_calls 仍跑完）。

- [x] 依 `loop.auto_loop` / `loop.max_iterations` 控制迴圈
- [x] 有 tool calls 則繼續；無 tool calls 或達上限則停止
- [x] `after_tools` 節點 + hook；`stop_loop` 可強制 `end`（亦可於 `run_tools`呼叫各tool時 設）
- [x] 手動驗收：多 tool 任務一次跑完

---

## Phase 5 — Skills

**權威**：[plan_feature_skill.md](./plan_feature_skill.md)。完成標準見該文件 §9。

- [x] 核心：`SkillRegistry`／`registry.skill(...)`；合規發現 `.uzcode/skills/**/SKILL.md`（目錄名 = `name`）
- [x] 引擎：`handle_request`（一次）→ `before_llm` → …；`AgentState.skills_enabled`（引擎依 cfg 種子）／`system_messages`（exts 追加；`call_llm` 合併成單一 system）
- [x] 內建 ext `skills`：載入檔案 skills；`before_llm` 將目錄 append 到 `system_messages`（標記 `<!-- uzcode:skills-catalog -->`）；`read_skill`／`read_file_in_skill`（依 `skills_enabled`）
- [x] 內建 ext `shell`：`sh` tool（cwd = `work_dir`）
- [x] cfg：`[skills] enable`（省略 = 全部；`[]` = 空；白名單）；`extension.enable` 含 `"skills"`／`"shell"`
- [x] 其他 ext：可於 `handle_request` 突變 `state["skills_enabled"]`（例如 ban）；可 `registry.skill(...)` 程式註冊
- [x] 文件／範例：`examples/sample/.uzcode/skills/demo-skill/`；cfg 啟用 skills + shell
- [x] 手動驗收：目錄／read／路徑安全／sh／enable／loop／replay（見專項 §9）

**本階段不做**：description 自動匹配、skill 內嵌 tools、`src/skills/` 內建 pack、ext 寫檔到 skills 目錄、多根發現路徑。

---

## Phase 6 — Mention

**完成標準**：引擎解析 `@{cmd:text}` → `mentions`；`file_cru`／`skills` 設 `replacement` 或預載 tools；展開後的 `content` 送 LLM；寫回 TOML 只含原始 `content`（`raw` 僅 runtime）。

- [x] 引擎：`@{cmd:text}` 解析、`AgentState.mentions`、runtime `raw`/`content`、套用 `replacement`
- [x] `file_cru`：`file`／`folder`／`file!`／`folder!`
- [x] `skills`：`skill`／`skill!`
- [x] 對象不存在時 `Continue? (y/N)`；刪除獨立 `mention` ext

---

## Phase 7 — Web Fetch/Search

**完成標準**：`web` 提供 tools + mention handlers；`@{search!:...}`／`@{fetch!:...}` 預載；結果可 replay。

依賴：`ddgs`、`httpx` + `trafilatura`。詳見 [plan_begin.md](./plan_begin.md) Phase 7。

Mention：`@{search|fetch[:!]:text}`（引擎解析；`web` ext exact `cmd`）。Expand 僅 title/link 短索引；正文／snippet 只在 tool result（runtime 或 `!` precall）。

- [x] `pyproject.toml`：加入 `ddgs`、`httpx`、`trafilatura`
- [x] 內建 ext **`web`**：`handle_request` 處理 search/fetch mentions（tools 未註冊則 skip）
- [x] 註冊 `web_search`／`web_fetch` tools；尊重 cfg `enable`／`permission`
- [x] 範例：`@{search!:...}`／`@{fetch!:...}` 的 req／cfg
- [x] 手動驗收：tool 搜尋／抓頁；precall／短索引；tool 未開時不炸

**本階段不做**：JS 渲染、付費搜尋 API、快取／index、跳脫、下載二進位。

---

## Phase 8 — History

**完成標準**：cfg 開啟後，每次成功執行在 `.uzcode/history/` 留下可 replay 的 request 複本。

- [ ] 成功路徑快照（`on_result` ext 或 `engine.run` 後 helper）
- [ ] cfg 開關（預設關閉）
- [ ] 手動驗收：執行後 history 目錄有複本，可當 `--req` replay

---

## Pending（未排期）

以下不開階段任務，避免 scope creep：

- [ ] 公開 API 打磨：`CodingAgent(work_dir).run(request_path=...)`
- [ ] README：安裝、CLI、cfg / req 契約、自訂 extension 步驟
- [ ] 套件內建 `src/skills/` pack
- [ ] 依 skill description 智慧匹配

---

## 明確不做（v1）

以下不開任務，避免 scope creep：

- RAG / codebase indexing
- 核心內建多模型（留給 extension）
- 自動 git commit / push
- 完整 CLI REPL

---

## 整體驗收（全部 Phase 完成後勾選）

- [ ] 一次 CLI：載入 `req.toml` → LLM + tools 迴圈 → 結果透明寫回（或指定輸出）
- [ ] 手改 `req.toml` 後可直接 replay / fork
- [ ] extension 可攔截寫檔類 tool（confirm / preview），無需改引擎
- [ ] 工作目錄無未確認變更、無自動 git 副作用

---

**建議順序**：Phase 0 → 1 → 2（extension）→ 3（Tools）→ 4 → 5（Skills）→ 6（Mention）→ 7（Web）→ 8（History）；其餘見 Pending