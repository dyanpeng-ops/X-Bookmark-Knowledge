# X-Bookmark-Knowledge · Phase 5（CLI）进度报告

| 项 | 值 |
|---|---|
| Phase | 5 — CLI |
| 日期 | 2026-10-10 |
| 状态 | 🔄 **进行中**（已完成"决策无关"部分；剩余部分卡在待裁定项） |
| 相关提交 | `c936ff6`（起步）、`4922ae4`（脱敏）、`ccc93a7`（文档与可观测性） |

---

## 一、已完成

| # | 交付 | 证据 |
|---|---|---|
| 1 | **`normalize`**：上游 `bookmarks.jsonl`(+`data/raw/` 富化) → Canonical 校验 → `data/normalized/{tweet_id}.json`；默认**只演练**，`--apply` 落盘 | `tests/test_cli_canonical.py` |
| 2 | **`render`**：Canonical JSON → `knowledge/X-Bookmarks/{YYYY}/{MM}/{YYYYMMDD}-{tweet_id}.md`；**不覆盖内容不同的既有文件**（AGENTS §14）；默认**只演练** | 同上 |
| 3 | **`xbk` 入口**：`pyproject.toml` 声明 `[project.scripts] xbk = "src.cli.main:main"`（**需 `pip install -e .` 才生效，该安装未执行**） | `pyproject.toml` |
| 4 | **`status` 可观测性**：新增 `canonical` 段（normalized 目录/文件数/流水线命令），只读 | 3 个用例 |
| 5 | **文档债修正**：README（Python 版本、`pyproject` 现状、Canonical 流水线小节）；`config.example.yaml` 如实区分两套 collector 模块并标注 S2 待裁定 | `README.md`、`config/config.example.yaml` |
| 6 | **安全性修复**：清除 5 个受控文件中的真实书签标识（其中 `schema/bookmark.schema.json` 仅改 description 举例） | `git grep` 对 13 条拒绝清单 → **0 命中** |

**测试**：`tests/test_cli_canonical` 15/15；既有 `tests/test_cli` 14/14；全量 **650 用例 / 9 失败**
（9 条为既有平台语义失败，与基线失败集逐条一致）。变异验证：4 次变异共捕获 1+1+1+6 个用例。

## 二、外部审计（Muse）

| 轮次 | 范围 | 状态 |
|---|---|---|
| 第 8 轮 | 审计 F-006 修复（证据来源护栏） | 待审 |
| 第 9 轮 | Phase 5 起步 + 受控文件脱敏 | 待审 |
| 第 10 轮 | Phase 5 文档与可观测性 | 待审 |
| 第 11 轮 | 流水线工具：审计接收自动化 | 待审 |
| （第 7 轮及以前）| Phase 4 各 Step | 全部 PASS；6 个 run 已 `DONE` |

## 三、阻塞：三项用户决策（**我不会自行裁定**）

| # | 事项 | 选项 | 影响 |
|---|---|---|---|
| **S2** | Collector Protocol 缺口（`FieldTheoryCollector` 缺 `sync`/`read_bookmarks`，按 Protocol 取用会 `AttributeError`） | a 最小闭合（加两个委托方法）/ b 拆协议 / c 仅文档 | 决定 Phase 5 后续 CLI 如何装配 Collector |
| **R1** | `src/storage/`（新）与旧 `src/ingest`/`src/markdown`/`src/database` | 并存 / 原地替换 / 并存+收口时点 | 原地替换会大面积破坏 500+ 既有测试 |
| **历史** | 真实书签标识仍在 git 历史（`4922ae4` 之前） | 是否重写历史并强推 | 破坏性；影响已推送提交与审计基线 |

详见 `X-Bookmark-Knowledge-Automation/docs/PHASE5-PREP-BRIEF.md`。

## 四、下一步

1. 裁定上述三项 → 完成 Phase 5 剩余部分（Collector 装配 + 按 Protocol 的 CLI 集成）；
2. 再进 **Phase 6（跨平台）**：方案已就绪（`docs/PHASE6-PREP-PLAN.md`），目标是
   把 9 个平台语义失败清零、**把回归判据从"与 9 条基线比对"升级为"期望 0 失败"**；
3. 之后 Phase 7（Git 同步）→ Phase 8（Knowledge-Agent）。

---

## 附：进度更新（2026-10-10 晚，第二次）

| 项 | 状态 |
|---|---|
| `rebuild-index --db` | ✅ 新增（使 `--apply` 可在临时库验收，不再只能写真实 `data/state/`）|
| 真实数据 CLI 级验收 | ✅ **10/10 通过**（临时配置 + 真实只读输入；真实 `data/`、`knowledge/` 指纹未变）|
| CLI 级 A1 回归 | ✅ 新增（非 UTF-8 富化快照不拖垮整批，含"富化警告 1"断言）|
| 证据质量 | ✅ 日志改 **verbose**（回应审计第 12 轮：原日志仅摘要、无用例名）|
| Phase 5 任务书 | ✅ `tasks/PHASE-5-CLI.md`（供每包附 `TASK.md`）|
| 审计接收 | ✅ 轮 8–12 全部 PASS 并推进 `REVIEW_READY`（用新工具一键接收）|
| 自动化流水线 | ✅ 出包自检 10 项、断言↔证据强制校验、变异检查器、审计接收工具 |
| 仍待裁定 | **S2 / R1 / git 历史清理 / Phase 6 方案** |

