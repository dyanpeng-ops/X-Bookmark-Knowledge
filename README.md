# X Bookmark Knowledge Pipeline

把 X.com 的 Bookmarks 采集到本地，加工为**每条 Tweet 一个独立 Markdown**，连同图片/视频、X Article 与推文中引用的外部链接正文一起归档，最终接入既有的 Knowledge-Agent 体系。

> **本项目默认不修改 X.com 中的 Bookmark，只执行读取和本地归档。**

---

## 1. 项目目标

```text
X.com Bookmarks
   ↓  采集（复用 fieldtheory CLI）
Raw Data（原始 JSON / 媒体清单 / 媒体文件）
   ↓  加工
Markdown（1 Tweet = 1 文件，含 Tweet / Thread / Media / Article / External Links / Metadata）
   ↓  写入
个人知识库（knowledge/X-Bookmarks/YYYY/MM/）
   ↓  交接
Knowledge-Agent（摘要 / 标签 / 主题 / 实体 / 关联）
```

目标不是做一个"X 下载器"，而是建立一条 **X.com → Personal Knowledge Base** 的自动知识采集管道。

---

## 2. 功能

| 功能 | 说明 | 实现阶段 |
| --- | --- | --- |
| 增量同步 | 默认只处理新书签，已处理的书签跳过 | Phase 6 |
| 幂等执行 | 同一任务跑两次不产生重复数据、不重复复制媒体 | Phase 6（媒体本地化：Phase 8） |
| 完整 Tweet 归档 | 正文、作者、发布时间、Tweet URL、会话 ID | Phase 7 |
| 媒体本地化 | 上游 `media/` 缓存复制到知识库自身的 `assets/{tweet_id}/`，稳定命名 + 哈希去重；Markdown 只引用本地相对路径 | ✅ Phase 8 |
| X Article | 识别并保存 Article 正文 | Phase 7 / 9 |
| 外链正文抽取 | 重定向解析 + 正文提取 + Markdown 清洗；失败也保留原始 URL | 🟡 Phase 9（实现完毕、未验收） |
| 媒体与内容完整性测试 | Test A–L（普通/长推/Thread/引用/Article/单图/多图/视频/外链/GitHub/PDF/多 URL） | Phase 10 |
| AI 增强（可选） | 摘要、标签、主题、关键点、实体；**只追加，不改原始字段** | Phase 11 |
| 状态机 | `NEW → COLLECTED → PROCESSED → ENRICHED → COMPLETED`（失败 `FAILED`） | Phase 12 |
| Windows 定时任务 | Task Scheduler 每日 08:00 无人值守运行 | Phase 13 |
| Doctor 自检 | Python / 配置 / 认证 / 数据库 / 知识库目录 / 网络 / Collector / AI / 调度 | Phase 6+ |

---

## 3. 架构

```text
┌─────────────────────────────────────────────────────────────┐
│ Collector（复用上游，只读）                                   │
│   fieldtheory CLI  →  data/upstream/（FT_DATA_DIR，ADR-011）  │
│     bookmarks.jsonl · media-manifest.json · media/**        │
└──────────────────────────┬──────────────────────────────────┘
                           │ src/collector/（Adapter）
                           ▼
┌─────────────────────────────────────────────────────────────┐
│ 本项目（Python）                                             │
│   ingest    → SQLite 状态机 / 增量 / 幂等                    │
│   processor → 单条归一化与内容补全                            │
│   media     → 媒体本地化 / 稳定命名 / 去重                    │
│   external  → 外链解析 / 重定向 / 正文抽取                     │
│   markdown  → 逐条 Markdown 生成                             │
│   scheduler → Windows Task Scheduler                         │
│   cli       → sync / media / links / process / status /       │
│               doctor（retry / enrich / verify 尚未实现）        │
└──────────────────────────┬──────────────────────────────────┘
                           ▼
        knowledge/X-Bookmarks/YYYY/MM/YYYYMMDD-{tweet_id}.md
        knowledge/X-Bookmarks/YYYY/MM/assets/{tweet_id}/**
```

设计要点：

