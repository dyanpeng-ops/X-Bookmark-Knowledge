# CURRENT_ARCHITECTURE — 当前架构审计报告

> 任务书 Phase 0 交付物。**只审计、不改代码。**
> 审计日期：2026-10-07。审计环境：macOS（代码检视 + 离线测试），真实运行环境为 Windows。
>
> 依据：《X-Bookmark-Knowledge 跨平台架构改造任务书》§29 Phase 0。
> 本文档回答任务书要求的 7 项：当前架构 / Field Theory 耦合点 / 平台相关代码 / SQLite 依赖 / 数据同步问题 / Markdown 问题 / Collector 问题。

---

## 1. 结论先行

当前项目是一个**功能完整、质量较高、但 Windows-only 且 Field Theory 深度耦合**的单平台采集管道。核心问题与任务书判断一致：

1. **Collector 未真正插件化**——虽然定义了 `Collector` Protocol，但数据模型、契约、状态库、Markdown 前端全都以 fieldtheory 的内部结构为蓝本。
2. **SQLite 被当作「唯一权威状态」**，与任务书「Markdown/JSON 为交换层、SQLite 仅为本地索引」的目标相悖。
3. **平台差异散落而非集中**——路径语义、`.cmd` shim、Firefox cookies 路径、调度器全绑定 Windows。
4. **无 Canonical Data Model / JSON Schema**——fieldtheory 的 JSONL 字段被「冻结」为 `contract.py`，实质是把上游内部格式当成了项目数据标准。

这些不是代码 bug，而是**架构定位问题**——需要重构而非打补丁。

---

## 2. 当前架构总览

现状实际的分层（与任务书目标架构对比）：

```text
X.com
  ↓  fieldtheory CLI（唯一 Collector，Windows 上运行）
data/upstream/{bookmarks.jsonl, media-manifest.json, media/**}   ← 上游只读输入
  ↓  src/collector/fieldtheory_adapter.py（Adapter，但只此一个实现）
data/state/state.db（SQLite = 本项目「唯一权威状态」）           ← ★ 与目标相悖
  ↓  src/ingest/  src/media/  src/external/  src/markdown/
knowledge/X-Bookmarks/YYYY/MM/YYYYMMDD-{tweet_id}.md + assets/**
  ↓  （Phase 12 交接，未实现）
01_Knowledge-Agent/inbox/X-Bookmarks/
```

**与任务书目标架构的差距**：

| 任务书目标层 | 现状 | 差距 |
|---|---|---|
| Collector Layer（可插拔） | `fieldtheory_adapter.py` 单实现 + `Collector` Protocol | Protocol 存在但数据契约绑死 fieldtheory |
| Normalization Layer（独立） | 混在 `collector/fieldtheory_adapter.py` 的 `_to_*()` 私有函数里 | 无独立 Normalizer，无法替换 |
| Canonical Data Layer（自有标准） | 无 | `contract.py` 冻结的是上游 JSONL 结构 |
| Storage（MD/JSON 交换 + SQLite 索引） | Markdown 有、JSON 无、SQLite 当权威 | 无 `normalized/` JSON、无 `rebuild-index` |
| Knowledge Layer | Markdown 即知识产物 | 基本达标 |
| AI Agent Layer | Phase 11 未实现 | 未开始 |

---

## 3. Field Theory 耦合点清单

按耦合强度分级。这是本次改造的核心打击面。

### 3.1 强耦合（必须解耦）

| # | 位置 | 耦合点 | 说明 |
|---|---|---|---|
| C1 | `src/collector/contract.py` | 冻结 fieldtheory 1.3.22 的 JSONL/manifest/enriched 字段契约（`JSONL_REQUIRED_KEYS` 等 21 键） | **把上游内部格式当项目标准**，任务书 §5 明确禁止 |
| C2 | `src/collector/base.py` | `UpstreamBookmark` / `EnrichedBookmark` / `MediaManifest` 字段名直接对应 fieldtheory | 无独立 `CanonicalBookmark`，字段如 `postedAt_raw`、`ingested_via`、`sort_index` 全是上游泄漏 |
| C3 | `src/database/models.py` + `schema.py` | `bookmarks` 表字段（`username`/`tweet_text`/`conversation_id`）为 fieldtheory 语义 | 状态库 schema 不是 Canonic 模型的投影 |
| C4 | `src/ingest/ingest.py` | 直接消费 `UpstreamBookmark`/`EnrichedBookmark` 入库 | 无 Normalizer 中间层 |
| C5 | `src/collector/fieldtheory_adapter.py` | `_resolve_executable` 报错信息写死 `npm install -g fieldtheory` | 替换 Collector 后信息失配 |
| C6 | `src/config.py` | `collector.executable` 默认 `fieldtheory.cmd`、`provider` 默认 `fieldtheory`、`FT_DATA_DIR` 环境变量 | 平台 + 上游双重绑定 |

