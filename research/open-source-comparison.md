# Open Source Comparison — Phase 1

> 项目：X Bookmark Knowledge Pipeline
> 生成阶段：Phase 1（GitHub 开源项目技术评估）
> 生成时间：2026-09-15
> 调研方式：GitHub REST API 元数据 + 仓库 README / docs 源码级核查（未仅凭 README 标题判断）
> 说明：本机无 git 仓库且未配置 git 身份，因此**未 clone 源码**；对实现层面的判断来自仓库内的文档文件（如 TweetKB 的 `docs/ARCHITECTURE.md`）与官方页面，凡未经源码确认的项一律标注"待源码验证"

---

## 1. 评估口径

评估维度（对应执行计划 Phase 1 检查清单）：

`许可证` · `最近提交` · `Issue` · `Release` · `安装方式` · `Windows 支持` · `X 登录方式` · `X API 使用` · `浏览器 Cookie 依赖` · `增量同步` · `Bookmark 支持` · `Tweet 完整度` · `Thread` · `Quote Tweet` · `X Article` · `图片` · `视频` · `GIF` · `外链` · `Markdown` · `Obsidian` · `SQLite` · `AI` · `CLI` · `Agent Skill` · `二次开发适配度`

评分口径：
- ✅ 明确支持（有文档或代码/文档级证据）
- ⚠️ 部分支持 / 有条件支持 / 实现细节待验证
- ❌ 不支持
- ❓ 未能确证（不可当作支持）

---

## 2. 执行计划点名项目的真实对应关系

| 计划点名 | 是否可解析 | 对应仓库 | 说明 |
| --- | --- | --- | --- |
| SaveBox | ✅ 可解析 | `AhmedFaizanDev/savebox` | 唯一同名 X 书签项目 |
| xmarks | ❌ **不可解析** | 无 | Xmarks 是 2014 年被 LastPass 收购、2018 年停服的**浏览器书签同步服务**，与 X/Twitter 书签无关；GitHub 上无同名 X 书签项目。本条目视为计划中的命名错误 |
| MarkHarbor | ✅ 可解析 | `dososo/markharbor` | 唯一同名项目 |
| TweetKB | ✅ 可解析 | `AdityaVG13/TweetKB` | 唯一同名项目 |
| XClipper | ✅ 可解析 | `zendegani/XClipper` | 需区分：另有一个 Windows/Android 剪贴板管理器也叫 XClipper，与本主题无关 |
| X Bookmark to Obsidian | ⚠️ 近似解析 | 候选：`kiki123124/x2o`、Obsidian 社区插件 `x-bookmarks-to-vault`、`ikaros-labs/x-bookmark-exporter` | 该名称不是单一仓库；以下以 `kiki123124/x2o` 为代表分析 |

---

## 3. 候选项目元数据（GitHub API 实测）

| 项目 | 仓库 | 语言 | Stars | License | 创建 | 最近提交 | Open Issues | 形态 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| SaveBox | `AhmedFaizanDev/savebox` | Python | 0 | **无 LICENSE 文件** | 2026-08-12 | 2026-08-12 | 0 | Agent Skill（Claude Code / Codex） |
| MarkHarbor | `dososo/markharbor` | TypeScript | 4 | MIT | 2026-05-17 | 2026-07-19 | 7 | Chrome 扩展 |
| TweetKB | `AdityaVG13/TweetKB` | Python | 0 | MIT | 2026-04-26 | 2026-09-12 | 0 | CLI + SQLite（含 TUI） |
| XClipper | `zendegani/XClipper` | TypeScript | 34 | **PolyForm Noncommercial 1.0.0** | 2026-02-14 | 2026-09-13 | 3 | Chrome 扩展（web clipper） |
| x2o（X→Obsidian 代表） | `kiki123124/x2o` | TypeScript + Rust | 30 | MIT | 2026-02-28 | **2026-03-23（停滞≈6 个月）** | 0 | Tauri 桌面应用 |
| **[已装] fieldtheory** | `afar1/fieldtheory-cli` | TypeScript / Node | **2020** | MIT | 2026-04-03 | 2026-09-05 | 40 | CLI（npm 全局） |
| xarchive | `sytelus/xarchive` | JavaScript | 88 | MIT | 2026-04-06 | 2026-09-05 | 6 | Chrome 扩展（Manifest V3） |
| twitter-web-exporter | `prinsss/twitter-web-exporter` | TypeScript | 2702 | MIT | 2023-09-20 | 2026-08-31 | 23 | 用户脚本 / 扩展 |
| twitter-bookmark-archiver | `nornagon/twitter-bookmark-archiver` | JavaScript | 140 | **无 LICENSE 文件** | 2022-11-09 | **2022-11-28（停滞≈4 年）** | 4 | Node 脚本（走官方 API） |

