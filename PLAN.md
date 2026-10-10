# PLAN

> 项目：X Bookmark Knowledge Pipeline
> 项目根：`/Users/nanopeng/AI-Agent-Lab/X-Bookmark-Knowledge/`（macOS）
> 最后更新：2026-10-08（跨平台改造 Phase 3 实现完毕并离线验收：RawCollectorData + FieldTheoryCollector + FieldTheoryNormalizer，133 用例绿）

> **跨平台改造说明（2026-10-07 起）**：本项目已从「Windows-only、fieldtheory 附属」重构为
> 「跨平台、Collector 可替换、Canonical Data 稳定」的分层架构。旧 Phase 0–9 的验收记录（含
> 下述状态表）为 Windows 时代历史，**已过时**，保留作存档。新的改造 Phase 顺序见
> `ARCHITECTURE.md` §15（Phase 0 审计 → 1 架构设计 → 2 Schema → 3 Collector Adapter →
> 4 Storage → 5 CLI → 6 Cross Platform → 7 Git Sync → 8 Knowledge-Agent）。

---

## 1. 当前状态（跨平台改造）

| 项 | 值 |
| --- | --- |
| 改造进度 | Phase 0 ✅ → Phase 1 ✅ → Phase 2 ✅ → Phase 3 ✅（含审计闭环） → **Phase 4（Storage）🔄 进行中（Step 1–2 完成）** |
| 当前阶段 | **Phase 3 完成（已提交 `498236a`）**：`src/collector/raw_data.py` + `src/collector/fieldtheory/` + `src/normalizer/` + 3 个测试文件（133 用例绿；含 5 个第三方审计回归用例）；5 条真实数据只读转换 5/5 通过 Schema |
| 技术路线 | Collector 可替换（Protocol + registry + 配置驱动）；CanonicalBookmark 为统一标准；SQLite 降级为可重建索引 |
| 真实数据 | 已从 Windows 包迁移到 `data/`（upstream/raw/state/logs）与 `knowledge/X-Bookmarks/`（5 篇 md + 媒体），`config/config.yaml` 就位 |
| 已知问题 | 全量测试**本机 macOS** 9 个失败（`test_config` 4 / `test_media` 3 / `test_external` 2），均为平台语义（macOS `/var`→`/private/var` 软链、盘符、机器环境变量），非代码 bug；**第三方 Linux 审计复跑为 3 失败 + 16 错误**（口径不可跨平台复现）→ Phase 6 必须重建分类基线，详见 `docs/phase3-preflight-review.md` §10.8.3 |

---

## 2. 阶段进度（跨平台改造）

| Phase | 名称 | 状态 | 产物 |
| --- | --- | --- | --- |
| 0 | 架构审计 | ✅ 完成 | `docs/CURRENT_ARCHITECTURE.md` |
| 1 | 架构设计 | ✅ 完成 | `ARCHITECTURE.md`（六层架构 + 决策 R1–R7） |
| 2 | Canonical Schema | ✅ 完成（2026-10-08） | `schema/bookmark.schema.json` + `src/canonical/validate.py` + `tests/test_schema.py`（28 用例） |
| 3 | Collector Adapter | ✅ 完成（2026-10-08，已提交 `498236a`） | `src/collector/raw_data.py` + `src/collector/fieldtheory/` + `src/normalizer/` + `tests/test_{raw_data,fieldtheory_collector,normalizer}.py`（133 用例） |
| 5 | CLI | 🔄 **起步**（决策无关部分：`normalize`/`render` dry-run 入口 + `xbk` 声明；S2/R1 待裁定） |
| 4 | Storage | ✅ **完成**（Step 1–5：JSON 投影 + Markdown 投影 + SQLite 索引 R6 + rebuild-index + 真实数据只读验收） | Markdown / JSON / SQLite 索引 + `rebuild-index` |
| 5 | CLI | ⏳ 待开始 | `xbk` 入口 + 命令对齐 |
| 6 | Cross Platform | ⏳ 待开始 | Windows + macOS 验证（修复 9 个平台断言，需先复核基线数字） |
| 7 | Git Sync | ⏳ 待开始 | Windows↔GitHub↔Mac |
| 8 | Knowledge-Agent | ⏳ 待开始 | 分类/摘要/标签/关联/问答 |