1. **Adapter 隔离**：上游可替换（`src/collector/base.py` 定义接口），知识处理链路不受影响。
2. **双层分离**：`data/` 是程序数据（被 gitignore），`knowledge/` 是用户知识库（人类可读、可长期维护）。
3. **不实现 Cookie 解密**：认证与解密属上游职责，上游修复后本项目零改动受益。

---

## 4. 目录结构

```text
X-Bookmark-Knowledge/
├── AGENTS.md                  Agent 工作规范
├── README.md                  本文件
├── PLAN.md                    阶段计划与决策表
├── CHANGELOG.md               变更记录
├── .gitignore                 安全忽略规则
│
├── config/
│   ├── config.example.yaml    配置模板（入 Git）
│   ├── config.yaml            本机配置（不入 Git）
│   └── .gitignore
│
├── docs/
│   └── environment-report.md  Phase 0 环境报告
├── research/
│   ├── open-source-comparison.md   Phase 1 开源项目比较
│   └── architecture-decision.md    Phase 2 架构决策
│
├── src/
│   ├── collector/             采集适配器（复用上游）— Phase 5 ✅
│   ├── ingest/                入库与状态机 — Phase 6 ✅
│   ├── processor/             单条内容加工 — Phase 11
│   ├── media/                 媒体本地化 — Phase 8 ✅
│   ├── external/              外链解析（fetcher + handlers/ 分站处理器 + resolver）— Phase 9 ✅
│   ├── markdown/              Markdown 生成 — Phase 7 ✅
│   ├── database/              schema / 迁移 / 查询 — Phase 4 ✅
│   ├── scheduler/             调度封装 — Phase 13
│   └── cli/                   命令行入口 — Phase 6+ ✅（sync / media / links / process / status / doctor）
│
├── data/                      程序数据（不入 Git）
│   ├── upstream/              上游只读输入：bookmarks.jsonl · media-manifest.json · media/**
│   ├── raw/                   逐条原始 JSON
│   ├── state/                 SQLite 状态库
│   └── logs/                  YYYY-MM-DD.log
│
├── knowledge/
│   └── X-Bookmarks/           用户知识库产出：YYYY/MM/*.md + YYYY/MM/assets/{tweet_id}/**
│                              ⚠️ 书签内容与媒体默认不入 Git（仅 README.md 被跟踪）
│
├── tests/                     测试
└── scripts/                   运维脚本（PowerShell 5.1）
```

---

## 5. 安装

### 5.1 前置依赖

| 依赖 | 版本要求 | 本机状态 |
| --- | --- | --- |
| Windows | 10/11 | ✅ |
| Python | 3.11+（本项目固定 3.12） | ✅ 3.12.13 可用（`%APPDATA%\uv\python\cpython-3.12.13-windows-x86_64-none`） |
| Node.js | ≥ 20 | ✅ v24.14.0 |
| `fieldtheory` CLI | 最新版 | ✅ 1.3.22 已全局安装 |
| 可用会话的浏览器 | Firefox（推荐）/ Chrome / Edge | ⚠️ 见第 7 节认证 |

### 5.2 安装步骤

```powershell
# 1) 进入项目目录
cd D:\Users\label-workplace\Agent-Eval\AI-Agent-Lab\01_Knowledge-Agent\projects\X-Bookmark-Knowledge

# 2) 创建虚拟环境（固定 Python 3.12）
& "$env:APPDATA\uv\python\cpython-3.12.13-windows-x86_64-none\python.exe" -m venv .venv
.\.venv\Scripts\Activate.ps1

# 3) 安装依赖（Phase 4 起提供 requirements.txt / pyproject.toml）
pip install -r requirements.txt

# 4) 生成配置
Copy-Item config\config.example.yaml config\config.yaml
```

```powershell
# 5) 安装上游采集器（若尚未安装）
npm install -g fieldtheory

# 6) 自检
python -m src.cli doctor
```

