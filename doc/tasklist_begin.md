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
- [x] stub：`engine.py`、`tools/`、`middleware/`
- [x] 本地驗證：`uv sync` 後執行  
  `uzcode --workdir examples/sample --req req.toml`

---



## Phase 1 — 薄引擎（無 tools）

**完成標準**：單輪對話可跑通，結果可透明寫回 TOML。

- [x] `engine.py`：LangGraph 流程（before_llm → call_llm → after_llm）→ 呼叫 LLM → append assistant message
- [x] LiteLLM client（`base_url` / `api_key_env` / `model` 來自 cfg；OpenAI-compatible 走 `openai/` prefix）
- [x] Before / after LLM middleware hook 點（此階段可 no-op）
- [x] 寫回 `req.toml`，或 CLI 指定輸出路徑（`--out`）
- [x] CLI 改為真正跑引擎（不再只印載入結果）
- [x] 手動驗收：一輪 user → assistant，TOML 可見完整 messages

---



## Phase 2 — Middleware 系統

**完成標準**：不改核心即可從 `src/middlewares/` 與 `.uzcode/mids/` 載入並執行 middleware（至少繞 LLM）；before/after tool hooks 已定義。

- [x] `middleware/base.py`：`HookRegistry`（`on(hook, fn, order=, name=)` / `run`）  
  （before/after LLM、before/after tool、on_result、on_error；非 Protocol）
- [x] `middleware/loader.py`：雙路徑發現（internal `src/middlewares` + external `.uzcode/mids`）；各 mid `register(registry, config)`
- [x] 引擎各階段串接 registry（LLM + on_result / on_error 活著；tool hooks 就緒待 Phase 3）
- [x] 範例 middleware：`src/middlewares/logging`；cfg 可 `enable` + 每 hook `middleware.order.*` 覆寫
- [x] 手動驗收：掛上 middleware 後 LLM 路徑會被攔截／記錄，無需改引擎

---



## Phase 3 — Tools（`file_cru` middleware）

**完成標準**：LLM 可 tool call；經 middleware 執行後寫回 tool result；每 tool 可在 cfg 開關／ask｜approve｜custom。

- [x] `tools/registry.py`：薄註冊表（register / openai_tools(config) / execute）
- [x] `HookRegistry.tool(...)`：mid 可註冊 tools
- [x] 內建 mid `file_cru`：`read_file` / `list_dir` / `grep`（read）、`write_file`（create）、`edit_file`（update）
- [x] 引擎：tools schema 傳給 LLM；解析 tool_calls；before/after tool → append tool messages（一輪，無 auto_loop）
- [x] 尊重 `cfg.toml`：每 tool `enable`、`permission`（ask｜approve｜custom）、`preview_diff`、`retry`、`on_failure`
- [x] `file_cru` `before_tool`：`preview_diff` stub（`ask` 由引擎 Y/n；`custom` 由其他 mid）
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



## Phase 5 — 打磨與擴充入口

**完成標準**：文件與範例足以讓使用者自訂 middleware 並掛上。

- [ ] 範例 `logging` middleware
- [ ] 範例 `preprocesser`（`@file` / `@folder` 展開 stub）
- [ ] （可選）執行後快照到 `.uzcode/history/`
- [ ] 公開 API 打磨：`CodingAgent(work_dir).run(request_path=...)`
- [ ] README：安裝、CLI、cfg / req 契約、自訂 middleware 步驟
- [ ] 更新本清單與 plan 狀態為 v1 可交付

---



## 明確不做（v1）

以下不開任務，避免 scope creep：

- RAG / codebase indexing
- 核心內建多模型（留給 middleware）
- 自動 git commit / push
- 完整 CLI REPL

---



## 整體驗收（全部 Phase 完成後勾選）

- [ ] 一次 CLI：載入 `req.toml` → LLM + tools 迴圈 → 結果透明寫回（或指定輸出）
- [ ] 手改 `req.toml` 後可直接 replay / fork
- [ ] Middleware 可攔截寫檔類 tool（confirm / preview），無需改引擎
- [ ] 工作目錄無未確認變更、無自動 git 副作用

---

**建議順序**：Phase 0 → 1 → 2（Middleware）→ 3（Tools）→ 4 → 5（見 plan §8）