---

## 2.1 旧阶段进度（Windows 时代，已过时存档）

---

## 2. 阶段进度（旧，Windows 时代存档）

| Phase | 名称 | 状态 | 产物 |
| --- | --- | --- | --- |
| 0 | 检查现有项目环境 | ✅ 完成 | `docs/environment-report.md` |
| 1 | GitHub 开源项目技术评估 | ✅ 完成 | `research/open-source-comparison.md` |
| 2 | 确定采集策略 | ✅ 完成（用户已批准） | `research/architecture-decision.md` |
| 3 | 建立项目骨架 | ✅ 完成 | 目录结构 + `AGENTS.md` / `README.md` / `PLAN.md` / `CHANGELOG.md` / `.gitignore` / `config.example.yaml` |
| 4 | 设计数据模型（SQLite） | ✅ 完成（2026-09-15） | `.venv` + `requirements.txt` + `src/database/`（9 模块）+ `tests/test_database.py`（68 用例） |
| 5 | 实现 Collector | ✅ 完成（2026-09-16） | `src/collector/base.py` + `contract.py` + `fieldtheory_adapter.py` + `tests/test_collector_*.py`（76 用例）+ `tests/support/stub_fieldtheory.py` |
| 6 | 实现增量同步 | ✅ 完成（2026-09-16） | `src/config.py` + `src/ingest/` + `src/cli/`（sync/status/doctor）+ 60 用例；M2 达成 |
| 7 | 实现 Markdown Generator | ✅ 完成（2026-09-17） | `src/markdown/`（render + writer）+ `process` 子命令 + `tests/test_markdown.py`（23 用例）；M3 达成 |
| 8 | 媒体处理 | ✅ 完成（2026-09-20） | `src/media/`（localizer）+ `media` 子命令 + `tests/test_media.py`（44 用例）；6/6 真实媒体本地化并归一 `media.local_path` |
| 9 | 外部 URL 解析 | ✅ 实现完毕 + 复审关闭（2026-09-21；真实数据写运行待批准） | `src/external/`（含 `netguard.py`）+ `links` 子命令 + `tests/test_external.py`（94 用例） |
| 10 | 内容完整性测试（Test A–L） | ⛔ 未开始 | `tests/` + 抽样报告 |
| 11 | AI Knowledge-Agent 接入 | ⛔ 未开始 | `src/processor/` 的 AI 段 |
| 12 | 建立 Knowledge-Agent Pipeline | ⛔ 未开始 | 状态机流转 + inbox 交接 |
| 13 | 定时任务 | ⛔ 未开始 | `scripts/install-scheduler.ps1` 等 |

---

## 3. Phase 5 硬性前置条件（未满足不得开工）

| # | 条件 | 验证方式 | 状态 |
| --- | --- | --- | --- |
| A | Windows 认证路径可用 | 三选一：`fieldtheory sync --browser firefox` / `--cookies <ct0> <auth_token>` / `auth` + `--api` | ✅ 已完成（2026-09-16 实测：Firefox 156 会话路径通过；Chrome ABE v20 已排除） |
| B | 上游 JSONL 字段契约确认 | 真实跑一次采集，取得 `bookmarks.jsonl` 样本并逐字段核对 | ✅ 已完成（21 必填 + 1 可选，冻入 `src/collector/contract.py`，快照测试锁定） |
| C | 媒体清单结构确认 | 读取真实 `media-manifest.json` 样本 | ✅ 已完成（schemaVersion=1；9 顶层键 + 11 条目键；`status` 仅观测到 `downloaded`） |
| D | X Article / Quote / 外链覆盖度抽样 | 执行 `--gaps` 后抽样核对 | ✅ 已完成（`--gaps` 富化 4 篇 linked article；正文经 `list --json` 可取，不等同于 JSONL） |

