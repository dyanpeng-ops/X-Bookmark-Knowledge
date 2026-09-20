# Architecture Decision — Phase 2

> 项目：X Bookmark Knowledge Pipeline
> 生成阶段：Phase 2（确定采集策略）
> 生成时间：2026-09-15
> 决策状态：**已获用户批准**（2026-09-15，用户选择"推荐方案")
> 依据：`docs/environment-report.md`（Phase 0）+ `research/open-source-comparison.md`（Phase 1）

---

## 1. 背景与硬约束

| 约束 | 来源 | 对本决策的影响 |
| --- | --- | --- |
| 运行环境为 Windows，仅 Windows PowerShell 5.1 | Phase 0 | 采集工具必须能无人值守在 Windows 上跑；调度用 `schtasks` |
| `C:` 仅剩 6.4 GB | Phase 0 | 所有数据必须落 `D:` |
| 本机 Chrome 155 的 Cookie 为 `v20`（ABE） | Phase 0 实测 | 直接排除"依赖 Chrome Cookie 自动提取"作为唯一认证路径 |
| 已有空目录 `projects/X-Bookmark-Knowledge` | Phase 0 | 不新建平行项目，不覆盖任何既有内容 |
| 上层 `AGENT.md` 规定"先收集再整理"、"知识与原始资料分离" | Phase 0 | `data/` 与 `knowledge/` 必须物理分离；产物先入 `inbox` 流程 |
| 不引入 RAG / 向量库 / 知识图谱 / 多 Agent / MCP | Phase 0 继承规范 + 执行计划 | 自研部分只用 stdlib + 极少量必要依赖 |
| 不得把 Cookie / Token / Secret 写入 Git | 执行计划 §20 | `.gitignore` + `config.example.yaml` 模板机制 |
| 增量、幂等、"同任务跑两次不产生重复数据" | 执行计划 §六/§十九 | 状态机 + `tweet_id` 唯一约束 + 写前检查 |
| 单条失败不影响整体 | 执行计划 §一/8 | 逐条 try/catch + 状态标记 + `retry` 命令 |
| 网络请求需 timeout / retry / 错误记录 | 执行计划 §一/9 | 自研外部抓取层必须实现 |

---

## 2. 决策

**采用执行计划的"第二优先"：成熟项目作为 Collector + 核心环节自研。**

```text
┌──────────────────────────────────────────────────────────────┐
│ Collector（复用）  fieldtheory CLI（MIT / Node / 已装 v1.3.22）│
│   fieldtheory sync ...                                       │
│     ├── ~/.fieldtheory/bookmarks/bookmarks.jsonl   ← 原始记录 │
│     ├── ~/.fieldtheory/bookmarks/media-manifest.json          │
│     └── ~/.fieldtheory/bookmarks/media/**                     │
└───────────────────────────┬──────────────────────────────────┘
                            │  Adapter（自研，只读，不改上游数据）
                            ▼
┌──────────────────────────────────────────────────────────────┐
│ 本项目自研（Python 3.12 venv）                                │
│   ingest      → SQLite 状态机 / 幂等 / 增量游标                │
│   processor   → 单条 Tweet 归一化与内容补全                    │
│   media       → 媒体本地化、稳定命名、去重、失败重试            │
│   external    → 外链解析、重定向、正文抽取、Markdown 清洗       │
│   markdown    → 1 Tweet = 1 Markdown，自有 frontmatter 与目录   │
│   database    → schema / migration / FTS 可选                 │
│   scheduler   → Windows Task Scheduler 安装/卸载脚本           │
│   cli         → sync / status / retry / process / enrich /     │
│                 verify / doctor                               │
└───────────────────────────┬──────────────────────────────────┘
                            ▼
        knowledge/X-Bookmarks/YYYY/MM/YYYYMMDD-{tweet_id}.md
        knowledge/X-Bookmarks/YYYY/MM/assets/{tweet_id}/**
                            │
                            ▼  交接（不改上层规范）
        01_Knowledge-Agent/inbox/X-Bookmarks/  → 由 Knowledge-Agent 提炼后入 knowledge/
```

### 2.1 决策要点

