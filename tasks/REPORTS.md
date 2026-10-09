# 报告索引（开发报告 ↔ 审计报告）

> 用途：让**开发报告**与**审计报告**用同一套编号一一对应，双方不必靠时间戳猜配对。
> 规则由自动化流水线定义（`/Users/nanopeng/AI-Agent-Lab/X-Bookmark-Knowledge-Automation/README.md`
> 与 Drive `X-Bookmark-Knowledge-Automation/00_CONTROL/`）；本文件是**登记表**（每产出一份报告就登记一行）。
> 历史说明：原 `tasks/DEV-AUDIT-LOOP.md`（含旧「常设授权」）已于 2026-10-09 按用户裁决**废弃并删除**——
> 其授权条款与新的 DSH 流水线任务书 §7 冲突，**不再有效**。历史报告中的引用保留原样，仅作记录。

---

## 1. 命名规则（以 Phase 序号为主键）

| 类型 | 命名模板 | 示例 |
|---|---|---|
| 阶段完成报告 | `X-Bookmark-Knowledge-Phase<N>-Report-<YYYY-MM-DD>.md` | `X-Bookmark-Knowledge-Phase3-Report-2026-10-09.md` |
| 阶段内分步报告 | `X-Bookmark-Knowledge-Phase<N>-Step<M>-Report-<YYYY-MM-DD>.md` | `X-Bookmark-Knowledge-Phase4-Step1-Report-2026-10-09.md` |
| 同日报修订版 | 追加 `-v2` / `-v3`（**不改名历史版本**） | `X-Bookmark-Knowledge-Phase4-Step1-Report-2026-10-09-v2.md` |
| **审计报告（镜像命名）** | 同上，把 `Report` 换成 `Audit` | `X-Bookmark-Knowledge-Phase4-Step1-Audit-2026-10-09.md` |
| 跨阶段汇总 | `X-Bookmark-Knowledge-PROGRESS-Report-<YYYY-MM-DD>.md` | 备用 |

要点：

- **Phase 号用 `Phase<N>`（阿拉伯数字，不加前导零）**，与审计方已发布的
  `X-Bookmark-Knowledge-Phase3-Audit-2026-10-09.md` 写法一致；不用 `P3` 之类缩写，
  也不用中文或"cycle"等非阶段词。
- 分步报告带 `Step<M>`，与 `tasks/PHASE-<n>-*.md` 任务书里的 Step 编号一致。
- 审计方只需把 `Report` 改成 `Audit`，即得到配对文件名。
- 识别"是否是新审计"**看文件 ID**（改名会刷新 Drive 的 modifiedTime，不能只看时间）。

## 2. 已产出报告登记

| 编号 | 类型 | 开发报告文件 | 对应审计文件 | 提交 | 状态 |
|---|---|---|---|---|---|
| `Phase3` | 阶段完成报告（Phase 0→3 汇总） | `X-Bookmark-Knowledge-Phase3-Report-2026-10-09.md` | `X-Bookmark-Knowledge-Phase3-Audit-2026-10-09.md` | `bf740ca`…`6751452` | ✅ 已审计并闭环（A1–A5 已修） |
| `Phase9` | 阶段审计响应报告 | `X-Bookmark-Knowledge-Phase9-Report-2026-10-09.md` | 待审计方命名（原《静态审计报告》`SEC-01/CFG-01/QA-01`） | `fb14bdc` | ✅ 已修复 CFG-01/QA-01；SEC-01 待决策 |
| `Phase4-Step1` | 阶段内分步报告（Storage Step 1：JSON 投影） | `X-Bookmark-Knowledge-Phase4-Step1-Report-2026-10-09-v2.md`（v1 已被 v2 取代） | 待产出（`…-Phase4-Step1-Audit-2026-10-09.md`） | `6a9c5c7`、`c604da1` | ⏳ **等待审计** |

> **改名历史**（只改文件名，**文件 ID 与内容不变**）：
> - `Phase3` ← Drive 原名 `progress-report.md`
> - `Phase9` ← `X-Bookmark-Knowledge-cycle1-audit-closeout-report.md`
> - `Phase4-Step1` v2 ← `X-Bookmark-Knowledge-Phase4-Step1-report-v2.md`；
>   v1 ← `X-Bookmark-Knowledge-Phase4-Step1-report.md`（已被 v2 取代，保留作追溯）

## 3. 待产出的报告（预告）

| 编号 | 计划内容 | 触发条件 |
|---|---|---|
| `Phase4-Step2` | Markdown 投影（路径 / frontmatter / 两段式正文） | 审计到达 或 用户放行 + R1 裁决 |
| `Phase4-Step3` | SQLite 索引（R6 两类字段） | `Phase4-Step2` 之后 |
| `Phase4-Step4` | `rebuild-index` | `Phase4-Step3` 之后 |
| `Phase4` | Storage 阶段完成报告 | Step 1–4 全部完成 |
| `Phase5` | CLI 阶段报告 | Phase 4 完成审计后 |

## 4. 未决事项（阻塞后续报告）

| # | 事项 | 影响 |
|---|---|---|
| R1 | `src/storage/` 与既有 `src/ingest`/`src/markdown`/`src/database` 并存 vs 原地替换 | 影响 `Phase4-Step2` 起 |
| SEC-01 | DNS 重绑定加固路线（绑定 IP / 双向解析比对 / 接受并文档化） | 影响 Phase 9 补验收 |
| S2 | `Collector` Protocol 拆分 | 影响 Phase 5 开工 |
