# Current State Board — X Bookmark Knowledge Pipeline（跨平台改造）

> 本文件是「当前状态板」，只放进度总览 + 当前 Phase 指针 + 下一步。
> 每个 Phase 的详细任务书独立成文件：`tasks/PHASE-N-NAME.md`。

## 进度总览

| Phase | 名称 | 状态 | 任务书 |
| --- | --- | --- | --- |
| 0 | 架构审计 | ✅ 完成 | — |
| 1 | 架构设计 | ✅ 完成 | — |
| 2 | Canonical Schema | ✅ 完成（28 用例绿，未提交） | — |
| **3** | **Collector Adapter** | ✅ **实现完毕、已离线验收（未提交）** | `PHASE-3-COLLECTOR-ADAPTER.md` |
| 4 | Storage | ⏳ 待开始（**需老板授权**） | `PHASE-4-STORAGE.md` |
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
  - 新增 `tests/test_raw_data.py`（20）、`tests/test_fieldtheory_collector.py`（21）、`tests/test_normalizer.py`（87）
  - 修改 `src/collector/base.py`（`Collector` Protocol 增 `collect()`，+12 行）
  - 文档：`docs/phase3-preflight-review.md` 追加「决策与修正记录」；`PLAN.md` / `CHANGELOG.md` 同步
- **五项决策**（见 `docs/phase3-preflight-review.md` §10.1）：dict 输出 / content_hash 按 §5.4 九项 /
  新建 `fieldtheory/` 包且旧 adapter 不动 / 富化取 `data/raw/` / 时间戳取 `syncedAt`。
- **验收证据**（2026-10-08，全部离线）：
  - 新模块 `python -m unittest tests.test_raw_data tests.test_fieldtheory_collector tests.test_normalizer` → **128 用例全绿**
  - 全量 `python -m unittest discover -s tests -t .` → 524 用例、**9 失败**（全在 `test_config`/`test_media`/`test_external` 的 Windows 路径语义，归 Phase 6）
  - 真实数据只读验收：`data/upstream` + `data/raw` → 5/5 `RawBookmarkItem` → 5/5 `CanonicalBookmark` → Schema 全通过（4 篇 Article、1 媒体、1 外链去重后）
  - 未写 `data/`、`knowledge/`、`schema/`、`config/`；未联网；未 Git 提交

## 关键状态

- **真实数据已就位**（2026-10-08 从 Windows 包迁移）：`data/upstream/`（5 条 + 6 媒体）、`data/raw/`、`config/config.yaml`、`knowledge/X-Bookmarks/`（5 篇 md + 资产）。
- **已知问题**：全量测试 9 失败，全为 Windows 语义平台断言，归 Phase 6。原记录为 11 个，Phase 6 需复核基线。
- **未提交改动**：Phase 2 + Phase 3 交付物与文档更新，均在本地工作区（未 `git commit` / `push`）。
- **Phase 3 遗留 gap**（记录，不在本 Phase 修改）：`engagement` 无 Canonical 字段（留 payload）；
  `reply_to`/`thread` 无数据源（恒 `null`）；`quotedTweet` 形状待验证（真实样本均为 `null`）；
  `video`/`animated_gif` 未实测；非绝对 URI 外链被丢弃；`Collector` Protocol 仍含写上游的 `sync()`。

## 下一步（等老板指令）

1. 复核 Phase 3 交付物 → 决定是否 `git commit`（本地提交 / 推送需显式授权）。
2. 若进入 Phase 4（Storage）：先出「待验证清单」与实现计划，获批准后再动代码。
3. Phase 6 启动前复核全量测试失败基线（9 vs 记录 11）。

## 硬约束（沿用 AGENTS.md）

- 验证分级授权：运行测试 / 联网 / 写盘，必须先列「待验证清单」交老板批准。
- 每 Phase 实现完成后先停下，未获批准不得自行验证。
- 数据与知识分离；敏感信息不进 Git/日志/Markdown。