---

## 4. 技术栈（已定 / 待定）

| 项 | 决定 | 状态 |
| --- | --- | --- |
| 语言 | Python | ✅ 已定 |
| 解释器 | 3.13.12（`.workbuddy/binaries/python/versions/3.13.12`，macOS） | ✅ 已定（2026-10-07 于 macOS 重建 venv） |
| 虚拟环境 | `.venv/`（项目内，已 gitignore） | ✅ 已于 2026-09-15 创建（Python 3.12.13，内部装 pip 25.x） |
| 状态存储 | SQLite（stdlib `sqlite3`） | ✅ 已定 |
| 全文检索 | SQLite FTS5 | ✅ 已于 2026-09-15 以 Python 3.12.13 / SQLite 3.53.1 实测：建表与 `MATCH` 查询可用 |
| 配置格式 | YAML（`config.yaml`），解析用 **PyYAML 6.0.3** | ✅ 已定（ADR-012，Phase 6 落地） |
| HTTP | **标准库 `urllib`**（注入式传输层，逐跳跟随重定向） | ✅ 已定（ADR-017，Phase 9） |
| HTML 正文抽取 | **标准库 `html.parser`**（skip 标签 + 块级换行归一化） | ✅ 已定（ADR-017，Phase 9） |
| SSRF 防护 | `src/external/netguard.py`（标准库 `ipaddress`；默认阻断非公网目标，重定向逐跳复核；`external.block_non_public_hosts` / `external.allow_hosts`） | ✅ 已定（Phase 9 复审，ADR-017 补充） |
| AI 引擎 | 待 Phase 11 决定（`ft classify` vs 直接调 claude/codex CLI） | 待定 |
| 调度 | Windows Task Scheduler（`schtasks`） | ✅ 已定 |
| 测试 | stdlib `unittest`（**已决定**，2026-09-15） | ✅ 已定：零第三方依赖、与"依赖最小化"一致；唯一理由是 pytest 提供更好的断言/夹具，但当前不构成必要需求 |
| 版本控制 | 仅提供 `.gitignore`，**未 `git init`** | 待用户授权 |

### 4.1 审核记录（2026-09-15）

- Phase 0--3 的文档、目录骨架与敏感信息忽略规则已核对；实现代码、数据库 schema 与自动化测试尚不存在，符合 Phase 3 的边界。
- `fieldtheory.cmd --version` 可用（1.3.22）。当前 PowerShell 策略会阻止直接执行 `fieldtheory.ps1`，后续 Adapter 应显式解析 `.cmd` 或绝对可执行路径。
- `config/config.example.yaml` 中“唯一已实现的适配器”与实际不符：Collector Adapter 仍是 Phase 5 工作项，应在实施时修正文案。
- Phase 5 的认证、真实 JSONL 字段契约、媒体 manifest 与 `--gaps` 覆盖抽样四项前置条件仍全部未满足；不得提前实现 Collector。

### 4.2 Phase 4 实施记录（2026-09-15）

授权来源：用户指令"按照 `tasks/CURRENT.md` 要求执行"。

**交付物**

| 类别 | 内容 |
| --- | --- |
| 环境 | `.venv/`（Python 3.12.13）、`requirements.txt`（当前无第三方运行时依赖） |
| 数据层 | `src/database/`：`clock.py` `states.py` `schema.py` `transaction.py` `migrations.py` `models.py` `repository.py` `connection.py` `__init__.py` |
| 测试 | `tests/test_database.py`（68 用例）+ `tests/__init__.py` |

**验收结果**

```text
.venv\Scripts\python.exe -m unittest discover -s tests -t . 
Ran 68 tests in 2.71s
OK        (exit 0；Python 3.12.13 / SQLite 3.53.1)
```

**已落实的设计决定**

