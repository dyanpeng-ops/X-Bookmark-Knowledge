# Current State Board — X Bookmark Knowledge Pipeline（跨平台改造）

> 本文件是「当前状态板」，只放进度总览 + 当前 Phase 指针 + 下一步。
> 每个 Phase 的详细任务书独立成文件：`tasks/PHASE-N-NAME.md`。

## 进度总览

| Phase | 名称 | 状态 | 任务书 |
| --- | --- | --- | --- |
| 0 | 架构审计 | ✅ 完成 | — |
| 1 | 架构设计 | ✅ 完成 | — |
| 2 | Canonical Schema | ✅ 完成（28 用例绿，已提交 `498236a`） | — |
| **3** | **Collector Adapter** | ✅ **实现完毕、已离线验收、已提交 `498236a`** | `PHASE-3-COLLECTOR-ADAPTER.md` |
| **4** | **Storage** | 🔄 **进行中（Step 1–2/5 完成）** | `PHASE-4-STORAGE.md` |
| 5 | CLI | ⏳ 待开始 | `PHASE-5-CLI.md` |
| 6 | Cross Platform | ⏳ 待开始 | `PHASE-6-CROSS-PLATFORM.md` |
| 7 | Git Sync | ⏳ 待开始 | `PHASE-7-GIT-SYNC.md` |
| 8 | Knowledge-Agent | ⏳ 待开始 | `PHASE-8-KNOWLEDGE-AGENT.md` |

## 当前 Phase 3 — Collector Adapter（实现完毕、已离线验收）

- **任务书**：`tasks/PHASE-3-COLLECTOR-ADAPTER.md`（33 节，含验收标准 A–J）
- **目标**：建立 `Collector → RawCollectorData → CanonicalBookmark` 解耦链路，让 Field Theory 只是 Collector 实现。
- **交付物**：
  - 新增 `src/collector/raw_data.py`（冻结契约 + `RawDataContractError`）
  - 新增 `src/collector/fieldtheory/{__init__,adapter}.py`（`FieldTheoryCollector`）
  - 新增 `src/normalizer/{__init__,errors,fieldtheory}.py`（`FieldTheoryNormalizer` + `compute_content_hash`）
  - 新增 `tests/test_raw_data.py`（21）、`tests/test_fieldtheory_collector.py`（23）、`tests/test_normalizer.py`（89）
  - 修改 `src/collector/base.py`（`Collector` Protocol 增 `collect()`，+12 行）
  - 文档：`docs/phase3-preflight-review.md` 追加「决策与修正记录」；`PLAN.md` / `CHANGELOG.md` 同步
- **五项决策**（见 `docs/phase3-preflight-review.md` §10.1）：dict 输出 / content_hash 按 §5.4 九项 /
  新建 `fieldtheory/` 包且旧 adapter 不动 / 富化取 `data/raw/` / 时间戳取 `syncedAt`。
- **验收证据**（2026-10-08，全部离线）：
  - 新模块 `python -m unittest tests.test_raw_data tests.test_fieldtheory_collector tests.test_normalizer` → **133 用例全绿**
  - 全量 `python -m unittest discover -s tests -t .` → 524 用例、**9 失败**（全在 `test_config`/`test_media`/`test_external` 的 Windows 路径语义，归 Phase 6）
  - 真实数据只读验收：`data/upstream` + `data/raw` → 5/5 `RawBookmarkItem` → 5/5 `CanonicalBookmark` → Schema 全通过（4 篇 Article、1 媒体、1 外链去重后）
  - 未写 `data/`、`knowledge/`、`schema/`、`config/`；未联网
  - 提交前独立审核：4/4 变异测试被捕获、AST 依赖边界断言、`schema` 键集合与输出完全一致（见 `docs/phase3-preflight-review.md` §10.7）

## 当前 Phase 4 — Storage（进行中，Step 1–2 完成）

- **Step 2 已完成**：`src/storage/markdown_projection.py` —— Markdown 投影
  （`knowledge/X-Bookmarks/{YYYY}/{MM}/{YYYYMMDD}-{tweet_id}.md`）
  - 布局复用 `src.markdown.render.date_parts`（与 Phase 8 assets 永不分叉）
  - frontmatter 14 键（按 Canonical D2：author=显示名 / author_username=handle）
  - 正文 `## Original Tweet` + `## AI Analysis`（仅占位，不编造分析）
  - **不覆盖内容不同的既有文件**（冲突抛 `MarkdownConflict`，显式 overwrite 才改写）
  - 测试 `tests/test_storage_markdown.py` **30 用例**；变异测试 2/2 捕获；全量 592 用例失败集 md5 未变
  - 与 ARCHITECTURE §7 的差异：不写 `tags`/`categories`（Canonical 无此字段），`engagement` 等同样记 gap
- **Step 3 已完成**（R6 字段二分）：
  - `src/database/r6_fields.py`：内容索引 / 运行态 / 结构列分类（唯一真实来源）+ 完整性护栏
  - `src/database/schema.py`：`MIGRATION_3` 补 `bookmarks.content_hash` + 索引（**原表没有这一列**）
  - `src/database/index_store.py`：幂等写入（同 hash 不写盘；只改内容列）+ 运行态重置
  - `tests/test_database_r6.py` **19 用例**；既有 database 层 70/70；全量失败集与基线一致