> **现状（2026-10-10）**：`.venv`（Python **3.13.12**）与 `requirements.txt`（PyYAML 6.0.3）已就绪；上游 `fieldtheory@1.3.22` 本机已安装（PowerShell 中用 `fieldtheory.cmd`，不要用 `ft`）；`python -m src.cli doctor` 自 Phase 6 起可用（实测输出 `Doctor result: OK`）。
>
> **入口（Phase 5 起）**：仓库已含 `pyproject.toml`，其中声明了 `xbk` 控制台入口
> （`[project.scripts] xbk = "src.cli.main:main"`）。**需先 `pip install -e .` 才生效**（该安装动作
> 尚未执行）；未安装时一律用等价的 `python -m src.cli`，两者入口函数相同。运行时依赖仍只走
> `requirements.txt`（`dependencies = []`）。
>
> **代码来源**：本项目已托管在**私有**仓库 `https://github.com/dyanpeng-ops/X-Bookmark-Knowledge.git`；新机器 `git clone` 后从第 2 步继续（需要该账号登录或 PAT）。仓库**不含** `config/config.yaml`、`data/` 与书签内容。
>
> 测试运行方式：macOS/Linux `.venv/bin/python -m unittest discover -s tests -t .`；Windows `.\.venv\Scripts\python.exe -m unittest discover -s tests -t .`（**跑测试前须先获得用户批准**，见第 14 节）

---

## 6. 配置

配置文件：`config/config.yaml`（从 `config.example.yaml` 复制，**不入 Git**）。

主要配置块：

| 块 | 作用 |
| --- | --- |
| `paths` | 项目根、`data/`、`knowledge/`、上级 inbox 交接点 |
| `collector` | 上游可执行文件、采集开关（media/gaps/folders）、超时 |
| `collector.auth` | 认证方式（firefox / cookies / oauth）与浏览器选择 |
| `ingest` | 去重键、失败重试上限、增量提前结束阈值 |
| `media` | 是否下载、是否含视频、单文件上限、稳定命名 |
| `external` | 外链抓取超时/重试/单页上限/分站处理器（已实现的 handler：`web` / `github`） |
| `markdown` | 文件名模式、frontmatter、段落开关、覆盖策略 |
| `ai` | AI 增强开关、引擎、以及**绝对不可被 AI 修改的字段列表** |
| `logging` | 日志级别、每日文件、同步报告 |
| `scheduler` | 任务名、每日时间、执行命令 |
| `safety` | 禁止写出项目目录、禁止写上游、日志脱敏 |

安全要求：密钥只通过环境变量注入；配置文件中只写环境变量名。

---

## 7. 认证

本项目不做 X 登录，认证与 Cookie 解密由上游 `fieldtheory` 负责。三条路径按优先级：

### ① Firefox 会话（推荐）

Firefox 的 `cookies.sqlite` 不加密，是最可靠的无人值守路径。

**2026-09-16 实测通过**（Firefox 156.0 + `fieldtheory` 1.3.22）：

```text
fieldtheory.cmd sync --browser firefox --no-media --yes --max-pages 1
  ✓ 5 new bookmarks synced (5 total)     exit 0
```

注意：上游默认的增量模式在**连续 3 页无新增**后即停止；要采集完整历史必须显式加 `--continue`（或首轮用 `--rebuild`）。

```powershell
# 先在 Firefox 中登录 x.com，然后：
fieldtheory sync --browser firefox --no-media --yes
```

### ② 手工 Cookie（临时排障）

Chrome 155 起使用 App-Bound Encryption（Cookie 前缀 `v20`），上游 1.3.22 无法解密，故不能直接用 Chrome 会话。可从 DevTools 取 Cookie 手工传入：

```powershell
# ct0 与 auth_token 等价于密码：不要写入配置、日志或对话记录
fieldtheory sync --cookies <ct0> <auth_token> --no-media --yes
```

### ③ OAuth（需 X 开发者应用）

```powershell
# 在 config.yaml 或环境变量中提供 X_CLIENT_ID / X_CLIENT_SECRET，回调 URL 默认 http://127.0.0.1:3000/callback
fieldtheory auth
fieldtheory sync --api
```

> 详细论证与取舍见 `research/architecture-decision.md` 第 5 节。

---

## 8. 首次同步

```powershell
python -m src.cli sync
```

`sync` 只做"采集 + 入库"；媒体、外链、Markdown 由后续三条命令完成（顺序见第 9 节）：