**Release 情况**：本次调研未逐仓核对 Release 资产；`dososo/markharbor` 的 homepage 指向其 releases 页面（存在 Release 机制）。其余项目的发布方式以源码/扩展商店为主。**待源码验证**。

---

## 4. 能力矩阵

| 能力 | SaveBox | MarkHarbor | TweetKB | XClipper | x2o | **fieldtheory** | xarchive | tw-web-exporter |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 采集 Bookmarks | ✅ | ✅ | ✅ | ⚠️ 需手动/批量触发 | ✅ | ✅ | ✅ | ✅ |
| X API 依赖 | ❌ 不需要 | ❌ | ❌ | ❌ | ❓ | ⚠️ 可选（`--api`） | ❌ | ⚠️ 内部 GraphQL |
| 浏览器 Cookie 依赖 | ✅ 复用会话 | ✅ 页面上下文 | ✅ | ✅ 页面上下文 | ✅ | ✅（或手工/OAuth） | ✅ | ✅ |
| Windows 支持 | ✅ 声明需 Chrome | ✅（扩展跨平台） | ❓ **未声明** | ✅（浏览器内） | ⚠️ 以 macOS 为主 | ✅（会话路径受 ABE 影响） | ✅ | ✅ |
| 增量同步 | ✅ | ❓ | ✅ | ✅（dedup ledger） | ❓ | ✅（`--continue`/默认增量） | ❓ | ⚠️ |
| 去重（tweet_id） | ✅ `--dedup` | ❓ | ✅ `status_id` + `content_hash` | ✅ | ❓ | ✅（内部索引） | ❓ | ❓ |
| Tweet 完整文本 | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Thread | ✅ 部分 | ✅ 尽量还原 | ✅ 可见上下文 | ✅ | ✅ | ✅（`--gaps` 补全） | ⚠️ | ✅ |
| Quote Tweet | ❓ | ❓ | ⚠️ | ✅ | ❓ | ✅（`--gaps` 回填被引用推文） | ❓ | ✅ |
| X Article | ❌ | ⚠️ 尝试读详情页 | ⚠️ | ✅ | ❓ | ✅（`--gaps` 展开被截断 Article） | ❓ | ⚠️ |
| 图片 | ⚠️ 可选缓存 | ✅ 下载 | ✅ `media-export` | ✅ 本地化 | ✅ | ✅ 自动下载 | ✅ | ⚠️ |
| 视频 | ❓ | ❌ 仅存链接 | ❓ | ✅ 本地化 | ❓ | ✅（含海报、有大小上限） | ❓ | ⚠️ |
| GIF | ❓ | ❓ | ❓ | ✅ | ❓ | ✅ | ❓ | ❓ |
| 外链正文抓取 | ⚠️ 保留链接 | ❌ 仅卡片元数据 | ⚠️ `enrich` 抓取链接页 | ✅ 解析 | ❓ | ✅（`--gaps` 丰富所链文章） | ❓ | ❓ |
| Markdown 产物 | ✅ `.md` | ✅ | ✅ 导出适配器 | ✅ | ✅ | ✅ `ft md` | ❓ | ✅ |
| Obsidian 适配 | ❌ | ✅ | ✅ `obsidian.py` 适配器 | ✅ | ✅ | ⚠️ 通用 Markdown | ❌ | ⚠️ |
| SQLite | ❓ | ❓ | ✅ + FTS5 | ❌ | ❓ | ✅ + FTS5 | ❌ | ❌ |
| AI 分析 | ⚠️ agent 侧 | ❌ | ✅ OpenAI / Ollama | ❌ | ✅ 19+ provider | ✅ `classify`（claude / codex CLI） | ❌ | ❌ |
| CLI 可脚本化 | ⚠️ skill 调用 | ❌ 扩展 UI | ✅ | ❌ 扩展 UI | ❌ 桌面 UI | ✅ **最完整** | ❌ | ❌ |
| Agent Skill | ✅ | ❌ | ❌ | ❌ | ❌ | ✅ `ft skill install` | ❌ | ❌ |
| 无人值守调度 | ⚠️ 依赖 agent | ❌ | ⚠️ 需浏览器自动化 | ❌ | ❌ | ✅ | ❌ | ❌ |
| 测试套件 | ❓ | ❓ | ✅ pytest | ❓ | ❓ | ❓ | ❓ | ✅ |
| 许可证可商用二开 | ❌ **无 License** | ✅ MIT | ✅ MIT | ❌ 非商业 | ✅ MIT | ✅ MIT | ✅ MIT | ✅ MIT |
| 二次开发适配度 | 低 | 中 | 中高 | 低（许可） | 低 | **高** | 低 | 中 |