1. schema 版本化：`schema_version` 表 + `Migration` 声明；`SCHEMA_VERSION = 2`（v1 书签、v2 媒体/外链/FTS5）。
2. 迁移原子性：`apply_migrations` 在单事务内执行；失败整体回滚（有专门测试）。
3. `tweet_id` 唯一约束 + CHECK 约束由 `states` 枚举自动生成，避免词表与代码脱节。
4. 状态机：`NEW → COLLECTED → PROCESSED → ENRICHED → COMPLETED`；任意非终态可入 `FAILED`，`FAILED` 可重入；`COMPLETED` 为终态；同状态为无操作；非法流转抛 `InvalidStateTransition` 且不写库。
5. 幂等 upsert：已存在记录**保留** `status`/`attempts`/`first_synced_at`/`error_message`，只更新本次提供的（非 None）内容字段与 `last_synced_at`。
6. 错误记录：`record_error` 写入 `error_message`（截断至 1000 字符）并累加 `attempts`。
7. FTS5 外部内容表 + 三个触发器，索引自动跟随插入/更新/删除。
8. 外键 `ON DELETE CASCADE`，删除书签同时清理媒体与外链。

**实施中发现并修复的缺陷**

| # | 问题 | 修复 |
| --- | --- | --- |
| 1 | `MediaRecord.download_status` / `ExternalLinkRecord.fetch_status` 的默认值 `PENDING` 会被误判为"调用方显式提供"，导致重复 upsert 把已 `DOWNLOADED` 的状态重置 | 两个字段默认改为 `None`（表示"未提供"），落库时由 `_status_value()` 回退为数据库默认 `PENDING`；补 2 条回归测试 |
| 2 | 测试文件漏导入 `parse_status`（`NameError`） | 修正导入清单 |

**Audit follow-up 完成情况**

`config/config.example.yaml` 的采集器文案已修正，并写入本轮实测结论：PowerShell 直调 `fieldtheory` 会命中被 `RemoteSigned` 拦截的 `.ps1` shim，Adapter 必须使用 `fieldtheory.cmd` 或绝对路径。

**边界确认**

- 未实现 Collector（`src/collector/` 仍只有包声明）——符合 Phase 5 闸门。
- 未创建 `config/config.yaml`、未执行 `git init`、未写 `knowledge/`、未触碰上游 `~/.fieldtheory`。
- Phase 5 四项前置条件依旧全部未满足。

**下一步**

在获得授权后，要么先打通 Phase 5 前置条件 A（Firefox 会话 / 手工 Cookie / OAuth 三选一）并采集真实样本确认字段契约，要么进入 Phase 6 中不依赖真实数据的部分（需先确认后者不被前置条件阻塞）。


---

### 4.3 Phase 5 实施记录（2026-09-16）

授权来源：用户指令"已安装 firefox 并登录 x.com" + `tasks/CURRENT.md` 路径 A（先关闸门、再实现 Collector）。

**闸门关闭过程（全部用真实数据实测）**

| 步骤 | 命令 | 结果 |
| --- | --- | --- |
| Firefox 会话可用性 | 读取 `%APPDATA%\Mozilla\Firefox\Profiles\5orlmzjh.default-release\cookies.sqlite` | `.x.com` 下 `ct0`/`auth_token` 存在，**明文存储**（Firefox 不受 Chrome ABE 影响） |
| 最小采集 | `fieldtheory.cmd sync --browser firefox --no-media --yes --max-pages 1` | exit 0，`5 new bookmarks synced` |
| 续跑翻页 | `... --continue` | 翻页至末页；`stopReason: end of bookmarks` |
| 全量重爬 | `... --rebuild --no-media --yes` | exit 0，仍为 5 条 → 该账号书签确实只有 5 条（JSONL / `stats` / `status` / `meta` 四方一致） |
| 媒体清单（闸门 C） | `fieldtheory.cmd sync --browser firefox --yes --max-pages 1` | 生成 `media-manifest.json`（6 条目）+ `media/` 6 个文件 |
| `--gaps` 抽样（闸门 D） | `fieldtheory.cmd sync --browser firefox --no-media --yes --gaps` | exit 0，`4 linked articles enriched` |