1. `sync` —— 调用上游完成采集（数据落在 `data/upstream/`，本项目只读）→ 逐条 ingest 到 SQLite → 打印报告
2. `media` —— 上游媒体本地化到 `assets/{tweet_id}/`
3. `links` —— 外链正文抓取到 `assets/{tweet_id}/links/`（Phase 9，**未验收**）
4. `process` —— 渲染逐条 Markdown 到 `knowledge/X-Bookmarks/`

`sync` 的实际报告（字段名以代码为准）：

```text
Sync report
  finished at   : 2026-09-20T02:40:49Z
  upstream dir  : <project>/data/upstream
  upstream rows : 5
  enrichment    : 5 record(s) from `list --json`
  fetched       : 5
  new           : 5
  updated       : 0
  unchanged     : 0
  failed        : 0
  transitions   : NEW/FAILED -> COLLECTED = 0
  raw archives  : 5 written, 0 unchanged
  media rows    : 6 new, 0 updated, 0 unchanged
  link rows     : 5 new, 0 updated, 0 unchanged
  db status     : COLLECTED 5 | COMPLETED 0 | ENRICHED 0 | FAILED 0 | NEW 0 | PROCESSED 0
  last synced   : 2026-09-20T02:40:49Z
```

## 9. 增量同步

再次运行同一条命令即可：

```powershell
python -m src.cli sync
```

幂等保证：

- `tweet_id` 在 SQLite 中唯一
- 已处于 `PROCESSED/ENRICHED/COMPLETED` 的记录直接跳过
- Markdown 已存在且内容哈希一致时不重写
- 媒体已存在且哈希一致时不重复复制（`media.local_path` 已指向知识库内文件）
- 外链正文已存在且与最新抓取一致时不重写；`FETCHED` 的外链**不重复联网**（`--force` 才重抓）

**验收标准**：同一任务连续执行两次，第二次 `New: 0`，且 `knowledge/` 下不新增任何重复文件。

**流水线顺序**（Phase 9 起为四条命令，各司其职）：

```powershell
python -m src.cli sync      # 采集 + 幂等入库
python -m src.cli media     # 媒体本地化（先加 --dry-run 可只看不写）
python -m src.cli links     # 外链正文抓取（--dry-run / --force / --tweet-id / --limit）
python -m src.cli process   # 渲染 Markdown；媒体与外链段引用本地相对路径
```

**Canonical 流水线（Phase 4–5；与上面四条命令并存）**：

```bash
python -m src.cli normalize --apply     # 上游 JSONL(+ data/raw 富化) → data/normalized/*.json
python -m src.cli render --apply        # data/normalized/*.json → knowledge/X-Bookmarks/**
python -m src.cli rebuild-index --apply # data/normalized/*.json → SQLite 内容索引（删库重建）
```

- 三者**默认都是演练**：不创建、不修改任何文件；确认输出无误后再加 `--apply` 落盘。
- `render` **不覆盖内容不同的既有 Markdown**（AGENTS §14）：内容相同跳过、不同记为冲突且原文件保持不变，
  仅在显式 `--overwrite` 时改写。
- `rebuild-index` 的「**运行态字段重建即重置**」语义写入 `--help`（R6 决策）：内容索引可由
  `normalized/*.json` 重建，运行态（状态/重试/错误/时间戳/媒体与外链状态）无重建来源，重建后回初始态；
  需要保留处理进度时改用 `--in-place`（按 `content_hash` 幂等刷新，不动运行态）。
- 三者均支持 `--normalized-dir` 等目录覆盖参数，便于在临时目录做只读演练。

外链行为（Phase 9）：

- 成功：标题与正文写入 `assets/{tweet_id}/links/{link_key}.md`，SQLite 记录 `resolved_url/title/content_path/FETCHED`；
  Markdown 的 `## external_links` 显示 `- [标题](原始 URL)` + 正文相对路径。
- 失败：状态 `FAILED` 并记录原因与尝试次数，**原始 URL 永远保留**；`external.max_attempts`（默认 3）到顶后不再重试，需 `links --force`。
- 跳过（不联网）：非 http(s) 链接、`external.skip_domains`（默认 `x.com`/`twitter.com`，正文已由 `## article` 提供）、
  单条推文超出 `max_links_per_tweet`、未实现的内容类型（如 `pdf`）。
