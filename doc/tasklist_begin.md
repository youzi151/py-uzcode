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

- [ ] `engine.py`：載入 config + request → 呼叫 LLM → append assistant message
- [ ] OpenAI Chat Completions client（`base_url` / `api_key_env` / `model` 來自 cfg）
- [ ] Before / after LLM middleware hook 點（此階段可 no-op）
- [ ] 寫回 `req.toml`，或 CLI 指定輸出路徑（例如 `--out`）
- [ ] CLI 改為真正跑引擎（不再只印載入結果）
- [ ] 手動驗收：一輪 user → assistant，TOML 可見完整 messages

---

## Phase 2 — 內建 Tools

**完成標準**：LLM 可 tool call，引擎執行後寫回 tool result，並可再進下一輪。

- [ ] `tools/registry.py`：註冊與查詢 tools
- [ ] `read_file`
- [ ] `write_file`
- [ ] `edit_file`
- [ ] `list_dir`
- [ ] `grep`
- [ ] 引擎：把 tools schema 傳給 LLM；解析 tool_calls；執行並 append tool messages
- [ ] 尊重 `cfg.toml`：`require_confirm`、`preview_diff`、`retry`、`on_failure`  
  （confirm / preview UX 留給 Phase 3 middleware）
- [ ] 手動驗收：要求讀檔的 request 可跑通並寫回 tool result

---

## Phase 3 — Middleware 系統

**完成標準**：不改核心即可用 middleware 攔截 `write_file` / `edit_file` 做確認。

- [ ] `middleware/base.py`：完整 hook 介面  
  （before/after LLM、before/after tool、on_result、on_error）
- [ ] `middleware/loader.py`：從 `.uzcode/mids/` 依 `middleware.order` 動態載入
- [ ] 引擎各階段串接 middleware chain
- [ ] 範例 middleware（可先放 examples）：攔截寫檔 + confirm / preview stub
- [ ] 手動驗收：掛上 middleware 後寫檔會被攔截，無需改引擎

---

## Phase 4 — Loop 控制

**完成標準**：一次 CLI 可完成多輪 tool 迴圈；過程可從 `req.toml` 重播。

- [ ] 依 `loop.auto_loop` / `loop.max_iterations` 控制迴圈
- [ ] 有 tool calls 則繼續；無 tool calls 或達上限則停止
- [ ] 每輪 messages 保持可寫回 / 可 replay
- [ ] 手動驗收：多 tool 任務一次跑完；改 `req.toml` 可 fork / replay

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

**建議順序**：Phase 0 → 1 → 2 → 3 → 4 → 5（見 plan §8）