| 决策项 | 结论 |
| --- | --- |
| 采集层 | 复用 `fieldtheory` CLI，本项目**不实现** X GraphQL 客户端 |
| 耦合方式 | Adapter 模式：`src/collector/base.py` 定义接口，`fieldtheory_adapter.py` 为默认实现 |
| 上游数据所有权 | 上游目录只读；本项目**不写** `~/.fieldtheory/**`，只读其 JSONL / manifest / media |
| 状态权威 | 本项目的 SQLite（`data/state/*.db`）是唯一权威状态；上游文件视为"输入源" |
| 知识库终点 | 项目内 `knowledge/` 产出 → 交接至上层 `inbox/X-Bookmarks/`，**不直接写上层 `knowledge/`** |
| AI 分析 | 后置（Phase 11），不参与基础采集链路；`fieldtheory classify` 与自研 enrich 二选一或并存，需在 Phase 11 决策 |
| 语言 | Python（与执行计划 `python -m src.cli` 一致），venv 用本机 3.12.13 |

---

## 3. 候选方案对比与排除理由

| # | 方案 | 对应执行计划优先级 | 判定 | 理由 |
| --- | --- | --- | --- | --- |
| A | 整体复用某个项目（如整体采用 fieldtheory / TweetKB） | 第一优先 | ❌ 排除 | fieldtheory 自带数据目录（`~/.fieldtheory`）、自有 SQLite 与 Markdown 规范，会接管知识库并把数据放到用户主目录，与"项目内 data/knowledge 分离 + 接入既有 Knowledge-Agent"直接冲突；TweetKB 则是 macOS 优先且 Windows 未声明 |
| B | **成熟项目作 Collector（fieldtheory）+ 其余自研** | 第二优先 | ✅ **采用** | 只借用"最难自研"的采集与媒体下载能力，同时保留数据模型、Markdown 规范与调度权 |
| C | 多项目组合（如 fieldtheory 采集 + TweetKB 分析） | 第三优先 | ❌ 排除 | 两套 SQLite/状态模型并存会产生双权威，幂等与去重难以保证；维护成本高于收益 |
| D | 对某项目二次开发（fork 上游补 Windows/外链能力） | 第四优先 | ❌ 排除 | 上游为 TypeScript/Node（fieldtheory）或 macOS 优先（TweetKB），改造后需长期跟进上游；且执行计划要求本项目为 Python CLI |
| E | 自研 X Collector（GraphQL + Cookie/OAuth） | 最后 | 🔒 保留为兜底 | 违反"不重复造轮子"；仅在 B 的认证路径全部失效、且 D 不可行时启用。此时可参照 `--cookies` 路径的最小实现（`ct0` + `auth_token` + GraphQL 分页） |

**为什么不是"直接复用"（第一优先）**：本项目的最终验收标准包含"写入个人知识库 + AI 分析 + 下次同步跳过已处理"，这意味着**状态与产物格式必须由本项目掌握**。直接复用会把"知识库的形态"交由第三方工具的版本发布决定，这与上层 `AGENT.md` 的"知识/原始资料分离、可长期维护"原则相悖。

---

## 4. 数据如何进入本项目

### 4.1 边界定义

| 目录 | 归属 | 是否进 Git | 说明 |
| --- | --- | --- | --- |
| `data/raw/` | 程序数据 | ❌ | 原始 JSON 快照（从上游 JSONL 抽取的逐条记录） |
| `data/state/` | 程序数据 | ❌ | SQLite 状态库、同步游标、去重索引 |
| `data/logs/` | 程序数据 | ❌ | 每日日志 `YYYY-MM-DD.log` |
| `knowledge/X-Bookmarks/` | **用户知识库** | ✅（文本） | 逐条 Markdown + `assets/` 媒体 |
| `config/config.yaml` | 本机配置 | ❌ | 含路径与密钥引用 |
| `config/config.example.yaml` | 模板 | ✅ | 无任何真实密钥 |

### 4.2 数据流（Phase 5 实现时的契约草案）

