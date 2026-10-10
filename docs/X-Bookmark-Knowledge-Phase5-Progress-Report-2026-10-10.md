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