---

## 5. 逐项目分析

### 5.1 SaveBox — `AhmedFaizanDev/savebox`

| 项 | 结论 |
| --- | --- |
| 定位 | Claude Code / Codex 的 **Agent Skill**：把 X 书签变成本地可检索的纯 Markdown 知识库，带命令面板 UI |
| 认证 | 复用已登录的 Chrome 会话；**不需要登录、不需要 API key、不需要粘贴 Cookie** |
| 采集机制 | **待源码验证**（未 clone）。文档口径为"无 API、全部落盘" |
| 增量 / 去重 | 支持增量；提供 `doctor.py --dedup` 去重 |
| 产物 | `.md` 文件 + `INDEX.tsv` + `kb.html` |
| Windows | 文档表述依赖已安装 Chrome，**未给出 Windows 专属验证** |
| 内容完整度 | 图片/视频：字段层面支持与可选缓存；外链：保留链接；Thread：部分（含要点提炼）；**Quote Tweet / X Article 未提及** |
| 工程成熟度 | 0 star、0 issue、创建与最后提交同为 2026-08-12（**单日项目后停更**） |
| **许可证** | **仓库无 LICENSE 文件 → 默认"保留所有权利"**，不可安全复用或二开纳入本项目 |
| 结论 | ❌ 不采用（许可风险为决定性因素）。可借鉴其"Agent Skill + 纯 stdlib + INDEX 索引"的产品形态思路 |

### 5.2 xmarks — 不可解析

- 检索结论：Xmarks 为 2014 年被 LastPass 收购、**2018 年停止服务**的浏览器书签同步工具；与 X/Twitter 书签无关联。
- GitHub 上不存在以此为名的 X 书签项目。
- 处置：本条目视为执行计划的命名错误，**以补充候选（第 6 节）替代**。

### 5.3 MarkHarbor — `dososo/markharbor`