```text
① fieldtheory sync --no-media ...        （由本项目调度，或在 CLI 内以子进程调用）
② Adapter 读取 bookmarks.jsonl → 逐行 JSON
③ 取 tweet_id（即上游 status id 字段）
④ 查 data/state/*.db：
     已存在且 status ∈ {PROCESSED, ENRICHED, COMPLETED} → SKIP
     已存在且 status = FAILED 且 重试次数未超限            → 重试
     不存在                                              → 新增
⑤ 写入 data/raw/{tweet_id}.json         （原始留档，永不删除）
⑥ 归一化为内部统一结构 → 写 SQLite bookmarks 表
⑦ processor / media / external / markdown 依次处理
⑧ 产物写 knowledge/X-Bookmarks/...，状态推进
```

**幂等保证的三道闸**：`tweet_id UNIQUE` 约束 + 处理前状态查询 + Markdown 写入前"同路径存在且内容哈希一致则跳过"。

### 4.3 与上游的字段映射（✅ Phase 5 已用真实样本冻结）

真实样本：2026-09-16 采集，`fieldtheory@1.3.22`，5 条记录 / 6 个媒体条目 / 4 篇 article。
冻结位置：`src/collector/contract.py`；快照测试：`tests/test_collector_contract.py`。

**A. `bookmarks.jsonl`（原始层，逐行 JSON）**

| 本项目字段 | 上游键 | 类型 | 实测备注 |
| --- | --- | --- | --- |
| `tweet_id` | `tweetId` | str | 同时存在 `id`，两者实测相等 |
| `url` | `url` | str | `https://x.com/{handle}/status/{id}` |
| `tweet_text` | `text` | str | Article 书签此处是 `x.com/i/article/{id}…` 占位符 |
| `username` | `authorHandle` | str | |
| `author_name` | `authorName` | str | |
| `author_profile_image_url` | `authorProfileImageUrl` | str | `_normal.jpg` 变体；manifest 中是 `_400x400.jpg` |
| `author`（嵌套） | `author` | dict | 必填 `id`/`handle`/`name`；另含 `bio`/`followerCount`/`followingCount`/`isVerified`/`location`/`snapshotAt` |
| `created_at` | `postedAt` | str | 格式 `Sat Jun 20 12:56:42 +0000 2026`（RFC822 风格，非 ISO） |
| `bookmarked_at` | `bookmarkedAt` | str \| null | **实测 5/5 全为 null**：X 不再返回可靠的书签时间 |
| `synced_at` | `syncedAt` | str | ISO-8601 `...Z` |
| `conversation_id` | `conversationId` | str \| null | |
| `language` | `language` | str \| null | Article 常为 `zxx`（无语言内容） |
| `possibly_sensitive` | `possiblySensitive` | bool | |
| `engagement`（扁平化） | `engagement` | dict | 必填 `likeCount`/`repostCount`/`replyCount`/`quoteCount`/`bookmarkCount` |
| 媒体 URL | `media` | list[str] | |
| 媒体对象 | `mediaObjects` | list[dict] | 必填 `type`/`url`；含 `expandedUrl`/`width`/`height`（photo 已实测；video 未实测） |
| 外链 | `links` | list[str] | 可含重复项（实测有 `['https://cobalt.tools', 'https://cobalt.tools']`） |
| 标签 | `tags` | list[str] | 实测为空 |
| 采集途径 | `ingestedVia` | str | 实测 `graphql` |
| 排序索引 | `sortIndex` | str | |
| 正文展开时间 | `textExpandedAt` | str \| 缺失 | **可选**，仅 `--gaps` 处理过的记录出现 |

**B. `media-manifest.json`（媒体层）**

顶层：`schemaVersion`(=1) / `generatedAt` / `limit` / `maxBytes` / `processed` / `downloaded` / `skippedTooLarge` / `failed` / `entries[]`。
条目：`bookmarkId` / `tweetId` / `tweetUrl` / `authorHandle` / `authorName` / `sourceUrl` / `localPath` / `contentType` / `bytes` / `status` / `fetchedAt`。
`status` 实测只出现 `downloaded`；`skippedTooLarge`/`failed` 计数为 0，其状态字符串**未实测**。

**C. 富化层（`fieldtheory list --json` / `show <id> --json`）—— Article 正文只在这里**

