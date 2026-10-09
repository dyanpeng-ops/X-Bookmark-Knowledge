# X-Bookmark-Knowledge 开发报告 · Cycle 1（审计待办关闭）

> **报告日期**：2026-10-09
> **循环单元**：Cycle 1 — 关闭第三方审计待办（非新 Phase）
> **仓库 / HEAD**：`main` @ 本轮新增提交（见 §5）
> **上一轮**：Phase 3 完成并通过审计（提交 `6751452`，A1–A5 已修）
> **本轮结论**：**CFG-01 已修复、QA-01 已更正；SEC-01 与 S2 属"需先询问"事项，未修**
> **数据边界**：本报告与代码不含真实书签内容、媒体、SQLite 状态库与任何凭据

---

## 1. 本轮目标

按《开发 ↔ 审计循环工作流》（`tasks/DEV-AUDIT-LOOP.md`）**步骤 ⑦–⑧**：逐条复验外部审计结论，
修复可修项、记录不修项及其理由。

审计来源：第三方《X-Bookmark-Knowledge 静态审计报告》（对象为 `src/external/` 外链抓取层），
其 3 项发现与本机实测结论如下。

| 编号 | 审计说法 | 本机复验 | 本轮处置 |
|---|---|---|---|
| **CFG-01** | `LinkResolver` 默认构造抓取器未传安全配置 | **成立**（代码确认 + 零测试覆盖） | ✅ **已修复** |
| **QA-01** | README 历史测试结论未经独立验证 | **成立**（README 声称 Ran 369 tests OK，实际 532/9） | ✅ **已更正** |
| **SEC-01** | DNS 校验与实际连接存在时间差 | **成立**（真实结构性缺口），但属安全加固**路线选择** | ⏸ 待用户决策 |

---

## 2. 修复详情

### 2.1 CFG-01（配置一致性 bug）

**缺陷**：`LinkResolver.__init__` 拿得到 `options`，却在默认构造 `HttpFetcher` 时漏传
`block_non_public_hosts` 与 `allow_hosts`。

**影响**（经复核，与审计的表述略有差异，这里按实际语义修正）：

- 漏传的两个参数其**默认值恰是最严格侧**（`block_non_public_hosts=True`、`allow_hosts=()`），
  因此该缺陷**不会放宽**安全策略 —— 只会：
  - `external.allow_hosts` 白名单被忽略 → 合法自建服务被**误拦**；
  - `external.block_non_public_hosts: false` 被忽略 → **过度拦截**。
- 生产路径 `xbk links` 经 `_build_link_fetcher` 显式传参，**线上行为未受影响**；
- 该默认分支此前**零测试覆盖**（`tests/test_external.py` 4 处 `LinkResolver(...)` 构造全部注入 `fetcher=`）。

**修复**（`src/external/resolver.py`）：默认分支补齐两个参数并注明原因。

**回归用例**（`tests/test_external.py` · `ReviewFixTests`，+2）：

1. `test_link_resolver_default_fetcher_inherits_security_options`
   —— 不注入 fetcher 时，`block_non_public_hosts=False` 与 `allow_hosts=("localhost",)` 必须生效；
   并行为验证「关闭开关后私网目标不再被拦」（**不触网、不做 DNS**）。
2. `test_link_resolver_default_fetcher_keeps_strict_default`
   —— 反向用例：默认配置下默认分支仍是最严格取值，私网目标被拦。

### 2.2 QA-01（文档过期）

`README.md` 三处更正：

| 位置 | 原文 | 更正为 |
|---|---|---|
| 快速开始提示 | 只有 Windows 测试命令 | macOS/Linux 与 Windows 双写法 |
| 验证命令块 | `cd D:\Users\...` + 「最近一次通过：Ran 369 tests … OK（2026-09-21）」 | 2026-10-09 macOS 实测 **532 用例 / 9 个平台语义失败**，并说明该口径不可跨平台移植（Linux 沙箱 3 failures + 16 errors） |
| Phase 9 状态行 | 「真实数据写运行与提交仍待批准」 | 已提交（`78ed077`）；并补记 CFG-01 修复与 SEC-01 待决策 |

---

## 3. 验证证据（本轮，全部离线）

| 项 | 命令 | 结果 |
|---|---|---|
| CFG-01 回归 | `python -m unittest tests.test_external.ReviewFixTests` | **11 用例全绿** |
| 外链层单测 | `python -m unittest tests.test_external` | 96 用例 / **1 失败**（既有 macOS 平台语义，非本轮引入） |
| 全量回归 | `python -m unittest discover -s tests -t .` | **532 用例 / 9 失败**，失败集与修复前**完全一致**（`test_config` 4 / `test_media` 3 / `test_external` 2） |
| 无回归判定依据 | 逐条比对失败清单 | 与上一轮报告同名同数 → 本轮改动**零新增失败** |
| 联网行为 | —— | 未联网；新增测试不触网、不做 DNS 解析 |

---

## 4. 未修项及理由（待用户决策）

| 编号 | 事项 | 为何本轮不修 |
|---|---|---|
| **SEC-01** | `netguard` 校验 IP 后 `urllib` 再次独立解析，无 IP 绑定 → 理论存在 DNS rebinding / TOCTOU 窗口。每跳重定向**已**重新校验 | 按 `DEV-AUDIT-LOOP.md` §4.3：**安全加固路线选择需用户拍板**。可选路线：① 绑定已验证 IP 连接并保留 SNI/Host（彻底，约 60–100 行 + 离线 rebinding 测试）；② 连接前后各解析一次比对（折中，只能缩小窗口）；③ 接受风险并文档化 |
| **S2** | `FieldTheoryCollector` 未形式化满足 `Collector` Protocol（故意不暴露会写上游的 `sync`/`read_bookmarks`） | 按 §4.2：**架构决策需用户拍板**（拆 `ReadOnlyCollector` Protocol vs 显式实现完整接口）。建议在 Phase 4 开工前定 |

---

## 5. 变更清单

| 文件 | 变更 |
|---|---|
| `src/external/resolver.py` | 默认分支补齐 `block_non_public_hosts` / `allow_hosts` |
| `tests/test_external.py` | 新增 2 个 CFG-01 回归用例 |
| `README.md` | 3 处过期/平台限定内容更正 |
| `CHANGELOG.md` | 新增「Phase 9 · 审计响应」记录 |
| `tasks/DEV-AUDIT-LOOP.md` | 新增（循环工作流定义，本循环的授权与步骤依据） |
| `docs/X-Bookmark-Knowledge-P3-Report-2026-10-09.md` | 上一轮产出（已上传 Drive；原名 `progress-report.md`） |

提交：见本轮 `git log`（已推送 `origin/main`）。

---

## 6. 下一轮计划

1. **等待审计报告**：检查 Drive「audit report」文件夹是否出现新文件（本报告上传后）。
2. **若 SEC-01 / S2 已获决策** → 立即实施。
3. **进入 Phase 4（Storage）**：`Canonical Data → JSON / Markdown / SQLite 索引 + rebuild-index`。
   按 AGENTS §17，Phase 4 无现成任务书，开工前先产出实施计划与验收标准。

*本报告所有结论均标注了验证方式；未实测项已显式标注「待决策 / 未验证」。*