**关键发现：Article 正文不在 JSONL**

`bookmarks.jsonl` 只有 21 个原始字段；Article 正文、分类、文件夹、被引用推文存储在上游 `bookmarks.db`，**仅通过 `fieldtheory list --json` / `show --json` 暴露**。因此 Adapter 采用"JSONL 取原始记录 + `list --json` 取富化"的双源设计。

**交付物**

| 类别 | 内容 |
| --- | --- |
| 契约 | `src/collector/contract.py`：冻结 JSONL（21 必填 + `textExpandedAt` 可选）、media-manifest、meta/backfill、`list\|show --json` 富化四类契约；嵌套 `author`/`engagement`/`mediaObjects` 必填键校验；两种时间格式解析；未实测项显式标注 `UNVERIFIED` |
| 接口 | `src/collector/base.py`：`Collector` 协议、5 类错误（不可用/契约/认证/超时/执行）、`SyncRunResult`、`UpstreamArtifacts`、`MediaManifest`、`UpstreamBookmark`、`EnrichedBookmark` |
| 实现 | `src/collector/fieldtheory_adapter.py`：`sync`（`--browser/--no-media/--rebuild/--continue/--gaps/--max-pages/--target-adds/--max-minutes/--folders/--folder/--delay-ms` 全参数映射）、`read_bookmarks/read_media_manifest/read_meta/read_backfill_state`、`list_enriched/show_enriched`、`check_ready`、`upstream_version`；子进程 timeout + 瞬时重试 + 错误分类；`FT_DATA_DIR` 显式指向解析出的数据目录 |
| 测试 | `tests/test_collector_contract.py`（34 用例）+ `tests/test_collector_fieldtheory.py`（42 用例）+ `tests/support/stub_fieldtheory.py`（离线桩：正常/认证失败/瞬时失败/慢响应/噪声输出） |

**验收结果**

```text
.venv\Scripts\python.exe -m unittest discover -s tests -t .
Ran 144 tests in 11.33s
OK        (exit 0)

真实上游只读校验（不联网、不写上游）：
ALL REAL-DATA READS OK (exit 0；fieldtheory 1.3.22；5 条记录 / 6 条媒体 / 4 篇 article)
```

**实施中发现并修复的缺陷**

| # | 问题 | 修复 |
| --- | --- | --- |
| 1 | 嵌套对象只校验"已出现键的类型"，缺 `type` 的 `mediaObjects` 条目会被放过 | 新增 `AUTHOR_REQUIRED_KEYS` / `ENGAGEMENT_REQUIRED_KEYS` / `MEDIA_OBJECT_REQUIRED_KEYS` 并补齐校验 |
| 2 | `bookmarks-backfill-state.json` 的 `lastCursor` 被当作必填，媒体同步后该键消失 → 真实数据读取失败 | 改为可选（仅页数受限的运行才出现），并记录 3 个已观测 `stopReason` 值 |
| 3 | 测试文件漏导入 `UpstreamContractError` | 修正导入 |
| 4 | 离线桩未对查询类命令模拟慢响应 | `slow` 场景对所有命令生效 |

**边界确认**

- Adapter 全程只读上游；`data/state/` 仅有 `.gitkeep`；`knowledge/` 未产出；无 `config/config.yaml`；无 `git init`。
- 未实现 Phase 6 内容：`src/ingest/`、`src/cli/` 仍只有包声明。

**下一步**

Phase 6：先定 YAML 解析依赖 → `src/ingest/` 抽取 + `python -m src.cli sync` 端到端跑通（里程碑 M2）。

---

### 4.4 Phase 6 实施记录（2026-09-16）

授权来源：用户确认三项待决事项（① 书签数 5 条正确 ② 上游数据目录迁到 D 盘 ③ 确认引入 PyYAML）。

