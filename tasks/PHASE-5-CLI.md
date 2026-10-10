# Phase 5 任务书 — CLI

> 目的：给 Phase 5 一个**明确的任务边界**，使每个审计包都能附上 `TASK.md`（协议 §2 第 1 项）。
> 本文件只定义范围与验收，**不裁定**架构决策（那些见文末"待裁定"）。

## 1. 目标

把 Phase 4 的 Canonical 投影（JSON / Markdown / SQLite / rebuild-index）与既有采集链路，
收拢为**一致的 CLI 入口**，并引入 `xbk` 命令（`ARCHITECTURE.md` §10 决策 D4）。

## 2. 范围

### 2.1 已交付（决策无关部分）

| 命令 | 行为 | 默认 |
|---|---|---|
| `normalize` | 上游 `bookmarks.jsonl`(+`data/raw/` 富化) → Canonical 校验 → `data/normalized/{tweet_id}.json` | **只演练**（`--apply` 落盘）|
| `render` | `data/normalized/*.json` → `knowledge/X-Bookmarks/{YYYY}/{MM}/{YYYYMMDD}-{tweet_id}.md`；**内容不同不覆盖**（AGENTS §14）| **只演练**（`--apply` 落盘；`--overwrite` 才改写）|
| `rebuild-index` | `normalized/*.json` → SQLite 内容索引；**运行态重建即重置**（R6）| **只演练**（`--apply` 落盘）|
| `status` | 只读展示：配置/库/上游 + **`canonical` 段**（normalized 目录与计数）| 只读 |
| `doctor` | 环境自检 + **`canonical normalized`** 非关键检查项 | 只读 |

### 2.2 待裁定后才能做

| 事项 | 依赖决策 |
|---|---|
| 按 `Collector` Protocol 装配 Collector | **S2**（Protocol 缺口：`FieldTheoryCollector` 缺 `sync`/`read_bookmarks`）|
| 旧 `process`/`media`/`links` 与 Canonical 流水线的最终关系（是否收口、何时收口）| **R1**（新旧模块并存 / 原地替换 / 并存+收口时点）|

## 3. 验收标准

| # | 判据 |
|---|---|
| A1 | 写真实 `data/`、`knowledge/` 的命令**默认都是演练**；演练模式不创建、不修改任何文件 |
| A2 | `render` **绝不覆盖内容不同的既有 Markdown**（除非显式 `--overwrite`）；冲突须计入报告并以非零退出码体现 |
| A3 | `rebuild-index` 的「运行态重建即重置」语义写入 `--help`（R6 要求），并提供 `--in-place` 保留运行态 |
| A4 | 单条失败不拖垮整批（AGENTS §2.7）：坏 JSON / 非法 Canonical 记入 failures 并继续 |
| A5 | 零回归：全量失败集与改动前**逐条一致**（判据见 `X-Bookmark-Knowledge-Automation/docs/EVIDENCE-CONVENTIONS.md`）|
| A6 | 不触碰真实 `data/`、`knowledge/`（除显式 `--apply`）|
| A7 | `xbk` 入口在 `pyproject.toml` 声明；**未执行 `pip install -e .` 时 `python -m src.cli` 等价可用** |

## 4. 明确不在范围

- Phase 6 跨平台（9 个平台语义失败清零）——方案见 `docs/PHASE6-PREP-PLAN.md`；
- Phase 7 Git 同步、Phase 8 Knowledge-Agent；
- AI 分析（Phase 11）；
- 任何 `schema/` 契约变更、任何安全加固路线选择（SEC-01）。

## 5. 待裁定（**不由开发方自行决定**）

1. **S2**：Collector Protocol 拆分/闭合方式（a 最小闭合 / b 拆协议 / c 仅文档）；
2. **R1**：新旧模块关系（并存 / 原地替换 / 并存+收口时点）；
3. **git 历史**：真实书签标识是否重写历史清除；
4. **Phase 6 方案**是否批准执行。

选项与影响：`X-Bookmark-Knowledge-Automation/docs/PHASE5-PREP-BRIEF.md`。