`articleTitle` / `articleText` / `articleSite` / `enrichedAt` / `categories` / `primaryCategory` / `domains` / `primaryDomain` / `githubUrls` / `viewCount` / `folderIds` / `folderNames` / `quotedStatusId` / `quotedTweet` / `mediaCount` / `linkCount` + 扁平化的互动数。

> **重要**：Article 正文（实测 12558 / 11149 / 2842 / 1898 字符）**不在 JSONL 中**，只在上游 `bookmarks.db`，且仅通过 `list|show --json` 暴露。因此 Adapter 采用双源：JSONL 取原始记录，`list --json` 取富化。`primaryCategory` 实测为 `unclassified`（尚未运行上游 `classify`）。

**D. 状态文件**

- `bookmarks-meta.json`：`provider` / `schemaVersion` / `lastIncrementalSyncAt` / `totalBookmarks`
- `bookmarks-backfill-state.json`：`provider` / `lastRunAt` / `totalRuns` / `totalAdded` / `lastAdded` / `lastSeenIds` / `stopReason`（+ **可选** `lastCursor`）；已观测 `stopReason`：`max pages reached` / `end of bookmarks` / `caught up to newest stored bookmark`

**E. 分页与增量语义（实测，影响 Adapter 的 `--continue` 决策）**

| 模式 | 行为 |
| --- | --- |
| 默认（增量） | 连续 3 页无新增即停止（`stalePageLimit = 3`）→ 只会补最新一段 |
| `--continue` | 从上次游标继续翻页，直到末页 |
| `--rebuild` | 全量重爬；实测在\"确实没有更多书签\"时同样很快结束 |

> 只靠默认增量无法保证历史全量；本项目首次采集必须显式使用 `--continue` 或 `--rebuild`。

---

## 5. 认证方案

### 5.1 现状（Phase 0 实测）

| 路径 | 状态 |
| --- | --- |
| Chrome 会话自动提取 | ❌ 失败。Chrome 155 的 Cookie 前缀为 `v20`（App-Bound Encryption），`fieldtheory@1.3.22` 只支持 `v10`/裸 DPAPI |
| Edge / Chromium | ❌ 无 x.com 登录态 |
| Firefox | ✅ **已采用**：156.0 已安装并于 2026-09-16 登录 x.com；`cookies.sqlite` 明文存储 `ct0`/`auth_token`，`sync --browser firefox` 实测 exit 0 |

### 5.2 待选路径（Phase 5 前必须定性）

| 路径 | 命令 | 优点 | 缺点 | 无人值守可行性 |
| --- | --- | --- | --- | --- |
| ① Firefox 会话 | `fieldtheory sync --browser firefox` | 无需 API、无需手工操作、Firefox Cookie 不加密 | 需先安装 Firefox 并登录 x.com（一次性成本） | ✅ 高（推荐） |
| ② 手工 Cookie | `fieldtheory sync --cookies <ct0> <auth_token>` | 立即可用、无需装浏览器 | 敏感值易泄漏；Cookie 过期即失效 | ⚠️ 低（需人工维护） |
| ③ OAuth | `fieldtheory auth` → `fieldtheory sync --api` | 跨平台最稳、token 可刷新 | 需自建 X 开发者应用（client id/secret + 回调 URL）；免费额度与 bookmark 读取权限不确定 | ⚠️ 中（取决于免费额度） |

> **2026-09-16 实测结论**：路径 ① 已跑通并作为默认；路径 ②③ 保留为备选，未启用。

### 5.3 决策与安全要求

1. **优先路径 ①（Firefox 会话）**，因为它唯一同时满足"无 API 凭证"与"无人值守"。
2. 路径 ② 仅作为临时排障手段，**任何情况下不得写入 Git、日志或 Markdown 产物**；使用后立即从 shell 历史与配置中清除。
3. 路径 ③ 若启用，凭证只存放在 `config/config.yaml`（已 gitignore）或 `.env.local`，`doctor` 命令需检查其存在性而不打印其值。
4. **无论哪条路径，本项目都不实现 Cookie 解密**——解密属上游 Collector 职责。这是本架构的关键解耦点：上游修好 `v20` 支持后，本项目零改动受益。

---

## 6. 调度方案