**上游数据目录迁移（ADR-011 落地）**

| 步骤 | 结果 |
| --- | --- |
| 复制 `C:\Users\gscaee\.fieldtheory\bookmarks` → `data\upstream` | 12 文件 / 374,396 字节，双侧一致 |
| 设置用户级环境变量 `FT_DATA_DIR` | 使手工调用 `fieldtheory` 也走 D 盘 |
| 实测 `fieldtheory.cmd status --json` | `bookmarksDir` / `mediaDir` / `mediaManifestPath` / `bookmarksCachePath` 全部指向 D 盘 |
| 实测 `fieldtheory.cmd sync --browser firefox --no-media --yes --continue` | exit 0，数据写入 D 盘 |
| 说明 | `FT_DATA_DIR` 同时影响 `library/md` 与 ideas 根目录；`~/.fieldtheory/library` 仍在 C:，本项目未使用 |

**交付物**

| 类别 | 内容 |
| --- | --- |
| 配置 | `src/config.py`（YAML 加载 + 强类型配置 + 路径解析 + 校验）+ PyYAML 6.0.3；`config/config.yaml`（本机真实配置，gitignore） |
| 入库 | `src/ingest/ingest.py`：`Ingestor` / `IngestStats`；幂等 upsert、原始 JSON 归档、单条失败隔离、媒体键与类型派生、外链去重 |
| CLI | `src/cli/main.py` + `__main__.py`：`sync` / `status` / `doctor`；退出码 0/1/2/3；按日日志且退出时关闭句柄 |
| 测试 | `tests/test_config.py`（21）+ `tests/test_ingest.py`（25）+ `tests/test_cli.py`（17），全部离线 |

**验收结果（M2）**

```text
.venv\Scripts\python.exe -m unittest discover -s tests -t .
Ran 204 tests in 14.74s
OK        (exit 0)

M2 断言（tests/test_cli.py::SyncCommandTests::test_second_sync_reports_new_zero）：
  第一次 sync → new : 3
  第二次 sync → new : 0 / unchanged : 3
  数据库 bookmarks 仍为 3 行，data/raw 仍为 3 个文件（未重写）
```

**幂等的三道实现**：`tweet_id UNIQUE` + 逐条状态查询 + （原始归档与后续 Markdown 的）内容哈希一致则跳过。

**实施中发现并修复的缺陷（5 项）**

| # | 问题 | 修复 |
| --- | --- | --- |
| 1 | `upsert_media` / `upsert_external_link` 的 `changed` 硬编码为 `True` → 每次同步都报"全部更新" | 改为与实际字段比较（与 `upsert_bookmark` 一致） |
| 2 | Adapter 收到命令序列时跳过分辨可执行文件 → `doctor` 把不存在的命令判为可用 | 首元素仍经 `shutil.which` 解析 |
| 3 | CLI 的日志 `FileHandler` 从不关闭 → Windows 下日志文件锁定、临时目录无法清理 | 新增 `_teardown_logging`，命令结束时关闭并摘除 |
| 4 | 仅含空白的 URL 穿透过滤 → 整条书签被误标 `FAILED` | 入库前按 `strip()` 过滤 |
| 5 | 测试夹具 `raw` 未跟随字段变化 → 幂等测试失真 | 夹具按实际字段构造 `raw` |

**事故与处置（已收尾，2026-09-17 复核）**

由于此前"环境变量优先于配置"的优先级设定，`test_cli.py` 的离线桩曾把 3 条**合成夹具记录**写进真实上游目录 `data/upstream/`。

