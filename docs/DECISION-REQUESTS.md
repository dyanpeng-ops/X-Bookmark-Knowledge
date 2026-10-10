# 待裁定事项单（开发方不能自行决定的部分）

> 生成于 2026-10-10；项目 Phase 4 已完成、Phase 5 部分完成（其余部分被下列决策**阻塞**）。
> **如何回复**：一行即可，例如 `D-1=a, D-2=c, D-3=批准, D-4=A, D-5=A, D-6=<你的路线>`。
> 未裁定的项，开发方一律**不动手**（越权风险高于等待成本）。

## 当前状态（便于判断优先级）

| 项 | 状态 |
|---|---|
| Phase 4（三投影存储） | ✅ 完成（652→663 用例；SQLite 可重建；审计多轮 PASS）|
| Phase 5（CLI 收拢）| 🟡 部分完成：`normalize`/`render`/`rebuild-index`/`status`/`doctor` 已交付；**剩余部分被 D-1/D-2 阻塞** |
| 审计 | 轮 8–15 全部 **PASS**（18 个文件已接收）；轮 16–20 待复审 |
| 测试 | 项目 663 用例（9 个平台语义失败，与基线逐条一致）· 自动化 160 用例全绿 · 变异 13/13 被捕获 |

---

## D-1 · S2：`Collector` Protocol 如何闭合

**事实**：`FieldTheoryCollector` 缺 `sync()` / `read_bookmarks()` → 按 Protocol 取用会运行期 `AttributeError`。
**阻塞**：Phase 5 剩余部分（CLI 按 Protocol 装配 Collector）。

| 选项 | 代价 | 影响 |
|---|---|---|
| **a 最小闭合**（推荐）| ~10 行 + 2-3 用例 | 立刻满足 Protocol；语义上"只读收集器也能 sync"，边界略糊 |
| **b 拆协议** | 改 `src/collector/base.py` + 装配处 | 语义最干净；触及既有消费者，改动面大 |
| **c 仅文档** | 0 | 债务留存；按 Protocol 装配会踩坑 |

📄 细节：`X-Bookmark-Knowledge-Automation/docs/PHASE5-PREP-BRIEF.md` §三

## D-2 · R1：新旧模块关系

**事实**：`src/collector/fieldtheory/adapter.py`（Canonical 版）与 `fieldtheory_adapter.py`（旧 Windows 版）并存。
**阻塞**：Phase 5 CLI 的权威路径定义、Phase 7 的 `process` 归属。

| 选项 | 代价 | 影响 |
|---|---|---|
| a 并存（现状）| 0 | 两套栈、概念重复；新 CLI 需明确权威路径 |
| b 原地替换 | 大 | 目录干净，但**大面积破坏既有测试**，回归判定失真 |
| **c 并存 + 明确收口时点**（推荐）| 中（需纪律）| 风险/收益最平衡：约定 Phase 7 `process` 切 Canonical、旧 `src/markdown` 退为兼容层 |

📄 细节：同上 §四

## D-3 · Phase 6 方案是否批准执行

**内容**：清零 9 个平台语义失败（根因已查明，全部在**测试/桩侧**，无产品缺陷）：
A 路径解析 `/var`↔`/private/var`（4）；B 桩用 `Path("C:\\...").name`，POSIX 下反斜杠非分隔符（2）；
C Windows 盘符语义（3）。目标：把"9 个已知失败"变成"期望 0 失败"的干净基线。
**代价**：改 `tests/`（不动产品代码），预计 0.5–1 轮；风险低但会让失败基线作废（需重设基线）。
📄 细节：`docs/PHASE6-PREP-PLAN.md`

## D-4 · Phase 7：`.gitignore` 与 §8.2 规格**相反**（新发现）

**事实（实测）**：`ARCHITECTURE §8.2` 要求 `data/normalized/` + `knowledge/X-Bookmarks/**/*.md` +
`assets` **入 Git**；但 `.gitignore` 第 15/48 行把三者**全部挡住**。
**阻塞**：Phase 7 整条链路。后果：跨设备无法同步；新机器无法 `rebuild-index`；
**富化内容（article/quoted）只在 normalized JSON 中，不同步即永久丢失**；Markdown 引用断裂。

| 选项 | 影响 |
|---|---|
| **A 按 §8.2 实现**（推荐 + 三条护栏）| 真实书签内容进入 GitHub **私有**仓库；需确认私有 + 提交前护栏 + assets 体积策略 |
| B 只同步 Markdown | 仓库小，但"无法重建索引 / 富化丢失"依然存在 |
| C 不进 Git，改用云盘等 | 与 §8.1 冲突，需重新定义同步机制（架构决策）|

护栏已就绪：`scripts/guard-staged`（拒绝 `data/raw/`、`data/state/`、`*.db`、凭据文件、日志、
以及 diff 中的真实标识）。**我未自行改 `.gitignore`**——改后下一个 `git add -A` 就可能把真实知识库纳入提交。
📄 细节：`docs/PHASE7-SYNC-PREP-PLAN.md`（含精确补丁）

## D-5 · git 历史中的真实书签标识

**事实**：`4922ae4` 只清了工作树；**历史提交中仍含** 5 个文件的真实标识（tweet_id/handle/显示名）。
**关键副作用**：重写历史会改变受影响提交之后的**全部 SHA** ⇒ 既存审计包声明的
`base_commit`/`head_commit`/`git_range` **全部失效**，须标记 `SUPERSEDED` 并重跑基线。

| 选项 | 影响 |
|---|---|
| **A 不处理**（可接受则推荐）| 仓库私有 + 非凭据；把本项作为"已知并接受"记录 |
| B 重写历史（filter-repo）| 历史干净，但强推 + 作废既有审计基线 |
| C 另起干净仓库（优于 B）| 避免强推与失效链条；需迁移 remote；应在**下一轮审计前**完成 |

📄 细节：`docs/GIT-HISTORY-CLEANUP-PLAN.md`

## D-6 · SEC-01：安全加固路线

**内容**：出站请求的加固路线选择（含 DNS rebinding 防护方案取舍）。
**阻塞**：Phase 8 之前的网络层加固实现。**我不自行选择路线。**
📄 细节：待你指定范围后我再出选项简报（避免给出与实际威胁不匹配的方案）。

---

## 附：决定后的连锁影响（帮你判断顺序）

```text
D-4（Phase 7 .gitignore）─┐
D-2（R1 权威路径）────────┼─→ Phase 5 收尾 → Phase 7 process 切换 → Phase 8 Knowledge-Agent
D-1（S2 Protocol 闭合）───┘
D-3（Phase 6 方案）→ 干净失败基线（其余 Phase 的回归判定基准）
D-5（git 历史）→ 若重写，必须**在下一轮审计前**做，否则要作废更多基线
```

**建议顺序**：D-4 → D-3 → D-2 → D-1 → D-5 → D-6（前两项影响后续所有回归与同步判定）。