- SSRF 防护（复审修复）：目标为主机回环/私网/链路本地/云元数据等非公网地址时直接拒绝并发请求
  （初始与每一跳重定向后均复核），记为策略跳过；由 `external.block_non_public_hosts`（默认开启）
  控制，`external.allow_hosts` 为显式白名单。
- dry-run 语义：`links --dry-run` 仍会发起真实网络请求，仅不写文件/库（与 `media --dry-run`、
  `process --dry-run` 纯本地不同）。
- 网络面：标准库 `urllib`，timeout/重试/退避/逐跳重定向/编码探测/单页体积上限；请求间有 `external.delay_seconds` 礼貌间隔。

---

## 10. AI 配置（Phase 11，默认关闭）

```yaml
ai:
  enabled: false
  provider: "upstream-classify"   # 复用上游 ft classify，或改 claude-cli / codex-cli
  engine: "claude"
  write_to: "frontmatter_and_section"
```

约束（硬性）：

- AI 只能**追加**：frontmatter 中的 `ai_*` 字段，以及正文的 `## ai_analysis` 段（段落名以渲染器为准，ADR-015）。
- AI **绝对不可修改**：`tweet_id`、`tweet_text`、`author`、`created_at`、`tweet_url`、`source`。
- 计划中的 `verify` 命令（Phase 10）会校验原始字段哈希未变，一旦被改动即报错；该命令**尚未实现**。
- AI 失败不影响已生成的基础 Markdown（状态停在 `PROCESSED`，可重试）。

---

## 11. Windows Scheduler

```powershell
# 安装（默认每天 08:00）
powershell -ExecutionPolicy Bypass -File scripts\install-scheduler.ps1

# 查看
schtasks /query /tn "XBookmarkKnowledge-Sync"

# 立即手工运行一次
schtasks /run /tn "XBookmarkKnowledge-Sync"

# 卸载
powershell -ExecutionPolicy Bypass -File scripts\uninstall-scheduler.ps1
```

要求：无交互运行、日志落 `data/logs/`、失败返回非零退出码、可随时手动关闭。

> 状态：`scripts/` 下的三个脚本属 **Phase 13**，当前目录只有 `README.md`，因此上面的命令**尚不可用**（见 `scripts/README.md`）。

---

## 12. 故障排查

| 症状 | 可能原因 | 处置 |
| --- | --- | --- |
| `Couldn't connect to your browser session.` | Chrome 155 的 Cookie 为 `v20`（ABE），上游无法解密 | 改用 Firefox 会话（已实测可用），或手工 `--cookies` / OAuth（见第 7 节） |
| 历史书签没抓全 / 第二次 `sync` 报 `All caught up` | 默认增量在连续 3 页无新增后停止，不会继续翻页 | 首轮或补历史时加 `--continue`，或执行 `--rebuild` 全量重爬 |
| Article 书签的正文是空的 | 正文**不在** `bookmarks.jsonl`，只在上游 `bookmarks.db` | 先 `sync --gaps` 展开，再通过 `fieldtheory list --json` / `show <id> --json` 读取（本项目 Adapter 已如此实现） |
| 想确认账号到底有多少书签 | 单次 `sync` 的退出码不能证明覆盖完整 | 交叉核对 `bookmarks-meta.json: totalBookmarks`、`fieldtheory stats --json`、`backfill-state.stopReason` |
| `C:` 盘空间吃紧 | 上游媒体默认下载到上游数据目录（本项目已按 ADR-011 重定位到 `data/upstream/`，单文件上限 200 MB） | 保持 `FT_DATA_DIR` 指向 `D:`，或用 `--no-media` / `--skip-profile-images` |
| PowerShell 中输入 `ft` 无反应 | `ft` 是 PowerShell 内置别名 `Format-Table` | 使用 `fieldtheory` 或 `ft.cmd` |
| 命令挂住不返回 | 上游某些子命令（如裸 `fieldtheory model`）是交互式的 | 不在脚本/定时任务中调用交互式子命令 |
| 同步成功但 `New: 0` | 没有新书签，或 Cookie/OAuth 已过期 | 运行 `python -m src.cli doctor` 检查认证 |
| `knowledge/` 中 Markdown 缺少图片 | 媒体未本地化，或上游源文件缺失 | 查看 `media` 表状态与 `error_message`，执行 `python -m src.cli media`（先 `--dry-run` 可只看不写） |
| 外链正文为空 | 目标站点反爬/超时 | 属预期降级：Markdown 中保留原始 URL 与失败原因 |
| 磁盘空间不足 | 视频/大图累积 | 关闭视频下载（`media.download_video: false`），检查 `D:` 余量 |
| 同一命令重复执行产生重复文件 | 幂等逻辑缺陷 | **视为 bug**，用 `tests/test_ingest.py` / `tests/test_media.py` 中的幂等用例复现并修复 |