| 项 | 决策 |
| --- | --- |
| 机制 | Windows Task Scheduler（`schtasks`），符合执行计划 §16 |
| 脚本 | `scripts/install-scheduler.ps1` / `scripts/uninstall-scheduler.ps1`，**兼容 Windows PowerShell 5.1** |
| 默认时间 | 每天 08:00 |
| 执行内容 | 单条命令 `python -m src.cli sync`（其内部再调用上游 `fieldtheory sync` 采集） |
| 无人值守要求 | 无交互（禁止任何会提示输入的参数，例如不得裸调 `fieldtheory model`）、输出写 `data/logs/YYYY-MM-DD.log`、失败返回非零退出码 |
| 失败处置 | 日志 + 下次运行时由 `doctor` 报告上次失败；不做静默重试 |
| 手动运行 | 同一命令可手工执行 |

> 为什么不在调度脚本里直接调 `fieldtheory sync`：采集、ingest、Markdown 生成、媒体归档、外链解析需要按序执行并共享状态；单入口 `python -m src.cli sync` 才能保证"状态一致 + 报告统一"。

---

## 7. 复用与自研边界

| 能力 | 复用上游 | 本项目自研 | 说明 |
| --- | --- | --- | --- |
| X 认证与会话 | ✅ | ❌ | 上游 Collector 职责 |
| Bookmarks 抓取（GraphQL 分页/游标） | ✅ | ❌ | 含增量与断点续传 |
| 媒体下载（图片/视频/海报） | ✅（可选） | ⚠️ 本地化与命名 | 上游下载到 `media/`；本项目负责复制到 `knowledge/.../assets/{tweet_id}/`（若直接引用上游目录会导致知识库不自包含） |
| 内容补全（quote/article/外链正文） | ✅ `--gaps`（覆盖度待验） | ⚠️ 兜底实现 | Phase 5 验证后再决定是否自研补齐 |
| SQLite 状态库与幂等 | ❌ | ✅ | 本项目的唯一权威状态 |
| 数据模型与迁移 | ❌ | ✅ | `bookmarks` / `media` / `external_links` 三表起步 |
| Markdown 生成 | ❌ | ✅ | 自有 frontmatter 与 `YYYYMMDD-{tweet_id}.md` 命名 |
| 外链解析与正文抽取 | ⚠️ 部分 | ✅ | 本项目重点自研项（执行计划 §12） |
| 媒体命名稳定性与去重 | ❌ | ✅ | 稳定命名 + 内容哈希去重 |
| AI 分析（摘要/标签/主题） | ✅ 可选（`ft classify`） | ✅ | Phase 11 决策；AI 不得修改原始字段 |
| 调度 | ❌ | ✅ | Windows Task Scheduler |
| CLI / 报告 / doctor | ❌ | ✅ | 本项目统一入口 |
| 测试与幂等验证 | ❌ | ✅ | "跑两次不产生重复数据"为核心验收 |
| Agent Skill | ✅ `ft skill install`（可选） | ❌ | 可选增强，非本项目依赖 |

---

## 8. 风险与缓解