---

## 附：进度更新（2026-10-10 深夜，**第三次**；覆盖轮 14–29）

> 本节覆盖上一次更新之后的 16 个工作轮。**Phase 5 的决策无关部分已完成**；
> 剩余部分与 Phase 6/7 均**阻塞于用户裁决**（见文末决策单）。

### 一、审计往来

| 项 | 状态 |
|---|---|
| 已接收审计结论 | 轮 8–16 **全部 PASS**（19 个文件；哈希绑定 manifest，均推进 `REVIEW_READY`）|
| 待复审 | **10 个包**（轮 17–29），由 `state/AUDIT-REGISTRY.md` 统一登记（自动生成）|
| 审计方反复提出的缺件 | **已系统修复**：附 `TASK.md`、附**改动前基线日志**、附**变异日志**、日志改 **verbose**（可逐条核对用例名）|

### 二、测试与自证（当前基线）

| 项 | 值 |
|---|---|
| 项目用例 | **663**（9 个失败全为 Windows 路径语义，归 Phase 6；与基线**逐条一致**）|
| 自动化用例 | **191**，全绿 |
| 变异验证 | 项目 **9/9** + 自动化 **13/13** 被捕获 |
| 出包自检 | `scripts/self-audit-package`（10 项 + C11 重名检测） |
| 真实数据 CLI 验收 | **10/10**（临时配置 + 真实只读输入；真实 `data/`、`knowledge/` 指纹未变）|
| 源码树泄漏扫描 | **0 命中**（文本 + 二进制，含 `__pycache__`；例行接入 `preflight`）|

### 三、本期真正解决的问题（按主题）

1. **打包透明度**（回应审计 13/14/15 轮）：manifest 新增**拒绝清单元数据**（条数/类别/sha256/派生方法）+
   **扫描器自检**；附**隔离动作日志**；**包自身自检**作为同级文件发布；附 **doctor 原始输出**。
2. **证据可信度**：断言必须附**包内证据**否则拒绝出包；证据必须**在包内 head 状态产生**否则拒绝复用；
   每包附**改动前后**两份全量日志。
3. **出包自检工具**：把"审计方的第一轮检查"前置到本地（10 项 + C11），避免再耗外部轮次发现机械问题。
4. **审计接收完整性**：结论落盘/推进逻辑提取为可测函数，覆盖**幂等**（重复 apply 不二次推进）、
   **fail-closed**（未知 run / 哈希不符 / 阻断 findings 一律不推进）。
5. **上传防假成功**（此前的真实坑）：5 条 fail-closed 规则，含"进度条出现 ≠ 完成"与
   **反陈旧**（同名旧文件不算成功）。
6. **状态机不变式**：声称已送审**必须**能回溯到具体产物（`audit_package_sha256`），`save`/`load` 双向强制。
7. **★ 一次真实标识泄漏的发现与修复**：测试夹具误用了**真实 tweet_id**（由出包护栏拦下）；
   随之补**全树扫描**并发现其**二进制盲区**（泄漏值藏在 `.pyc` 里）；修复后隔离 **28 个**含真实标识的旧缓存
   （**未删除**）。**项目受控文件全程 0 命中**，泄漏未进入任何已上传包或提交。
8. **可靠性**：Drive 调用**有界重试**（瞬时失败）；harness 可执行文件解析**不再依赖 shell PATH**；
   损坏索引库转**领域错误**（含 SQLite 惰性报错的处理）；原子写补**崩溃安全**测试（失败不留半截文件）。
9. **如实披露的过程缺陷**：2 个 run 作废（其中一个包含**重名材料**的包已上传）——
   **未删除任何已上传制品**，仅标注作废，说明随包附上。

### 四、新发现的一个**阻塞项**（需你裁决）

`ARCHITECTURE §8.2` 要求 `data/normalized/`、Markdown 与 assets **入 Git**，
但 `.gitignore` **实测把三者全部挡住** ⇒ Phase 7 的跨设备链路**不成立**，
且新机器**无法 `rebuild-index`**；富化内容（article/quoted）只在 normalized JSON 中，**不同步即永久丢失**。
方案与精确补丁见 `docs/PHASE7-SYNC-PREP-PLAN.md`（**未自行修改 `.gitignore`**）。

### 五、需要你裁决（`docs/DECISION-REQUESTS.md`，**一行即可回复**）

| # | 事项 | 我的推荐 |
|---|---|---|
| D-1 | S2 `Collector` Protocol 闭合 | a（最小闭合）|
| D-2 | R1 新旧模块关系 | c（并存 + 明确收口时点）|
| D-3 | Phase 6 方案（清零 9 个平台语义失败）| 批准执行 |
| D-4 | Phase 7 `.gitignore` 与规格相反 | A（按 §8.2 实现 + 三条护栏）|
| D-5 | git 历史中的真实标识 | A（不处理）；若必须清则 C（另起干净仓库）|
| D-6 | SEC-01 安全加固路线 | 待你指定范围后我再出选项简报 |

**建议顺序**：D-4 → D-3 → D-2 → D-1 → D-5 → D-6。

