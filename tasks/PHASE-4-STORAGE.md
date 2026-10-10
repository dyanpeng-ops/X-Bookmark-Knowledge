# Phase 4 — Storage 实施任务书

> 项目：X-Bookmark Knowledge Pipeline（跨平台改造）
> 当前阶段：Phase 4 — Storage（L3 三种投影落地）
> 依据：`ARCHITECTURE.md` §6（Storage 设计）/ §7（frontmatter）/ §13（目录结构）/ §14（改造映射）
> 日期：2026-10-09
> 状态：**实施中**

---

## 1. 目标

把 CanonicalBookmark 落成**三种地位对等的投影**，并使 SQLite 降级为**可重建的本地索引**：

```text
CanonicalBookmark（L3，内存 dict，已由 Phase 3 Normalizer 产出）
      ├─→ Markdown   knowledge/X-Bookmarks/{YYYY}/{MM}/{YYYYMMDD}-{tweet_id}.md   （长期可读，入 Git）
      ├─→ JSON       data/normalized/{tweet_id}.json                              （标准交换，入 Git）
      └─→ SQLite     data/state/state.db                                          （本地索引，不入 Git，可重建）
```

Phase 4 完成后：**删除 `data/state/state.db` 能由 `rebuild-index` 从 normalized/*.json 重建内容索引**。

## 2. 严格边界（不得越界）

**不实现**：Collector 改造、Normalizer 逻辑变更、CLI 新命令体系（除 `rebuild-index` 所需最小接线）、
Knowledge-Agent、AI 分类/摘要/标签、Embedding/RAG、外链抓取、新 Scheduler、跨平台完整适配。

**不得**：
- 修改 `schema/bookmark.schema.json`（契约已冻结）
- 修改 `src/normalizer/`、`src/collector/` 的既有行为（只消费其输出）
- 写入真实 `data/`、`knowledge/`（测试一律用临时目录；对真实数据运行需另行批准）

## 3. 交付物

| # | 交付物 | 位置 | 说明 |
|---|---|---|---|
| D1 | Canonical JSON 投影 | `src/storage/json_projection.py` | `data/normalized/{tweet_id}.json`，原子写 + 内容哈希幂等 |
| D2 | Markdown 投影 | `src/markdown/`（对齐 Canonical） | 路径按 §6.1；frontmatter 补 `collector`/`collected_at`/`content_hash`；正文分 `## Original Tweet` / `## AI Analysis` |
| D3 | SQLite 索引 | `src/database/` | 按 ARCHITECTURE §6.3.1 的 **R6 两类字段**（内容索引可重建 / 运行态重建即重置） |
| D4 | `rebuild-index` | `src/storage/rebuild.py` + CLI 接线 | 扫描 `normalized/*.json` 重建内容索引；运行态重置语义写入帮助文本 |
| D5 | 测试 | `tests/test_storage_*.py` 等 | 离线、临时目录、零第三方依赖 |

## 4. 实施步骤

| Step | 内容 | 验收 |
|---|---|---|
| S1 | **JSON 投影**：路径布局、原子写（临时文件+替换）、内容未变跳过、非法 Canonical 拒绝 | `tests/test_storage_json.py` 全绿 |
| S2 ✅ | **Markdown 投影**：路径 `{YYYY}/{MM}/{YYYYMMDD}-{tweet_id}.md`、frontmatter 14 键、正文两段式、不覆盖内容不同的既有文件 | ✅ 已交付：`src/storage/markdown_projection.py` + `tests/test_storage_markdown.py`（30 用例）；全量零回归 |
| S3 ✅ | **SQLite 索引**：表结构按 R6 两类划分；写入/更新幂等 | ✅ 已交付：新增 19 用例 + 既有 database 层 70/70 不回归 |
| S4 | **rebuild-index**：删库重建；运行态重置 | 新增测试（含「删库→重建→内容索引一致」） |
| S5 | 全量回归 + 真实数据**只读 dry-run** 验收（需另行批准） | 报告 |

## 5. 验收标准

- A. Canonical JSON 与 `schema/bookmark.schema.json` 字段一一对应，可通过 `validate_bookmark`
- B. `data/normalized/{tweet_id}.json` 幂等：内容未变时**不重写**（mtime/内容哈希不变）
- C. Markdown 路径与 frontmatter 符合 ARCHITECTURE §6.1/§7
- D. 既有知识库文件**不被覆盖**（内容不同即拒绝写，或按既定策略处理）
- E. 删除 SQLite 后 `rebuild-index` 可重建**内容索引**；运行态明确重置并文档化
- F. 单条失败不中断批次（AGENTS §2.7）
- G. 全部离线测试可跑；无新增第三方依赖
- H. 不触碰真实 `data/`、`knowledge/`（测试用临时目录）

## 6. 风险与待决策

| # | 事项 | 处置 |
|---|---|---|
| R1 | 现有 `src/ingest/`、`src/markdown/`、`src/database/` 是 Windows 时代实现（消费 UpstreamBookmark/raw JSON），与本 Phase 目标不同 | ARCHITECTURE §14 定义为「移 + 改」。**待用户决策：新建 `src/storage/` 与既有模块并存（增量、不破坏 500+ 既有测试）还是原地替换（更干净但会大面积破坏既有测试）** |
| R2 | 既有 9 个平台语义测试失败构成噪声，容易掩盖真实回归 | 每步用「失败集快照比对」而非「失败数」判定回归（Phase 6 重建基线） |
| R3 | Markdown 覆盖策略（D4）涉及既有知识库文件安全 | 采用「内容不同则不覆盖」；如需覆盖须显式 `--force`，且在报告中标注 |

## 7. 与 S2 的关系（澄清）

第三方审计 S2（`FieldTheoryCollector` 未形式化满足 `Collector` Protocol）**不阻塞本 Phase**：
Phase 4 消费的是 **CanonicalBookmark dict**，与 Collector 的接口形状无关。
S2 的决策时点应放在 **Phase 5（CLI）** 之前——CLI 才会按 Protocol 装配各 Collector。

---

*本任务书由开发方依 `ARCHITECTURE.md` 生成；不属于架构决策，凡涉及架构取舍之处均标注为「待用户决策」。*

---

## 8. 实施状态（滚动更新）

| Step | 状态 | 证据 |
|---|---|---|
| S1 JSON 投影 | ✅ 已完成 | `src/storage/json_projection.py`；30 用例（含审计 F-001/F-004 回归）；Muse 第 2 轮复审 **PASS**（`RUN-20261009T134544Z-r5r2`）|
| S2 Markdown 投影 | ✅ 已完成 | `src/storage/markdown_projection.py`；`tests/test_storage_markdown.py` **30 用例**；变异测试 2/2 被捕获；全量 **592 用例**失败集 md5 未变（零回归）|
| S3 SQLite 索引（R6 两类字段） | ✅ 已完成 | `src/database/r6_fields.py` + `index_store.py` + `schema.py`（migration 3）；`tests/test_database_r6.py` **19 用例**；全量失败集与基线一致（零回归）|
| S4 `rebuild-index` | ⏳ 待开工 | — |
| S5 全量验收 + 真实数据 dry-run | ⏳ 待批准 | — |

### S2 实现要点

- 路径布局**复用** `src.markdown.render.date_parts`，保证与 Phase 8 的 `assets/` 布局永不漂移；
- frontmatter 以 **Canonical 契约（决策 D2/D5）为准**：`author` = 显示名、`author_username` = handle；
  `ARCHITECTURE.md` §7 示例中的 `author: "username"` 属 D2 明确之前的旧写法，本实现按 D2 处理；
- 正文两段式：`## Original Tweet`（可恢复原文）+ `## AI Analysis`（**仅占位说明，绝不编造分析**）；
- **不覆盖内容不同的既有文件**（验收 D）：内容相同跳过、内容不同抛 `MarkdownConflict` 并保持原文件不变，
  仅显式 `overwrite=True` 才改写；
- 批量入口逐条隔离冲突与错误（AGENTS §2.7），冲突数在报告中单列。

### 与 ARCHITECTURE §7 的两处差异（需记录，未自行扩张）

1. **`tags` / `categories`**：§7 目标 frontmatter 含这两键，但 CanonicalBookmark **没有**这两个字段
   （它们在 Field Theory 侧）。本实现**不写**这两键，避免凭空断言"无标签"。
2. **`engagement` / `primary_category` / `folder_names`**：§7 称"保留为扩展键"，但 Canonical 同样没有，
   且 Phase 4 不得依赖 FT 侧数据 → 无法生成，记录为 gap。

### S3 实现要点（R6 落地）

- **字段二分成为可执行契约**：`src/database/r6_fields.py` 是「内容索引 / 运行态 / 结构列」分类的唯一真实来源，
  `assert_classification_complete()` 双向校验 DDL 与归类——**新增列忘记归类会直接报错**（防止 R6 语义悄悄失效）。
- **补上 `content_hash`**：`MIGRATION_3` 给 `bookmarks` 加列 + 索引。原表**根本没有**这个列，
  而 R6 的幂等判断（内容未变即跳过）与内容索引全都依赖它；旧行为 NULL，Phase 4 写入一律填充
  （NULL 视为"内容已变"，会被修正）。
- **幂等写入**（`IndexStore.upsert_content_index`）：
  - 同 `content_hash` → `unchanged`，**一个字节都不写**（不写盘、不动时间戳、不触发 FTS）；
  - 变化 → `updated`，**只更新内容索引列**；
  - 接口层拒绝运行态键（传 `status=`/`attempts=` 直接 `ValueError`），把 R6 边界变成接口约束。
- **运行态重置**（`IndexStore.rebuild_runtime_state`）：三张表的运行态列重置为初始态
  （`status='NEW'` / `attempts=0` / `error_message=NULL` / `download_status|fetch_status='PENDING'` /
  时间戳=重建时刻），**内容索引列原样保留**。
- **重建等价已验证**：删库 → 只扫内容重建 → 内容索引逐列与重建前一致，运行态为初始态。

### S3 顺带修正的两处脆弱测试（既有）

migration 3 让两个**硬编码 schema 版本**的断言暴露出来，已改为引用 `SCHEMA_VERSION` / `MIGRATIONS`：
`tests/test_database.py::test_upgrades_legacy_v1_database_to_latest`（`[2]`）、
`tests/test_cli.py::test_status_json_reports_database_and_upstream`（`current_version == 2`）。