---

## 13. 安全说明

- **数据不出本机**：本项目不向任何第三方上报数据；唯一网络行为是采集（上游负责）与外链正文抓取（自研）。
- **敏感信息不入库**：`.gitignore` 覆盖 `config/config.yaml`、`.env*`、`cookies*`、`tokens*`、`credentials*`、`*.db`、`data/`。
- **个人数据不入库**：仓库是**私有**库，且 `knowledge/*` 默认被忽略——真实书签 Markdown 与媒体资产**不进 Git**（仅 `knowledge/X-Bookmarks/README.md` 被跟踪）；确需纳管时用 `git add -f <路径>`。
- **日志脱敏**：日志中只允许出现"凭证是否存在"，不允许出现凭证值。
- **只读上游**：不写入 `~/.fieldtheory/**`。
- **不越界写入**：禁止写入项目目录之外的路径、禁止直接写上级 `knowledge/`。
- **只读 X**：本管道不会新增、删除或修改 X.com 上的任何书签。

---

## 14. 开发说明

### 开发流程（每个 Phase）

1. 改代码 → 2. **提交「待验证清单」并等待用户批准** → 3. 按批准项跑测试 → 4. 检查文件 →
5. 更新 `PLAN.md` → 6. 更新 `CHANGELOG.md` → 7. 汇报 → 8. 标记下一阶段。

> **验证授权关卡（2026-09-20 用户指令，见 `AGENTS.md` 第 2 节第 16 / 17 条）**：只读检查（读文件、搜索、`git status` / `git log`）可直接做；
> **跑测试、任何联网（`git ls-remote` / `clone` / `fetch` / `push` / 抓网页）、任何写盘（含提交、写数据库 / 知识库）、任何动用账号凭据的操作，都必须先给出「命令 + 目的 + 影响范围」并得到批准**；
> 未获批准时，阶段只能表述为“实现完毕、未验收”，不得对外声称已验证。

### 代码组织约定

| 目录 | 职责 | 不允许 |
| --- | --- | --- |
| `src/collector/` | 上游适配（只读） | 写上游目录、写 Markdown |
| `src/ingest/` | 入库、状态机、去重 | 网络抓取 |
| `src/processor/` | 单条内容加工/补全 | 直接写知识库 |
| `src/media/` | 媒体下载与本地化 | 修改 Markdown 正文 |
| `src/external/` | 外链解析与正文抽取 | 依赖 AI |
| `src/markdown/` | Markdown 渲染 | 发起网络请求 |
| `src/database/` | schema/迁移/查询 | 业务逻辑 |
| `src/scheduler/` | 调度封装 | 业务逻辑 |
| `src/cli/` | 参数解析、编排、报告 | 实现业务算法 |

### 测试约定

- 禁止访问真实网络（注入 fake fetcher）
- 禁止读取真实上游目录（用 `tests/fixtures/` 样本）
- 禁止写真实 `knowledge/`（用临时目录）

详细规范见 `AGENTS.md`。

---

## 15. 项目状态