- 根因已修复：配置优先于环境变量（ADR-013）；测试一律使用临时目录，全套测试运行前后真实 `data/` 不变
- 污染已收尾（2026-09-17 复核）：`data/upstream` 现含 **5 条真实 bookmark 记录 + 6 个媒体文件**，无 `stub-argv.txt`；真实数据从 `~/.fieldtheory/bookmarks`（C: 迁移源，未删除）恢复
- 另修复一个同族缺陷：中文 Windows 上子进程 stdout/stderr 默认 GBK/cp936，上游 CLI 输出非 GBK 字符（如 `✓`、`⠋`）时崩溃——Adapter 子进程环境注入 `PYTHONIOENCODING=utf-8`，测试桩启动时强制 stdout/stderr 为 UTF-8（ADR-014）

**下一步**

Phase 9（外部 URL 解析）：`src/external/` 统一 timeout / retry / 重定向 / 编码探测，抽取外链正文并更新 `external_links`（失败也保留原始 URL）。

---

### 4.5 Phase 8 实施记录（2026-09-20）

**目标**：把上游 `media/` 缓存本地化为知识库自有资产，修正历史遗留的旧缓存绝对路径，并让 `## media` 段落引用本地相对路径。

**交付物**

| 类别 | 内容 |
| --- | --- |
| 媒体层 | `src/media/localizer.py`：`MediaLocalizer` / `MediaSource` / `MediaUpdate` / `MediaStats`；稳定命名 `{media_key}{ext}`、SHA-256 幂等、原子复制、`dry_run` |
| 路径归一 | 源解析顺序：知识库内 `local_path` → 配置媒体目录内 `local_path` → 清单索引 `sourceUrl→localPath` → `local_path` 文件名 → `source_url` 文件名；**只取文件名到 `<upstream_data_dir>/media/` 解析，不读旧 C: 缓存** |
| 跳过规则 | `media.download=false`、上游非 `downloaded`、`download_video=false` 下的 `video`/`animated_gif`、超 `max_bytes` |
| Markdown | `render.date_parts()` 抽出；`render_markdown(..., media_files=...)`；`MarkdownWriter(..., media_lookup=...)` 换算为相对本文件的 POSIX 路径；`process` 只采纳知识库内且存在的路径 |
| CLI | 新增 `media [--tweet-id X] [--dry-run]`；流水线顺序 `sync → media → process` |
| 入库 | `ingest`：`media.local_path` 改为首次插入时写入（Phase 8 之后由媒体层接管，`sync` 不得覆盖） |
| 测试 | `tests/test_media.py`（44 用例）+ `test_ingest.py` 回归用例；离线桩按清单生成媒体文件 |

**验收结果（真实 5 条 / 6 个媒体）**

```text
media --dry-run    : attempted 6 / copied 6 / unchanged 0 / skipped 0 / failed 0
media（首次）       : copied 6 / failed 0
media（二次）       : copied 0 / unchanged 6        ← 幂等
SQLite             : 6/6 行 local_path 位于 knowledge/X-Bookmarks/{YYYY}/{MM}/assets/{tweet_id}/
                     与 data/upstream/media/ 源文件 SHA-256 逐条一致
process --overwrite: written 1 / unchanged 4       ← 只有含推文媒体的那份文件变化
process（再跑）     : written 0 / unchanged 5
Markdown ## media  : assets/1900000000000000101/cf1939a0c2c6b71d.png（不再引用远程 URL）
sync --skip-collect: media rows : 0 new, 0 updated, 6 unchanged   ← 本地路径不被回退
全量测试            : 272 用例，exit 0
```

**关键设计决定**

| # | 决定 | 理由 |
| --- | --- | --- |
| 1 | 清单里的**全部**媒体行都本地化（含 `profile_image`） | 审计要求 6 条 `media.local_path` 全部归一；`## media` 只引用推文自身媒体，头像不参与渲染 |
| 2 | 跳过**不写** `SKIPPED` 状态，只写 `error_message = "skipped: ..."` | 否则每次 `sync` 都会被清单的 `downloaded` 改回 `DOWNLOADED`，制造"每轮全部更新"假统计（Phase 6 缺陷 #1 同族） |
| 3 | 文件名用 `media_key`（`sha1(url)[:16]`）而非上游文件名 | DB 行与文件可直接互查，且不随上游命名策略漂移 |
| 4 | 保留清单索引作为源定位的兜底 | `local_path` 被改写为知识库路径后，仍能在文件被误删时重新复制 |