### 3.2 弱耦合（可保留，但需抽象）

| # | 位置 | 说明 |
|---|---|---|
| C7 | `src/external/`（fetcher/handlers/resolver） | 外链解析与 fieldtheory 无关，设计合理，可整体复用 |
| C8 | `src/markdown/render.py` | 渲染层相对干净，但 frontmatter 键名混入了 fieldtheory 概念 |
| C9 | `src/media/localizer.py` | 依赖上游 `media-manifest.json` 的 `sourceUrl`/`localPath`，需经 Normalizer 间接化 |

---

## 4. 平台相关代码清单

### 4.1 硬编码 Windows 路径 / 语义

| # | 位置 | 具体 |
|---|---|---|
| P1 | `README.md` §5 | `D:\Users\...`、`.venv\Scripts\Activate.ps1`、`Copy-Item`、`%APPDATA%` |
| P2 | `README.md` §7 | Firefox `cookies.sqlite` 路径 `%APPDATA%\Mozilla\Firefox\Profiles\...` |
| P3 | `README.md` §11 | Windows Task Scheduler（`schtasks`） |
| P4 | `config/config.example.yaml` | `executable: fieldtheory.cmd`（`.cmd` 是纯 Windows 概念） |
| P5 | `config/config.example.yaml` | `scheduler.provider: windows-task-scheduler` |
| P6 | `PLAN.md` | 通篇 `D:\`、`%APPDATA%\uv\python\...windows-x86_64...` |

### 4.2 代码层平台隐患（跨平台会出错的点）

| # | 位置 | 隐患 | macOS 实测表现 |
|---|---|---|---|
| P7 | `src/config.py` `resolve_path` | `Path("C:/abs").is_absolute()` 在 Windows 为 True、POSIX 为 False | `test_resolve_path_helper` 失败（`C:/x/C:/abs`） |
| P8 | `src/markdown/writer.py` | 相对路径用 `os.path.relpath` 对跨盘符（`Z:/...`）无解 | `test_cross_drive_lookup_path` 失败 |
| P9 | `src/media/localizer.py` | 源路径解析假设 `media/` 子目录相对上游目录 | `test_stale_absolute_path` 失败 |
| P10 | 测试套件 | 断言硬编码 `/var`（非软链）、盘符语义 | macOS 上 369 跑 / 11 平台相关失败 |
| P11 | `fieldtheory_adapter.py` | `env.setdefault("PYTHONIOENCODING")` 注释针对「中文 Windows cp936」 | 功能 OK，但属平台特判 |

**关键事实**：`src/config.py` 已用 `pathlib` 且无硬编码盘符（代码层基本干净），平台绑定主要发生在**配置默认值、README 文档、测试断言**三个层面，而非核心逻辑。这意味着平台改造的代码改动量可控。

---

## 5. SQLite 依赖问题

### 5.1 现状

- `src/database/` 是**唯一权威状态**（`PLAN.md` §1 原文：「SQLite = single source of truth」；`ARCHITECTURE.md` 约束 3：「this project's SQLite is the only authority」）。
- schema v2 含 `bookmarks`/`media`/`external_links` + FTS5。
- 无 `normalized/` JSON 层、无 `rebuild-index` 命令。

### 5.2 与任务书的冲突

| 任务书要求 | 现状 | 差距 |
|---|---|---|
| SQLite 仅为「本地索引/缓存」 | 唯一权威状态 | 需降级 |
| 删除 SQLite 后 Markdown+JSON 可重建 | 无法重建（原始数据在 `data/raw/*.json` 是 fieldtheory 格式，非 canonical；Markdown 不含全部字段） | 需补 `normalized/*.json` + `rebuild-index` |
| SQLite 不作为跨设备同步主数据源 | 无跨设备方案，但 SQLite 确实被当权威 | 需重新定位 |

**注意**：现有 `data/raw/{tweet_id}.json` 存的是**上游原始 JSON**（fieldtheory 格式），不是 canonical JSON，不能直接充当交换层。

---

## 6. 数据同步问题

- **无跨设备同步设计**。当前只有 Git 托管代码；`knowledge/*` 被 `.gitignore` 忽略（真实书签内容不入库）。
- **SQLite 不入库**（`*.db`、`data/` 被忽略），意味着 Windows 与 Mac 之间**没有任何数据层同步**——知识内容无法在两机间迁移。
- 任务书 §16 要求的「Canonical Data → Git Sync → Local SQLite Index」链路**完全缺失**。
- `.gitignore` 需重新设计：应同步 `normalized/*.json` + 清理后的 Markdown，继续排除 cookies/token/`.db`/`data/raw`（上游原始）/临时文件。

---

## 7. Markdown 问题

### 7.1 现状（Phase 7/8 已实现，质量尚可）

- 路径 `knowledge/X-Bookmarks/YYYY/MM/YYYYMMDD-{tweet_id}.md`（按发帖日期分组）。
- frontmatter 13 键：`tweet_id / url / author_handle / author_name / created_at / language / media_count / link_count / engagement / tags / primary_category / folder_names / source`。
- 8 段落：`tweet / thread / media / article / external_links / metadata / ai_analysis / source`。
- 幂等：内容哈希一致跳过、拒绝覆盖。

### 7.2 与任务书的差距

| 任务书要求 | 现状 | 差距 |
|---|---|---|
| frontmatter 含 `collector`、`collected_at`、`content_hash` | 无 `collector`/`content_hash`；`collected_at` 语义被 `synced_at` 替代 | 需补字段 |
| `source` 记录 collector 来源 | 有 `source`（值为 `graphql`）| 与任务书 `source: "x"` 语义不同，需对齐 |
| 每条 Tweet 独立文件 | 已满足 | ✅ |
| 文件名 `{tweet_id}.md`（任务书 §8.1） | 现为 `YYYYMMDD-{tweet_id}.md` | 命名规则需决策 |

### 7.3 潜在冲突需决策

任务书 §8.1 建议 `knowledge/X-Bookmarks/123456789.md`（纯 tweet_id），但现有布局是 `YYYY/MM/YYYYMMDD-{tweet_id}.md`。二者冲突，需在 Phase 1 架构设计中明确取舍（我倾向保留现有按日期分组，理由见 Phase 1）。

---

## 8. Collector 问题

### 8.1 现状

- `src/collector/base.py` 定义了 `Collector` Protocol（`check_ready`/`sync`/`read_bookmarks`），方向正确。
- 但 Protocol 的返回类型是 `UpstreamArtifacts`/`Sequence[UpstreamBookmark]`——**返回的是 fieldtheory 形状，不是 Canonical 形状**，所以「可插拔」只停留在签名层面。
- 只有一个实现 `FieldTheoryAdapter`，且 `contract.py` 冻结了 fieldtheory 的具体字段。

### 8.2 改造方向（任务书 §4/§5/§7）

1. `Collector` Protocol 应返回 **Canonical 形状**，或返回「原始 + collector 标识」，由独立 Normalizer 转 Canonical。
2. 新增 `schema/bookmark.schema.json` 定义 `CanonicalBookmark`。
3. `contract.py` 降级为 `FieldTheoryAdapter` **内部**的字段校验，不再作为项目级数据标准。

---

## 9. 现状资产盘点（可复用部分）

以下模块与 fieldtheory 解耦良好，重构时应**保留并复用**：

| 模块 | 评估 |
|---|---|
| `src/database/`（schema/迁移/事务/状态机/FTS5） | 质量高，但需按 Canonical 模型重新投影表字段 |
| `src/external/`（fetcher/netguard/handlers/resolver） | 完全独立，零改造 |
| `src/markdown/render.py` + `writer.py` | 渲染逻辑可复用，frontmatter 需对齐 Canonical |
| `src/media/localizer.py` | 逻辑可复用，输入需经 Normalizer 间接化 |
| `src/cli/`（编排层） | 结构可复用，命令名需对齐 `xbk` |
| 测试套件（369 用例） | 高价值，需按新架构重写契约部分 |

---

## 10. 平台改造的代码改动量评估

**结论：核心逻辑层基本干净（已用 pathlib、无硬编码盘符），平台绑定集中在 3 个外围层。**

| 层 | 改动量 | 说明 |
|---|---|---|
| 核心逻辑（collector/ingest/media/markdown/external/database） | 小 | 已用 pathlib；主要风险是 `is_absolute`/`relpath` 的盘符语义 |
| 配置默认值 | 中 | `fieldtheory.cmd`、`FT_DATA_DIR`、`windows-task-scheduler` 需抽象 |
| 文档（README/PLAN） | 大 | 通篇 Windows 命令需改为跨平台说明 |
| 测试断言 | 中 | 11 个平台相关用例需跨平台化（用 `os.path` 抽象） |

---

## 11. 与任务书逐条对照的执行清单

Phase 0 的产出即本文档。后续阶段按任务书 §29 顺序执行：

| Phase | 任务书要求 | 对应现状 | 状态 |
|---|---|---|---|
| 0 当前项目审计 | 输出 `CURRENT_ARCHITECTURE.md` | **本文档** | ✅ 完成 |
| 1 新架构设计 | 输出 `ARCHITECTURE.md`（重写现有） | 待做 | ⏳ |
| 2 Schema | `schema/bookmark.schema.json` + 测试 | 无 | ⏳ |
| 3 Collector Adapter | `FieldTheoryAdapter → CanonicalBookmark` | 部分（缺 Normalizer） | ⏳ |
| 4 Storage | Markdown/JSON/SQLite Index + rebuild | 无 JSON、无 rebuild | ⏳ |
| 5 CLI | `xbk sync/status/search/rebuild-index/verify/doctor` | 现为 `python -m src.cli ...` | ⏳ |
| 6 Cross Platform | Windows + macOS 验证 | Windows-only | ⏳ |
| 7 Git Sync | Windows↔GitHub↔Mac | 无数据层同步 | ⏳ |
| 8 Knowledge-Agent | 分类/摘要/标签/关联/问答 | Phase 11 未做 | ⏳ |

---

## 12. 关键风险与决策点（进入 Phase 1 前必须明确）

1. **Markdown 布局取舍**：任务书 §8.1 建议 `{tweet_id}.md` 平铺，现有为 `YYYY/MM/YYYYMMDD-{tweet_id}.md`。需决策保留哪种（或两者兼容）。
2. **Canonical 模型字段冻结**：`CanonicalBookmark` 需覆盖任务书 §6 全部字段（含 `quoted_tweet`/`reply_to`/`thread`/`x_article`/`content_hash` 等），并决定哪些来自 JSONL、哪些来自 `list --json` 富化、哪些来自后续处理。
3. **旧数据迁移**：现有 `data/raw/*.json`（fieldtheory 格式）与 `data/state/state.db` 如何迁移到新的 Canonical + `normalized/` 布局，需迁移方案（任务书 §32：问题/原因/方案/影响/迁移方式）。
4. **CLI 命令名**：任务书 §20 用 `xbk`，现用 `python -m src.cli`。是否引入 `xbk` 入口（需打包/entry point），还是保留模块调用。
5. **状态机扩展**：任务书 §18 要求 `NEW→COLLECTED→NORMALIZED→STORED→PROCESSED→ENRICHED→FAILED`（7 态），现有为 6 态（无 `NORMALIZED`/`STORED`）。需扩展 `src/database/states.py` 并迁移。

---

## 附录 A：审计方法

- 只读检查：`git status/log`、`find`、读取 `PLAN.md`/`CHANGELOG.md`/`README.md`/`ARCHITECTURE.md`/`AGENTS.md`/`tasks/CURRENT.md`。
- 通读核心源码：`src/collector/`（base/contract/fieldtheory_adapter）、`src/config.py`、`src/database/`（schema/models）、`src/ingest/`、`src/markdown/`、`src/media/`、`src/external/`、`src/cli/`。
- 离线测试：`.venv/bin/python -m unittest discover -s tests -t .` → 369 跑 / 11 平台相关失败（详见 §4.2 表格）。
- 未做任何代码修改、未联网、未写真实数据。
