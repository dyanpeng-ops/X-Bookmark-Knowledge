# 开发 ↔ 审计 循环工作流（DEV-AUDIT LOOP）

> 建立日期：2026-10-09
> 授权来源：用户显式指令 ——「每一步骤的开发完成后就发送开发报告，然后等待审计报告，
> 再根据审计报告继续修改开发，一直循环，直到开发结束」

本文件定义该循环的**步骤、产物、命名、存放位置、停止条件与授权边界**，使每一轮都可追溯。

---

## 1. 循环步骤

```text
① 开发（一个循环单元）→ ② 自验（离线测试 + 边界核对）→ ③ 写开发报告
→ ④ 上传报告到 Drive「development report」→ ⑤ 等待审计报告出现在 Drive「audit report」
→ ⑥ 读取审计报告（按修改时间正序）→ ⑦ 逐条复验审计结论 → ⑧ 修复 / 记录不修理由
→ ⑨ 提交并推送 Git → 回到 ①
```

每轮必须产出：**可复现的验证证据**（命令 + 结果）、**明确标注的未验证项**、
**未修复项及其理由**。禁止把未验证的东西写成已验证。

## 2. 产物与命名

| 产物 | 命名 | 存放位置 |
|---|---|---|
| 开发报告 | `X-Bookmark-Knowledge-<单元>-report.md` | Drive 文件夹 `x-bookmark-development report` |
| 审计报告（外部产出） | `X-Bookmark-Knowledge-<单元>-audit.md` | Drive 文件夹 `x-bookmark-audit report` |
| 报告源文件 | 同步一份到仓库 `docs/` | Git |

- 生产目录：`/Users/nanopeng/AI-Agent-Lab/x-bookmark-audit/`
- Drive 文件夹 ID：
  - development report：`1RC9xW__N0soTDkG4cVsiiS0d5d-Ia8mV`
  - audit report：`1W6lJQuA4-FbOiWwJbnTSfCQ_s0QgYVgV`

## 3. 循环单元

默认 **1 个 Phase = 1 个循环单元**（与既有审计粒度一致）。
Phase 内部按 Step 实现，全部完成并通过自验后才出报告。

## 4. 授权边界（常设）

用户已授权本循环内的以下动作，**无需逐次再问**：

- 运行**离线**测试（`python -m unittest ...`；不联网、用临时目录、不碰真实数据）
- 写入本仓库文件、`git commit` / `git push` 到 `origin/main`
- 上传开发报告到上述 Drive「development report」文件夹
- 读取上述 Drive「audit report」文件夹中的审计报告

**仍需先停下询问**（不自行决定）：

1. 修改 `schema/bookmark.schema.json` 或 Canonial 契约语义
2. 需要架构决策的事项（例：S2 — 是否拆分只读 `Collector` Protocol）
3. 需要权衡路线的安全加固（例：SEC-01 — DNS 重绑定是否做 IP 绑定）
4. 任何联网抓取、访问真实外部站点
5. 触碰 `data/`、`knowledge/` 真实数据或知识库
6. 使用新凭据 / 新账号 / 向新的第三方位置写入
7. 删除文件、批量移动/重命名知识库文件、覆盖已有 Markdown

## 5. 停止条件

满足任一即停止循环并报告：

- 全部 Phase（当前目标：Phase 4 → 8）完成，且最后一轮审计报告无阻塞性发现
- 用户显式叫停
- 出现第 4 节中任一「需先询问」的事项且未获答复
- 连续 3 轮出现同一阻塞条件

## 6. 等待审计报告的方式

- 每轮报告上传后，检查 Drive「audit report」文件夹是否有**新于上一轮**的文件
- 有新文件 → 立即按修改时间正序读取并进入 ⑦
- 无新文件 → 本轮结束待命，不空转；用户提示「审计到了」可立即触发
- 读取依赖本机 Chrome 已登录该 Google 账号，且 `browser-harness` 可用

## 7. 与 AGENTS.md 的关系

本文件是 `AGENTS.md` 在「开发—审计协作」上的**具体化**，不覆盖 AGENTS.md 的红线：

- 数据与知识分离、敏感信息不进产物、只读上游、先验证后声明
- 遇架构/Schema 级变更先停下报告（AGENTS §2.13、§2.15、§8）
