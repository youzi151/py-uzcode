# Skills 功能實作計畫

本文件依 [plan_begin.md](./plan_begin.md) Phase 5 與 [tasklist_begin.md](./tasklist_begin.md) 拆出 **Skills** 的專項開發計畫。  
前置：Phase 0–4 已完成（薄引擎、extension、tools、`auto_loop`）。

**核心原則**：Keep it simple, give control to the user.

**分層原則（重要）**：

| 層級 | 內容 | 權威來源 |
|------|------|----------|
| **Skill 套件格式** | 目錄結構、`SKILL.md` frontmatter／body、相對路徑、漸進載入語意 | **[Agent Skills 開放標準](https://agentskills.io/specification)**（Cursor／Claude／Codex 等同慣例） |
| **uzcode 執行層** | 發現路徑、`[skills].enable`、`skills_enabled`／`system_messages`、`read_skill`／`read_file_in_skill`、`registry.skill(...)` | 本專項（**非**標準一部分；只是用標準已有資訊額外提供便利） |

Skills 是「可發現的任務手冊」，不是可執行外掛：標準不定義專屬 LLM API 欄位；uzcode 以 **prompt 目錄 + 讀取 tools** 實現漸進載入，不做獨立匹配引擎。

---

## 1. 目標

讓 LLM 在第一次呼叫前能看到已啟用 skill 的**輕量目錄**（`name`／`description`），並能按需載入全文與附屬資源；**磁碟上的 skill 套件可與 Cursor／Claude 等互通**；過程對 `req.toml` 透明可 replay。

| 目標 | 含義 |
|------|------|
| 格式合規 | 檔案 skill **必須**符合 Agent Skills 規格（見 §4）；不自創不相容的套件格式 |
| 雙來源合一 | 檔案 skills + extension 程式註冊 → 同一 runtime 表 |
| 使用者可控 | `[skills].enable` 由**引擎**注入 `state.skills_enabled`；exts 可在 `handle_request` 再改變該列表；省略 = 全部；空列表 = 無目錄／`read_*` 皆拒 |
| 漸進載入 | 對齊標準三級披露：`system_messages` 只放 metadata 目錄；全文／附屬資源按需載入（省 token） |
| Skill 不可執行 | 標準與本計畫一致：Skill 本身無 runtime；跑腳本 = 取得路徑後轉呼叫既有 `sh` |
| 便利 tools 非規格 | `read_skill`／`read_file_in_skill` 為 uzcode 實作細節，**不**要求 skill 作者為這兩個 tool 寫特殊標記 |
| 不落盤程式 skill | `registry.skill(...)` 僅執行期存在，不寫入 skills 目錄 |
| Replay 友好 | 目錄進 `messagelib.__skill`；request 以 `ref = "__skill"` 定位；不展開寫回；tool results 走既有 messages |

---

## 2. 非目標（本階段明確不做）

- 獨立的「智慧匹配引擎」（embedding／規則自動選 skill）；**允許** LLM 依 system 中的 `description` 自行決定是否載入
- Skill 變成可執行外掛／RPC（無 `invoke_skill` 執行入口；標準亦無此要求）
- Skill 內嵌／註冊任意 tool pack（skill ≠ MCP／function 打包）；標準的 `allowed-tools` 僅作可選 metadata，v1 可不強制執行
- 把 `read_skill`／`read_file_in_skill` 寫進對外「Skill 格式規格」（它們是 runtime 便利，不是套件欄位）
- 套件內建 `src/skills/` pack（列 Pending）
- extension 把程式 skill 寫檔到 skills 目錄
- 為 skills 新增獨立匹配／執行節點（僅用既有 `handle_request`／`before_llm` + tool 通道）
- 對外回傳本機**絕對路徑**給 LLM（見 §5.3）
- v1 必做掃描 Claude／Cursor 全路徑（見 §4.2；可列相容加分／Pending）

---

## 3. 運作模型（如何傳入 LLM）

以 OpenAI Chat Completions 為協議類比（實際仍走 uzcode 既有 messages）。  
**標準不規定**必須用何種 tool 名稱；下列為 uzcode 對「漸進載入」的實作映射。

| 內容 | 落點 | 時機 | 對應標準層級 |
|------|------|------|----------------|
| Skill 目錄（`name` + `description` + 使用約定） | `messagelib.__skill` → resolve 成 `role=system` | 第一次 `before_llm` 寫入 | Level 1 Metadata |
| 「相關時先載入 skill」規則 | 同上 | 與目錄一併 append | （runtime 約定） |
| `SKILL.md` 正文 | `role=tool`（`read_skill` 的 result） | LLM 決定載入後 | Level 2 Instructions |
| 附屬檔（`references/`／`scripts/` 原文等） | `role=tool`（`read_file_in_skill` 的 result） | 按需 | Level 3 Resources |
| 執行腳本 | 既有 `sh`（或同等） | 用 tool 回傳的 **相對 workdir 路徑** 組命令 | Level 3（執行，非讀） |

**沒有** Chat API 的 `skills:` 欄位；也沒有「執行整個 skill」的專屬 tool。  
介入 = **prompt 索引 +（uzcode）讀取 tools +（可選）通用 Shell**。

```text
handle_request（一次）：
  引擎 peel req system → system_messages
  引擎依 cfg 注入 skills_enabled
  exts 可改變 skills_enabled／registry.skill(...)
    ↓
before_llm：skills ext 將目錄 append 到 system_messages（僅 name + description）
    ↓
call_llm：合併 system_messages → 單一 system，再送 API
    ↓
LLM 依 description 判斷是否需要某 skill
    ↓
read_skill(name) → body 等（僅 skills_enabled 內）
    ↓
read_file_in_skill(name, path) → content + workdir 相對路徑
    ↓
sh：對 workdir_relative_path 執行（Skill 本身不執行）
```

> **讀取 tools 的定位**：`read_skill`／`read_file_in_skill` 只是把標準套件裡**本來就有的** `SKILL.md` 與相對路徑檔案，用受控方式交給 LLM；不新增套件格式、不改變 `SKILL.md` 寫法。作者仍按 agentskills.io 寫 skill，不必知道這兩個 tool 名稱。

---

## 4. 架構

### 4.1 分層職責

```text
┌─────────────────────────────────────────────────────────┐
│  核心 engine（系統級）                                     │
│  · handle_request：peel system；注入 skills_enabled       │
│  · SkillRegistry + registry.skill(...)                    │
│  · call_llm：合併 system_messages → 單一 system           │
│  · discover／parse 合規 SKILL.md（可由 ext 呼叫）         │
└──────────────────────────┬──────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────┐
│  內建 ext `skills`                                        │
│  · register()：discover 檔案 skills；註冊 read_* tools    │
│  · before_llm：依 skills_enabled 組目錄 → append          │
│    system_messages（標記 <!-- uzcode:skills-catalog -->） │
└──────────────────────────┬──────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────┐
│  其他 ext                                                 │
│  · register() 或 handle_request：registry.skill(...)      │
│  · handle_request：改變 state["skills_enabled"]（ban 等） │
└─────────────────────────────────────────────────────────┘
```

### 4.2 目錄與發現

#### 4.2.1 標準套件佈局（權威）

每個 skill **必須**是一個目錄，內含 `SKILL.md`（[規格](https://agentskills.io/specification)）：

```text
skill-name/                 # 目錄名必須等於 frontmatter.name
├── SKILL.md                # 必要：YAML frontmatter + Markdown 指示
├── scripts/                # 可選：可執行腳本（由 Agent 經 Shell 跑）
├── references/             # 可選：按需文件
├── assets/                 # 可選：模板／靜態資源
└── ...                     # 其他附屬檔亦可（路徑仍相對 skill 根）
```

範例（使用者工作目錄，uzcode 預設發現根）：

```text
{work_dir}/.uzcode/skills/
└── deploy-app/
    ├── SKILL.md
    ├── scripts/
    │   ├── deploy.sh
    │   └── validate.py
    ├── references/
    │   └── REFERENCE.md
    └── assets/
        └── config-template.json
```

#### 4.2.2 uzcode 發現根（執行層）

**v1 預設**：

| 範圍 | 路徑 |
|------|------|
| 專案 | `{work_dir}/.uzcode/skills/` |

**相容加分／Pending**（與 Cursor 掃路徑對齊，便於共用同一份 skill 套件）：

| 範圍 | 路徑 |
|------|------|
| 專案 | `.agents/skills/`、`.cursor/skills/`、`.claude/skills/`、`.codex/skills/` |
| 使用者 | `~/.agents/skills/`、`~/.cursor/skills/`、`~/.claude/skills/`、`~/.codex/skills/` |

規則：只認 **`*/SKILL.md`**（可遞迴掃描分類子目錄；skill 身分 = 含 `SKILL.md` 的那層目錄名）。  
**不**把「僅有扁平 `foo.md`、無 `SKILL.md`」當標準 skill（舊草案扁平 `.md` 改為 **不做／非合規**，避免產出無法在 Cursor／Claude 使用的套件）。

#### 4.2.3 套件（實作）

```text
src/uzcode/
├── skills/                  # 薄核心：discover / parse / SkillRegistry
│   ├── __init__.py
│   ├── registry.py
│   └── discover.py
├── extension/base.py       # HookRegistry.skill(...)；HOOKS 含 handle_request
├── engine.py                # handle_request 可注入；call_llm 合併 system_messages
└── ...

src/extensions/skills/
└── __init__.py              # discover 檔案 + read_* + before_llm → system_messages
src/extensions/shell/
└── __init__.py              # sh tool
```

> 若希望核心更薄，可把 `discover` 放進 ext、核心只留 `SkillRegistry`；本計畫建議核心負責合規解析，ext 負責 enable 過濾、目錄注入與兩個讀取 tools。

### 4.3 `SKILL.md` 格式（Agent Skills 標準）

權威：https://agentskills.io/specification  

必須為 **YAML frontmatter + Markdown body**。

#### Frontmatter

| 欄位 | 必須？ | 約束 |
|------|--------|------|
| `name` | 是 | ≤64；僅 `a-z`／`0-9`／`-`；不首尾 `-`；無連續 `--`；**必須等於父目錄名** |
| `description` | 是 | ≤1024；非空；寫清 **做什麼 + 何時用**（含觸發關鍵詞）；第三人稱 |
| `license` | 否 | 授權名稱或捆绑授權檔參考 |
| `compatibility` | 否 | ≤500；環境／產品需求 |
| `metadata` | 否 | 任意 string→string map（建議鍵名夠獨特） |
| `allowed-tools` | 否 | 實驗性；空白分隔的預批工具字串；**v1 可解析並忽略執行語意** |

**未知 frontmatter 鍵：必須忽略**（保證可攜；不因 Cursor 擴充欄位而解析失敗）。

Cursor 常見擴充（可選支援，**非**開放標準核心）：

| 欄位 | 說明 |
|------|------|
| `disable-model-invocation` | `true` 時僅顯式啟用（uzcode v1：可只進 registry、**不**注入自動目錄，或目錄標註「僅手動」；實作擇一並寫進 cfg／文件） |
| `paths`（舊名 `globs`） | 依檔案 glob 才露出；v1 可 Pending |

最小合規例：

```markdown
---
name: deploy-app
description: Deploy the application to staging or production. Use when deploying code or when the user mentions deployment, releases, or environments.
---

# Deploy App

## Instructions

1. Run validation: `python scripts/validate.py`
2. Deploy: `scripts/deploy.sh <environment>`

## Additional resources

- See [references/REFERENCE.md](references/REFERENCE.md)
```

| 項目 | 規則 |
|------|------|
| `name` | **必須**與目錄名一致；不合規 → 跳過該 skill + stderr 警告 |
| `description` | **必須**；缺則跳過（標準必填，不作「建議」） |
| body | frontmatter 之後全文；**不**在第一次 `before_llm` 整份注入 |
| 正文寫法 | 作者只寫標準相對路徑（如 `scripts/validate.py`）；**不必**寫 `read_skill`／workdir 路徑 |

### 4.4 附屬檔路徑約定（標準）

- 引用一律 **相對 skill 根**（含 `SKILL.md` 的目錄），例如 `references/REFERENCE.md`、`scripts/validate.py`。
- 引用保持 **一層**：由 `SKILL.md` 直連附屬檔；避免深鏈。
- 路徑使用正斜杠（`scripts/helper.py`）。
- 不在正文寫本機絕對路徑。

uzcode 的 `read_file_in_skill(name, path)` 中，`path` 即上述 skill 根相對路徑；回傳時另附 **workdir 相對路徑** 供 `sh` 使用（執行層便利，非標準欄位）。

### 4.5 漸進披露（標準語意 → uzcode 映射）

| 標準層級 | 內容 | uzcode 做法 |
|----------|------|-------------|
| 1. Metadata | 全部 skill 的 `name` + `description` | `before_llm` → `system_messages`；引擎合併 |
| 2. Instructions | 啟用後的完整 `SKILL.md` body | `read_skill` → tool result（或未來等價載入） |
| 3. Resources | `scripts/`／`references/`／`assets/` 等 | `read_file_in_skill`；執行用 `sh` |

建議：主 `SKILL.md` 保持精簡（規格建議 &lt; 500 行／instructions &lt; ~5000 tokens）；細節放 `references/`。

---

## 5. 資料契約

### 5.1 Runtime skill 表

```python
@dataclass(frozen=True)
class Skill:
    name: str
    description: str
    body: str
    # 檔案 skill：skill 目錄相對 work_dir；程式 skill：None
    root_relpath: str | None
    source: str  # "file:<path>" | "code:<ext_name>"（debug 用，可不注入 LLM）
    # 可選：保留原始 frontmatter 中標準／擴充欄位（license、metadata、…）
    extra: dict[str, object] | None = None
```

合併規則：

1. 先載入檔案 skills（僅合規 `SKILL.md`；skills ext `register()`）
2. 再套用 `registry.skill(...)`（同名：**後註冊覆寫**；可在 `register()` 或 `handle_request`）
3. **引擎**於 `handle_request` 依 `[skills].enable` 注入 `state["skills_enabled"]`
4. 其他 ext 可於 `handle_request` **改變** `skills_enabled`（例如移除 = ban）
5. 目錄與 `read_*` 可見範圍皆以最終 `skills_enabled` 為準

### 5.1b `AgentState`（系統級欄位）

```python
skills_enabled: list[str]      # 引擎注入；exts 在 handle_request 可改
system_messages: list[str]     # req system peel 進來；exts 只 append
# messages 不再承載多源 system 拼接；call_llm 合併 system_messages
```

### 5.2 `cfg.toml`

```toml
[extension]
enable = ["logging", "file_cru", "skills", "shell"]

[skills]
# 留空 = 引擎注入為全部已註冊 name
# enable = []              # 空列表 → skills_enabled = []
# enable = ["deploy-app"]  # 白名單 ∩ 已註冊

[extension.order.before_llm]
logging = 10
skills = 20
# Phase 6 mention 建議在 handle_request（skills 已注入 skills_enabled）
```

| `skills.enable` | 行為（引擎注入） |
|-----------------|------------------|
| 鍵省略／未設定 | `skills_enabled` = 全部已註冊 name |
| `[]` | `skills_enabled` = `[]`（目錄為空；`read_*` 皆拒） |
| `["a", "b"]` | 僅列出的已註冊 name（未知 name 可警告 stderr，不中斷） |

`extension.enable` 不含 `"skills"` 時：不載入 ext → 無目錄、無 skill 讀取 tools（`skills_enabled` 仍可能被注入為空／僅程式註冊，視其他 ext 而定）。

### 5.3 便利 tools（uzcode 執行層；非 Agent Skills 規格）

契約：Shell 的 cwd **固定為 `work_dir`（workspace 根）**。對外路徑一律相對此 workdir，**不**把絕對路徑回給 LLM。

這兩個 tool **不**改變 skill 套件格式；只讀標準目錄內既有檔案，並把路徑轉成對 `sh` 友善的 workdir 相對路徑。

#### `read_skill`

```text
read_skill(name: string) -> {
  name: string,
  description: string,
  body: string,                 # SKILL.md Markdown body（或程式註冊的 body）
  root_relpath: string | null   # 相對 work_dir；程式 skill 可為 null
}
```

- 僅允許 `state["skills_enabled"]` 內的 name。
- 程式註冊、無磁碟根目錄者：仍回 `body`；`root_relpath = null`。

#### `read_file_in_skill`

```text
read_file_in_skill(name: string, path: string) -> {
  skill: string,
  skill_relative_path: string,      # 相對 skill 根（與 SKILL.md 寫法一致）
  workdir_relative_path: string,    # 相對 Shell workdir，供後續 sh 使用
  content: string                   # 文字內容
}
```

規則：

| 規則 | 說明 |
|------|------|
| `path` | 必須相對 skill 根；禁止 `..`、絕對路徑；resolve 後必須仍在 skill 目錄內 |
| 回傳 | **內容 + 路徑**；路徑對外用 `workdir_relative_path`，不用絕對路徑 |
| 大檔／二進位 | 可只回路徑 + `size`／提示改用 sh；避免巨型 content 塞進上下文 |
| 無 root | 純程式 skill → 明確 error |
| 與通用讀檔 | 工作區一般檔案仍用既有 file tools；這兩個 tool **只**服務 skill 目錄沙箱 |

#### 執行腳本

```text
read_file_in_skill(...) 或已知 workdir_relative_path
    → sh: python .uzcode/skills/deploy-app/scripts/validate.py ...
```

- Skill **理論上無法執行**；`scripts/*` 只是普通檔案（標準亦如此）。
- 可選後續（非本階段必須）：薄包裝 `run_skill_script(name, script, args)`，內部仍是「校驗路徑 ∈ skill 根 → subprocess」。本階段以既有 `sh` 為準。

### 5.4 目錄注入與 `messagelib.__skill`

**時機**：本 run 第一次 `before_llm`（`auto_loop` 後續輪次不重注目錄）。

**流程：**

1. `handle_request`：注入 `skills_enabled`；保留 raw `messages`（含 `ref`）與 `messagelib`。
2. skills ext `before_llm`：若 `messagelib.__skill` 尚無 `<!-- uzcode:skills-catalog -->`，依 `skills_enabled` 組目錄並寫入 `messagelib.__skill`。
3. **不**把各 skill 的 `body` 寫進目錄（對齊標準 Level 1）。
4. Request 模板以 `ref = "__skill"` 決定目錄在 messages 中的位置；**不**與 `__system` 混拼字串。
5. `call_llm`：對每則 message resolve（lib 先、自身欄位覆寫）後送 API。
6. 寫回 session `session.toml`：保留原稿（含 `ref`）；只 append 本輪 assistant／tool；不寫入 runtime 展開或 catalog 內容。

| 方案 | 做法 | 取捨 |
|------|------|------|
| A | 寫入前檢查 `__skill` 是否已含標記 | 同一次 run 內防重複 |
| B（採用） | catalog 只進 runtime `messagelib`、不回寫 session | 檔案保持 `ref`；每輪由 ext 再填 `__skill` |

### 5.5 HookRegistry API

```python
# extension/base.py（示意）
def skill(
    self,
    name: str,
    *,
    description: str = "",
    body: str,
    root_relpath: str | None = None,
) -> None:
    self.skills.register(
        name,
        description=description,
        body=body,
        root_relpath=root_relpath,
        source=...,
    )
```

其他 ext 範例（**runtime 擴充**，不產生標準套件檔）：

```python
def register(registry, config) -> None:
    def handle_request(ctx):
        # 可 registry.skill(...)；可改變 skills_enabled
        enabled = ctx["state"]["skills_enabled"]
        ctx["state"]["skills_enabled"] = [n for n in enabled if n != "deploy-app"]
        return ctx

    registry.skill(
        "team-conventions",
        description="Apply team Python conventions when editing this repo. Use when writing or reviewing Python.",
        body="Prefer pathlib; never commit secrets.",
    )
    registry.on("handle_request", handle_request, order=20, name="my_ext")
```

程式註冊的 `name` 建議仍遵守標準命名規則，以便與檔案 skill 同一套過濾／工具契約。  
若在 `handle_request` 才 `registry.skill(...)`，需自行把 name 加進 `skills_enabled`（引擎注入早於 ext hooks）。

---

## 6. 實作步驟

對應 [tasklist_begin.md](./tasklist_begin.md) Phase 5 勾選項（本專項文件為準；若與 tasklist 舊述衝突，以本文件為準並回頭改 tasklist／plan_begin）。

### Step 1 — 核心 SkillRegistry + 合規發現

- [x] `Skill` 資料結構（含 `root_relpath`、可選 `extra`）+ `SkillRegistry`（`register`／`get`／`all`／同名覆寫）
- [x] `discover(skills_dir) -> list[Skill]`：僅 `*/SKILL.md`（可遞迴）；校驗 `name` 規則與目錄名一致、`description` 非空
- [x] 解析 YAML frontmatter（最小依賴）；**忽略未知鍵**
- [x] 不合規 skill：跳過 + stderr 警告
- [x] `HookRegistry` 持有 `skills: SkillRegistry`，並暴露 `registry.skill(...)`

### Step 2 — 引擎 `handle_request`／`skills_enabled`／`system_messages` + ext `skills`

- [x] `handle_request` 節點；注入 `skills_enabled`；保留 `messagelib` + raw messages
- [x] `call_llm` resolve `ref`（僅 API）；寫回 session 保留原稿 + append assistant／tool
- [x] ext `skills`：discover + `read_*`；`before_llm` 寫入 `messagelib.__skill`
- [x] ext `shell`：`sh` tool

### Step 3 — Config 契約 + 範例

- [x] `[skills].enable`（引擎讀 `config.raw`）
- [x] 範例 cfg + `demo-skill` 合規套件

### Step 4 — 手動驗收

- [x] 目錄／read／路徑安全／sh／enable／loop／replay／`skills_enabled` 改變

---

## 7. 與引擎／其他 Phase 的銜接

| 元件 | 關係 |
|------|------|
| `engine.handle_request` | 一次：peel system、注入 `skills_enabled`、跑 ext hooks |
| `engine.before_llm` | skills ext 寫入 `messagelib.__skill` |
| `engine.call_llm` | resolve `ref` → API；不寫回展開結果 |
| Tools 通道 | `read_skill`／`read_file_in_skill`／`sh` |
| Phase 6 mentions | 引擎解析 `@{...}`；`file_cru`／`skills`／`web` 處理對應 `cmd` |
| Phase 8 History | 快照：保留原稿 request + append 的 tool／assistant messages |

---

## 8. 錯誤與邊界

| 情況 | 行為 |
|------|------|
| skills 根目錄不存在 | 視為無檔案 skill |
| 缺 `SKILL.md`／frontmatter 不合規 | 跳過該目錄 + stderr 警告；不中斷整次 run |
| `name` ≠ 父目錄名 | 跳過 + 警告 |
| 缺或空 `description` | 跳過 + 警告 |
| 未知 frontmatter 鍵 | 忽略 |
| `enable` 含未知 name | stderr 警告；其餘照常 |
| `read_skill` 未知／未啟用 name | tool error（不中斷整次 run） |
| `read_file_in_skill` 路徑穿越或越界 | tool error |
| `read_file_in_skill` 無 root | tool error |
| body 為空 | 若 frontmatter 合規仍可進目錄；`read_skill` 回空 body |
| 同名檔案 + 程式 | 程式後註冊者勝出 |

不在 v1 做：skill 級 token 預算、加密 skill 檔、`run_skill_script`、強制執行 `allowed-tools`、完整多根目錄掃描（Pending）、`paths`／`disable-model-invocation` 完整語意（可後補）。

---

## 9. 驗收標準（功能級）

1. 合規 skill + 啟用 `skills` ext 後，第一次 LLM 前合併 system 含 **目錄**（name + description），**不含**各 skill 全文。
2. 磁碟套件符合 [Agent Skills 規格](https://agentskills.io/specification)。
3. `read_skill`／`read_file_in_skill` 行為符合 §5.3；路徑無絕對路徑。
4. 腳本經 `sh` + workdir 相對路徑；Skill 本身不可執行。
5. `registry.skill(...)` 無需落盤；無 root 則 `read_file_in_skill` 失敗。
6. `[skills].enable` cfg注入至engine；ext 可改變 `skills_enabled`。
7. `auto_loop` 多輪不重複 append 目錄（同 run 內標記檢查）。
8. 關閉 `"skills"` ext 後無目錄／無 `read_*`（與未掛 skills 行為一致）。
9. `messagelib` + `ref`：`__system`／`__skill` 等可自由排序；skills 只改 `__skill`；catalog 不寫回 session。

---

## 10. 建議實作順序（摘要）

```text
Step 1  SkillRegistry + discover
    → Step 2  handle_request + skills_enabled + system_messages + ext skills/shell
        → Step 3  cfg + 範例
            → Step 4  驗收
```

之後可接 Phase 7 Web／Phase 8 History；Pending：多根發現路徑、`src/skills/` pack、可選 `run_skill_script`、`paths`／`disable-model-invocation`、`allowed-tools` 執行語意。

---

## 11. 與舊版計畫差異（摘要）

| 舊草案 | 本版 |
|--------|------|
| 「最小 Cursor 風格」自述格式 | **明確遵循 [agentskills.io](https://agentskills.io/specification)** |
| 允許扁平 `other.md` | **取消**（非標準）；僅 `*/SKILL.md` |
| `name` 可缺省推導 | **`name`＋`description` 必填**；`name` 必須等於目錄名 |
| 附屬檔隨意放根目錄為主 | 標準目錄：`scripts/`／`references/`／`assets/` |
| `read_*` 像規格核心 | **標註為 uzcode 便利層**；套件作者不需為其改寫格式 |
| 第一次注入全文 body | 只注入目錄；全文靠載入（`read_skill`） |
| ext 改 messages 拼 system | **`system_messages` 列表 + 引擎合併** |
| ext 讀 cfg 過濾 enable | ** 注入engine `skills_enabled`；ext 可改變** |
| — | 未知 frontmatter 忽略；可選擴充欄位不阻塞 |

---

## 12. 參考

- **Agent Skills 規格（套件格式權威）**：https://agentskills.io/specification
- Cursor Skills 文件：https://cursor.com/docs/skills
- 總計畫：[plan_begin.md](./plan_begin.md) § Phase 5
- 勾選任務：[tasklist_begin.md](./tasklist_begin.md) § Phase 5
- 理念：[idea_begin.md](./idea_begin.md) § Skills
- 現況錨點：`handle_request`、`skills_enabled`、`system_messages`、`registry.skill`、`read_*`、`sh`

---

**狀態**：已實作並與引擎契約同步（`handle_request`／`skills_enabled`／`system_messages` + 漸進載入）  
**範圍**：Phase 5 Skills（本專項文件為準）