| 项 | 结论 |
| --- | --- |
| 定位 | 本地优先的 Chrome 扩展：X Bookmarks → Obsidian 知识库包 |
| 认证 | 在已登录的 `x.com/i/bookmarks` 页面上下文内工作；**不读取密码或 Cookie** |
| 产物 | Markdown + JSON + CSV + TXT + HTML + media manifest |
| 增量 / 去重 | **文档未明确声明**（❓） |
| 媒体 | 图片下载到分类目录；**不下载视频，仅保存链接** ❌ |
| 外链 | 仅保留链接卡的标题/描述/URL；**不抓取外部正文** ❌ |
| X Article | 会尝试读取详情页以取全文与图片 |
| Windows | 扩展形态，理论跨平台；未专门声明 |
| 许可证 | MIT ✅ |
| 工程成熟度 | 4 star、7 open issues、最后提交 2026-07-19（近 2 个月无更新） |
| 结论 | ⚠️ 不作 Collector。原因是"扩展 UI + 不下载视频 + 不外抓外链"三条与本项目目标（完整归档 + 无人值守）直接冲突 |

### 5.4 TweetKB — `AdityaVG13/TweetKB`

| 项 | 结论 |
| --- | --- |
| 定位 | 本地优先的 X 书签知识库：采集 → 存 SQLite → AI 分析 → 导出 |
| 认证 | 无需 X 账号密码；从已登录浏览器读取 |
| 采集机制 | "Browser-Harness"：macOS 上用 **Apple Events** 与已开着的 Chrome 通信；`--headless` 会**复制会话文件并另起一个 Chrome**；`--normal-chrome` 可能以远程调试方式重启 Chrome |
| 存储 | SQLite（默认 `~/.local/share/tweetkb/bookmarks.sqlite3`，可用 `--db`/`TWEETKB_DB` 覆盖），**使用 FTS5 全文检索** |
| 数据模型 | `bookmarks` / `authors` / `links` / `entities` / `classifications` / `clusters` / `projects` / `exports`；结构化字段初期以 JSON 存在 `bookmarks` 表 |
| 增量 / 去重 | 按 `status_id` 去重并更新；`content_hash` 跳过未变内容的重复分析；`--all` 增量可跳过已存前缀 |
| AI | OpenAI（`OPENAI_API_KEY`）与 Ollama；embeddings 支持本地 hash 向量 |
| 导出 | 适配器 `markdown.py` / `obsidian.py` / `logseq.py` |
| 媒体 | **默认不下载**；`enrich --include-media` 做图片描述/OCR，`media-export` 可导出图片 |
| 外链 | `enrich` 会抓取链接页与可见 thread/reply 上下文 |
| 测试 | ✅ `uv run pytest` |
| Python | 3.11+ |
| 安装 | `uv tool install git+https://github.com/AdityaVG13/TweetKB.git` |
| 许可证 | MIT ✅ |
| Windows | ❌ **未声明支持**，Apple Events 路径为 macOS 专属；Windows 只能寄望 `--headless` 复制会话路径 |
| 结论 | ⚠️ 保留为**备选 Collector**。理由：架构与数据模型最接近本项目目标（SQLite + FTS5 + `status_id` 去重 + `content_hash` 幂等 + 导出适配器 + 测试），但**Windows 采集可行性必须先实测**；0 star 也意味着上游风险 |

### 5.5 XClipper — `zendegani/XClipper`

| 项 | 结论 |
| --- | --- |
| 定位 | 高保真 X/Twitter **web clipper** 扩展：抓取单条或批量，导出 Markdown/PDF/HTML/JSON/CSV/Obsidian |
| 认证 | 浏览器已登录会话；无需 API key |
| 内容完整度 | **最全**：thread、quote tweet、X Article、图片与视频本地化、外链解析 |
| 增量 / 去重 | 有 dedup ledger；支持批量 |
| Windows | 浏览器内运行，天然跨平台 ✅ |
| 工程成熟度 | 34 star、6 fork、最后提交 2026-09-13（**活跃**） |
| **许可证** | **PolyForm Noncommercial License 1.0.0 → 禁止商业用途**（商用需付费授权）❌ |
| 结论 | ❌ 不采用。功能虽最好，但（a）许可限制，（b）扩展形态无法作为无人值守 Collector。可作为"完整度基线"参考，用于校验本项目输出质量 |