| # | 风险 | 概率 | 影响 | 缓解措施 | 触发条件/兜底 |
| --- | --- | --- | --- | --- | --- |
| R1 | **Windows 认证不可用**导致无法采集 | 中 | 致命 | Phase 5 前实测 Firefox 路径；准备 OAuth 备选 | 三条路径全失败 → 启用方案 E（自研最小 Collector）并向用户报告 |
| R2 | 上游 JSONL 字段变更导致解析失败 | 中 | 高 | Adapter 做字段白名单 + 缺失字段降级 + `verify` 命令；快照测试 | `doctor` 报告字段缺失 → 人工核对并更新映射 |
| R3 | Cookie/OAuth 过期导致定时任务静默失败 | 高 | 中 | 退出码非零 + 每日日志 + `doctor` 检查认证态 | 连续 2 天 0 新增但预期有新增 → 告警 |
| R4 | `fieldtheory` 上游停止维护或修改数据目录 | 低 | 高 | Adapter 隔离；上游数据只读；本项目状态自持 | 上游不可用 → 方案 E |
| R5 | 外链抓取被反爬/超时，导致 Markdown 不完整 | 高 | 中 | timeout + retry + 失败也保留原始 URL（执行计划 §12 强制） | 单条外链失败不影响 Tweet 整体状态 |
| R6 | 媒体体积膨胀（视频） | 中 | 中 | 沿用上游 `--media-max-bytes`；本项目默认不下载视频（可配置） | `C:` 空间紧张与本项目无关（全在 D:），但需监控 D: 增长 |
| R7 | X Article / Quote Tweet 还原不全 | 中 | 中 | Phase 5 用真实样本抽样评估，必要时自研补齐 | 抽样不达预期 → 追加 Phase 9.5 自研补全 |
| R8 | 媒体文件与知识库不同步（知识库指向上游目录） | 中 | 中 | 强制复制到 `knowledge/.../assets/{tweet_id}/`，不跨目录引用 | `verify` 命令检查 Markdown 引用的每个资源是否存在 |
| R9 | AI 分析污染原始字段 | 低 | 高 | 原始字段只读 + AI 仅追加 frontmatter `ai_*` 字段与正文 `## AI Analysis` 段 | `verify` 校验原始字段哈希未变 |
| R10 | 误写上层知识库（违反修改安全） | 低 | 高 | 本项目所有写操作限定在项目目录内；向上层只做**显式交接**（Phase 12 决策） | 交接前必须获得用户确认 |
| R11 | 知识库与 Inbox 规范冲突未解决 | 中 | 中 | 已按"项目内产出 → inbox 交接"设计（见 4.1） | 用户若改为直接写 `knowledge/`，需更新本决策 |
| R12 | Python 3.14 与 3.12 混用 | 中 | 低 | venv 固定 3.12.13；`doctor` 校验解释器版本 | `python -m src.cli doctor` 报版本不匹配 |

---

## 9. 待用户确认事项

| # | 事项 | 当前采用的默认 | 需用户确认 |
| --- | --- | --- | --- |
| 1 | 项目根路径 | `01_Knowledge-Agent\projects\X-Bookmark-Knowledge\`（文档原文的 `02-Knowledge-Agent` 不存在） | 已按实际执行，如需改回请告知 |
| 2 | 知识库终点 | 项目内 `knowledge/X-Bookmarks/` 产出 → 交接 `01_Knowledge-Agent/inbox/X-Bookmarks/` | 是否同意（替代"直接写上层 knowledge/"） |
| 3 | Python 解释器 | 3.12.13 建 venv | 是否同意（备选：3.14.3） |
| 4 | 是否 `git init` | **否**，只提供 `.gitignore` | 需要版本控制时授权 |
| 5 | 认证路径优先级 | ① Firefox ② 手工 Cookie ③ OAuth | 是否同意，或指定其他 |
| 6 | 视频是否本地化 | 待定（上游默认下载，本项目可配置关闭） | Phase 8 前确认 |
| 7 | AI 引擎 | 待定（`ft classify` vs 自研调 claude/codex CLI） | Phase 11 前确认 |
| 8 | `scripts/*.ps1` 是否创建 | Phase 13 才实现，Phase 3 仅占位说明 | 无 |

---

## 10. 决策复审触发条件

出现下列任一情况时，必须重新评估本决策（而非直接改代码）：

1. 上游 `fieldtheory` 新增 `v20`（ABE）支持，或发布 Windows 认证修复版本。
2. 三条认证路径全部失败。
3. 上游 JSONL/媒体清单发生破坏性格式变更。
4. `fieldtheory` 超过 12 个月无提交。
5. 执行计划的目标发生变化（例如要求"写入 X 书签"等写操作，而非只读归档）。
6. TweetKB 在 Windows 的采集被实测证明可用且更优。

---

## 11. Phase 2 状态

**完成**。技术路线已确定：**fieldtheory CLI 作 Collector（Adapter 隔离）+ 本项目自研 ingest / processor / media / external / markdown / database / scheduler / CLI**。
Phase 3（骨架）已建立，Phase 4 起进入实现，**Phase 5 实现 Collector 之前必须先完成第 8 节 R1 的认证验证与第 4.3 节的字段契约确认**。