**实施中发现并处理的问题**

| # | 问题 | 处理 |
| --- | --- | --- |
| 1 | `sync` 会用上游旧路径覆盖 `media.local_path`，使每次同步都倒退本地化结果 | `ingest` 改为首次插入才写该字段，并加回归测试 |
| 2 | 旧缓存（C:）中同名文件仍存在 → 若按名字直接信任会读项目外文件 | 源解析只接受配置目录内的文件；测试显式覆盖"旧缓存有同名文件也不采用" |
| 3 | 跳过若写 `SKIPPED` 会与上游清单状态反复互相覆盖 | 状态保持上游原值，原因写 `error_message`（见上表决定 2） |

---

## 5. 待用户确认事项

1. 知识库终点：项目内产出 → 交接上级 `inbox/X-Bookmarks/`（替代直接写 `knowledge/`）。
2. Python 解释器固定为 3.12.13。
3. ~~是否执行 `git init`~~ → 已定（2026-09-20）：已初始化并推送到**私有**仓库 `https://github.com/dyanpeng-ops/X-Bookmark-Knowledge.git`（远程名 `X-Bookmark-Knowledge`，分支 `main`）；真实书签内容与媒体资产**不入库**（`knowledge/*` 被忽略，仅 `knowledge/X-Bookmarks/README.md` 跟踪）。
4. ~~认证路径优先级~~ → 已实测确定：**Firefox 会话为主**，手工 Cookie / OAuth 仅作备选。
5. ~~Phase 8 前：视频是否本地化~~ → 已定（2026-09-20）：`media.download_video: false` 为默认，视频/动图**不**本地化（跳过原因写入 `media.error_message`），需要时改配置一行即生效。
6. Phase 11 前：AI 引擎选型。

---

## 6. 里程碑

| 里程碑 | 内容 | 验收 |
| --- | --- | --- |
| M1（Phase 4） | 数据库 schema 落地 + 迁移机制 + 数据库测试通过 | `tests/test_database.py` 全绿 |
| M2（Phase 6） | `python -m src.cli sync` 可跑通并输出统计报告 | 连续执行两次，第二次 New=0、无重复 Markdown |
| M3（Phase 7） | 逐条 Markdown 符合 frontmatter 规范并落到 `knowledge/X-Bookmarks/YYYY/MM/` | ✅ 达成（2026-09-17）：真实 5 条全部核对；`process` 二次运行 `written: 0 / unchanged: 5` |
| Media（Phase 8） | 媒体本地化到知识库 `assets/` + `media.local_path` 归一 + Markdown 引用本地路径 | ✅ 达成（2026-09-20）：6/6 行指向知识库内且与上游副本 SHA-256 一致；`media` 二次运行 `copied: 0 / unchanged: 6`；`## media` 引用本地相对路径 |
| M4（Phase 9） | 外链正文抽取可用，失败也保留原始 URL | 部分达成（2026-09-21）：实现完毕 + 复审关闭，离线 369/369 经批准全绿；真实数据写运行待批准 |
| M5（Phase 10） | Test A–L 全部通过 | 测试报告 |
| M6（Phase 13） | 定时任务可安装/卸载/手工运行 | `schtasks /query` 可见任务 |

---

## 7. 风险登记（摘要，完整见 architecture-decision 第 8 节）

| # | 风险 | 状态 |
| --- | --- | --- |
| R1 | Windows 认证不可用 | ✅ 已解除：Chrome ABE `v20` 不可用，Firefox 会话路径实测通过（2026-09-16） |
| R2 | 上游 JSONL 字段变更 | 🟡 缓解设计中 |
| R3 | Token 过期导致定时任务静默失败 | 🟡 缓解设计中 |
| R5 | 外链抓取失败 | 🟡 设计已覆盖（保留原始 URL） |
