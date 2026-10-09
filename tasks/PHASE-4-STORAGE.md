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
| S2 | **Markdown 投影**：路径 `{YYYY}/{MM}/{YYYYMMDD}-{tweet_id}.md`、frontmatter 14 键、正文两段式、不覆盖内容不同的既有文件 | 新增测试 + 既有 markdown 测试不回归 |
| S3 | **SQLite 索引**：表结构按 R6 两类划分；写入/更新幂等 | 新增测试 |
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