### 5.6 X Bookmark to Obsidian（以 `kiki123124/x2o` 为代表）

| 项 | 结论 |
| --- | --- |
| 定位 | X 书签 → Obsidian 知识库（书签导出 + AI 分类） |
| 技术 | Tauri 桌面应用（Rust + SolidJS），19+ AI provider，全本地 |
| 产物 | Obsidian Vault 结构 |
| Windows | ⚠️ 技术栈跨平台可行，但 topics 标注 macOS，且未见 Windows 验证说明 |
| 工程成熟度 | 30 star、最后提交 **2026-03-23（停滞约 6 个月）** |
| 许可证 | MIT ✅ |
| 结论 | ❌ 不作 Collector。桌面应用形态无法无人值守；且停更风险高。其"导出 + AI 分类 + Obsidian"的成品形态可作为 Phase 11 的产物参考 |

---

## 6. 补充候选（文档未列，但更贴合本项目）

### 6.1 fieldtheory CLI — `afar1/fieldtheory-cli` ⭐ 本机已装

| 项 | 结论 |
| --- | --- |
| 定位 | "Self-custody for your X/Twitter bookmarks"：采集、检索、分类，并向 Agent 暴露本地上下文 |
| 认证 | 浏览器会话（Chrome/Chromium/Brave/Edge/Helium/Comet/Dia/Firefox）或手工 `--cookies`，或 OAuth（`--api`） |
| 采集 | GraphQL 增量抓取；`--rebuild` 全量、`--continue` 断点续传、`--gaps` 回填（被引用推文 / 被截断 Article / 引用文章正文 / 媒体缺口）、`--folders` 同步书签文件夹 |
| 媒体 | 自动下载图片/视频海报/有上限的视频，支持 `--no-media`、`--media-max-bytes`、`--skip-profile-images`、`fetch-media` 回填 |
| 增量 / 去重 | 内置 SQLite 索引 + JSONL 缓存，默认增量 |
| 产物 | `bookmarks.jsonl`（原始缓存）、`bookmarks.db`、`media-manifest.json`、`media/`、`ft md` 导出的逐条 Markdown、`ft wiki` 生成的互联知识库 |
| AI | `classify` / `classify-domains` 调 claude 或 codex CLI；`model` 可切换引擎 |
| CLI | 极完整（60+ 子命令），全部可脚本化 ✅ |
| Agent 集成 | `ft skill install` 安装 `/fieldtheory` skill 给 Claude Code / Codex ✅ |
| 工程成熟度 | **2020 star、209 fork、MIT、最后提交 2026-09-05、40 open issues**，本机已装并验证 `--version`/`--help`/`paths`/`status` 正常 |
| Windows | ✅ 官方 README 有 Windows Notes（会话同步支持 Chrome/Chromium/Brave/Edge/Firefox；Firefox 需 Node ≥ 22.5 或 `sqlite3`） |
| **实测阻塞** | 本机 Chrome **155** 的 Cookie 为 `v20`（App-Bound Encryption），而 `fieldtheory@1.3.22` 的 Windows 解密只处理 `v10`/裸 DPAPI → `fieldtheory sync` 报 `Couldn't connect to your browser session.`。此问题与"是否关闭 Chrome"无关（已实测） |
| 结论 | ✅ **选为 Collector**。理由：MIT 可商用、社区规模最大、活跃维护、CLI 完整可调度、产物（JSONL + 媒体清单）天然可作为本项目 ingest 的输入源。风险集中在 Windows 认证路径，需在 Phase 5 前用 Firefox 会话 / 手工 Cookie / OAuth 之一打通 |

### 6.2 xarchive — `sytelus/xarchive`

- JS / Chrome 扩展（Manifest V3）、88 star、MIT、最后提交 2026-09-05。
- 主打"无限量导出 + 文件夹归属"，零依赖，走 GraphQL。
- ❌ 不作 Collector：扩展形态，无法无人值守；无 CLI。