| Phase | 状态 |
| --- | --- |
| 0 环境检查 | ✅ 完成（`docs/environment-report.md`） |
| 1 开源项目评估 | ✅ 完成（`research/open-source-comparison.md`） |
| 2 采集策略 | ✅ 完成（`research/architecture-decision.md`） |
| 3 项目骨架 | ✅ 完成 |
| 4 数据模型（SQLite） | ✅ 完成：`src/database/`（9 模块）+ `tests/test_database.py`（68 用例全绿）+ `.venv` |
| 5 Collector（上游适配） | ✅ 完成（2026-09-16）：`src/collector/`（`base.py` / `contract.py` / `fieldtheory_adapter.py`）+ 76 用例；前置条件 A–D 全部用真实数据关闭 |
| 6 增量同步 + CLI | ✅ 完成（2026-09-16）：`src/config.py`（PyYAML）+ `src/ingest/` + `src/cli/`（sync/status/doctor）+ 60 用例；**M2 幂等达成** |
| 7 逐条 Markdown 生成 | ✅ 完成（2026-09-17）：`src/markdown/`（render + writer）+ `process` 子命令 + 23 用例；**M3 达成**（真实 5 条，二次运行 `written: 0 / unchanged: 5`） |
| 8 媒体本地化 | ✅ 完成（2026-09-20）：`src/media/localizer.py` + `media` 子命令 + 44 用例；6/6 真实媒体本地化、`media.local_path` 归一至知识库内、`## media` 引用本地相对路径（ADR-016） |
| 9 外链正文抽取 | ✅ 实现完毕 + 复审关闭（2026-09-21）：fetcher + handlers + resolver + netguard（SSRF 逐跳防护），canonical 入库；94 用例经批准全绿。代码已提交（`78ed077`）；真实数据写运行仍待批准（ADR-017/018）。2026-10-09 依第三方审计修复 CFG-01（`LinkResolver` 默认分支漏传安全配置），SEC-01（DNS 重绑定）待决策 |
| 10+ 完整性 / AI / 交接 / 调度 | ⏳ 未开始 |

**当前实现的代码范围**：`src/database/`、`src/collector/`、`src/config.py`、`src/ingest/`、`src/markdown/`、`src/media/`、`src/external/`、`src/cli/`。`src/processor/`、`src/scheduler/` 仍只有包声明。

**验证命令**

```bash
# macOS / Linux（项目根目录）
.venv/bin/python -m unittest discover -s tests -t .
# Windows
# .\.venv\Scripts\python.exe -m unittest discover -s tests -t .

# 最近一次实测：2026-10-09 macOS，Ran 530 tests，9 failures
#   - 9 个失败全部是**平台语义断言**（macOS 的 /var → /private/var 软链使 startswith(知识库根) 失败、
#     Windows 盘符断言、机器环境变量），与业务代码无关，归 Phase 6 跨平台范畴。
#   - 第三方在 Linux 沙箱复跑为 3 failures + 16 errors（其中 14 个 error 是沙箱 DNS 把 example.com
#     解析到 198.18.11.198，被 netguard 正确拦截）。
#   - 结论：**「失败数」不是可移植的验收口径**，Phase 6 必须重建分类基线（详见
#     docs/phase3-preflight-review.md §10.8.3）。
# 注：`links --dry-run` 会发起真实 HTTP；真实数据写运行仍待批准
```

**日常运行**（采集 + 入库 + 媒体本地化 + 外链抓取 + Markdown；第二次执行 New 必须为 0）

```powershell
python -m src.cli sync              # 采集（上游 fieldtheory）+ 幂等入库 + 报告
python -m src.cli sync --skip-collect  # 只入库已有上游数据（不联网）
python -m src.cli media             # 媒体本地化到知识库 assets/（--dry-run 只看不写）
python -m src.cli links             # 外链正文抓取（--force 重抓已抓过的；dry-run 会联网但不写盘）
python -m src.cli process           # 渲染 Markdown（--overwrite 允许覆盖变化内容）
python -m src.cli status            # 只读状态
python -m src.cli doctor            # 环境自检
```

**真实上游只读校验**（不联网、不写入上游；确认冻结的字段契约在真实数据上成立）

```text
FieldTheoryAdapter().check_ready()                 → ready=True, records=5
read_bookmarks() / read_media_manifest()           → 契约校验通过
list_enriched()                                    → 4 篇 article 正文可取（JSONL 中不存在）
ALL REAL-DATA READS OK   (exit 0, fieldtheory 1.3.22)
```