- **Step 4 已完成**（`rebuild-index`，D4 + R6）：
  - `src/storage/rebuild.py`：扫描 `data/normalized/*.json` 重建内容索引；两种模式
    （整库重建 ⇒ 运行态回初始态；`--in-place` ⇒ 幂等刷新且**保留运行态**）
  - CLI `rebuild-index`：默认**只演练**，须 `--apply` 才落盘；旧库自动备份 `state.db.bak-<UTC>`
  - **重置语义写进 `--help`**（D4 要求）；`tests/test_storage_rebuild.py` **22 用例**
  - 含任务书指定用例：**删库 → 重建 → 内容索引逐条一致**
- **Step 5 已完成**（只读 dry-run 验收 10/10）：
  5 条真实书签 → Canonical 校验 → JSON/Markdown 投影 → `rebuild-index` 建索引；
  三处 tweet_id 集合一致、content_hash 逐条一致、二次写入 **0 写**、
  整库重建后运行态回初始态、真实 `data/`+`knowledge/` 指纹**前后未变**（只读证明）。
- **Phase 4 五个 Step 全部交付** → 完成报告：`docs/X-Bookmark-Knowledge-Phase4-Report-2026-10-10.md`
- **Phase 5 已起步（决策无关部分，2026-10-10）**：
  - `normalize`（上游 → Canonical JSON）与 `render`（Canonical → Markdown）两个子命令，**均默认只演练**；
  - `pyproject.toml` 声明 `xbk` 入口（需 `pip install -e .` 生效，未执行安装）；
  - `tests/test_cli_canonical.py` 12 用例；全量 647 用例零回归。
- **Phase 5 其余部分仍待裁定**：S2（Collector Protocol 拆分）与 R1（新旧模块关系）——
  选项与影响见 `X-Bookmark-Knowledge-Automation/docs/PHASE5-PREP-BRIEF.md`

- **任务书**：`tasks/PHASE-4-STORAGE.md`（本轮新建；含 5 个 Step 与验收 A–H）
- **Step 1 已完成**：`src/storage/json_projection.py` —— Canonical JSON 投影
  （`data/normalized/{tweet_id}.json`）；原子写 + content_hash 幂等 + 路径穿越防护 + 单条失败隔离
  - 测试：`tests/test_storage_json.py` **24 用例全绿**；变异测试 2/2 被捕获
  - 端到端：5 条真实数据（只读）→ 规范化 → 临时目录落盘 **5/5**；二次运行 **0 写 / 5 跳过**（幂等实证）
- **Step 2–5 待续**：Markdown 投影 → SQLite 索引（R6 两类字段）→ `rebuild-index` → 全量验收
- **待用户决策 R1**：新建 `src/storage/` 与既有 `src/ingest`/`src/markdown`/`src/database`
  **并存**（增量、不破坏 500+ 既有测试）还是**原地替换**（更干净但大面积破坏既有测试）

## 关键状态

- **真实数据已就位**（2026-10-08 从 Windows 包迁移）：`data/upstream/`（5 条 + 6 媒体）、`data/raw/`、`config/config.yaml`、`knowledge/X-Bookmarks/`（5 篇 md + 资产）。
- **已知问题**：全量测试本机 macOS 9 失败（平台语义，非代码 bug）；第三方 Linux 审计复跑为 3 失败 + 16 错误 → **基线口径不可跨平台复现**，Phase 6 必须重建分类基线（见 `docs/phase3-preflight-review.md` §10.8.3）。
- **提交状态**：Phase 2 + Phase 3 交付物已提交并推送 `origin/main`（`498236a`）。
- **Phase 3 已完成第三方审计回应**（2026-10-09）：A1（非 UTF-8 快照拖垮整批，违反 AGENTS §2.7）+ A2/A3/A4/A5 已修复并补 5 个回归用例；S2（Protocol 债务）留待 Phase 4 前架构决策（见 `docs/phase3-preflight-review.md` §10.8）。
- **Phase 3 遗留 gap**（记录，不在本 Phase 修改）：`engagement` 无 Canonical 字段（留 payload）；
  `reply_to`/`thread` 无数据源（恒 `null`）；`quotedTweet` 形状待验证（真实样本均为 `null`）；
  `video`/`animated_gif` 未实测；非绝对 URI 外链被丢弃；`Collector` Protocol 仍含写上游的 `sync()`。

## 下一步（等老板指令）

1. ~~复核 Phase 3 交付物 → 提交~~：已完成（独立审核 + 提交 + 推送 `origin/main`）。
2. 若进入 Phase 4（Storage）：先出「待验证清单」与实现计划，获批准后再动代码。
3. Phase 6 启动前复核全量测试失败基线（9 vs 记录 11）。

## 硬约束（沿用 AGENTS.md）

- 验证分级授权：运行测试 / 联网 / 写盘，必须先列「待验证清单」交老板批准。
- 每 Phase 实现完成后先停下，未获批准不得自行验证。
- 数据与知识分离；敏感信息不进 Git/日志/Markdown。