### 6.3 twitter-web-exporter — `prinsss/twitter-web-exporter`

- TS 用户脚本/扩展、**2702 star**、MIT、最后提交 2026-08-31、23 open issues。
- 老牌高星导出工具，可导出书签（突破 800 条上限）。
- ⚠️ 交互式使用为主，非自动化 Collector；可作为"导出格式"参考。

### 6.4 twitter-bookmark-archiver — `nornagon/twitter-bookmark-archiver`

- JS、140 star、**无 LICENSE**、最后提交 **2022-11-28（停滞约 4 年）**。
- 走**官方 API**（需 `TWITTER_CLIENT_ID` / `TWITTER_CLIENT_SECRET`），下载书签与媒体。
- ❌ 不采用：许可缺失 + 长期停更 + 依赖 API 凭证。

---

## 7. 结论与适配度排序

| 排名 | 方案 | 适配度 | 决定 |
| --- | --- | --- | --- |
| 1 | **fieldtheory CLI**（作 Collector） | 高 | ✅ 采用（MIT、活跃、CLI、产物可直接 ingest、本机已装验证） |
| 2 | **TweetKB**（备选 Collector / 设计参考） | 中高 | ⚠️ 仅当 Windows 采集实测通过才考虑；其 SQLite+FTS5+content_hash 设计可作为本项目数据模型的参考 |
| 3 | 自研 GraphQL Collector | 中 | 🔒 最后手段（违反"不重复造轮子"原则，仅在认证路径全部失败时启用） |
| 4 | MarkHarbor / xarchive / twitter-web-exporter | 低 | ❌ 扩展形态，无法无人值守 |
| 5 | x2o | 低 | ❌ 桌面应用 + 停更 |
| 6 | XClipper | 低（功能高但许可阻断） | ❌ 非商业许可 |
| 7 | SaveBox / twitter-bookmark-archiver | 极低 | ❌ 无许可证 |
| — | xmarks | 不适用 | 该名称无法解析 |

**关键判断**：符合"第一优先（成熟项目直接整体复用）"的项目为 **0 个**——现有项目要么是扩展/桌面形态（无法无人值守），要么数据模型/目录规范与本项目要求冲突。因此按执行计划的优先级落到 **第二优先：成熟项目作为 Collector**。

---

## 8. 未决问题与待源码验证清单

| # | 待验证项 | 验证方式 | 阻塞阶段 |
| --- | --- | --- | --- |
| 1 | `fieldtheory` 的 `bookmarks.jsonl` 字段结构与版本稳定性 | 真实跑一次 `sync` 取样本，做字段快照测试 | Phase 5 前（必需） |
| 2 | Windows 认证路径选择（Firefox / `--cookies` / OAuth） | 三者逐一实测 | Phase 5 前（必需） |
| 3 | `fieldtheory` 对 X Article、被引用推文、外链正文的实际覆盖度 | 用真实书签跑 `--gaps` 后抽样核对 | Phase 5 |
| 4 | TweetKB 在 Windows 的 `--headless` 采集是否可用 | `uv tool install` 后实跑（需先装 uv） | Phase 5 备选分支 |
| 5 | SaveBox 的采集实现（判断是否值得借鉴思路而非代码） | clone 源码阅读 | 非阻塞 |
| 6 | 各项目 Release 资产与 Issue 中的已知数据丢失类 bug | 逐仓核对 Issues/Releases | Phase 5 |
| 7 | XClipper 的完整度基线（用于产出质量对照） | 手工对照一条 Thread / Article 书签 | Phase 7 |
| 8 | `fieldtheory` 的 FTS5 使用方式与 SQLite schema | 读 `dist/bookmarks-db.js` / 取样本库 | Phase 4 参考 |

---

## 9. Phase 1 状态

**完成**。产出结论已用于 Phase 2 的架构决策（见 `research/architecture-decision.md`）。所有标注 ❓ 的项目均保留为"未能确证"，不作为支持性证据使用。



