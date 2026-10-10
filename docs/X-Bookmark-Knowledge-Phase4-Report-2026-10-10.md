# X-Bookmark-Knowledge · Phase 4（Storage）完成报告

| 项 | 值 |
|---|---|
| Phase | 4 — Storage（Canonical JSON / Markdown / SQLite / rebuild-index） |
| 日期 | 2026-10-10 |
| 分支 / HEAD | `main` / 见提交记录（Step 4 收尾） |
| 结论 | **Phase 4 五个 Step 全部交付并通过验收**（含真实数据**只读** dry-run） |

---

## 一、交付清单

| Step | 交付 | 提交 | 测试 |
|---|---|---|---|
| S1 Canonical JSON 投影 | `src/storage/json_projection.py` | `6a9c5c7` + `c604da1` | 30 用例 |
| S2 Markdown 投影 | `src/storage/markdown_projection.py` | `f067ac6` + `a9ec0a9` + `7b0ca13` | 32 用例 |
| S3 SQLite 索引（R6 二分） | `src/database/r6_fields.py`、`index_store.py`、`MIGRATION_3` | `947bfdb` | 19 用例 |
| S4 `rebuild-index` | `src/storage/rebuild.py` + CLI | `6eda5b3` | 22 用例 |
| S5 全量验收（只读 dry-run） | 本报告 + `scripts/step5-dryrun`（自动化侧） | — | 10 项检查全通过 |

**关键设计点**

- **D1 原子写 + 内容哈希幂等**：同 `content_hash` 一个字节都不重写。
- **D2 frontmatter 按 Canonical 决策 D2**：`author`=显示名、`author_username`=handle。
- **R6 字段二分**：内容索引（可重建）与运行态（重建即重置）在**类型层与接口层**都隔离
  （内容写入接口拒绝运行态键；`assert_classification_complete` 拦住 DDL 漏归类）。
- **D4 重置语义写进命令帮助**：`rebuild-index --help` 逐字段说明。
- **单条失败不拖垮整批**（AGENTS §2.7）贯穿四个投影与重建路径。

## 二、S5 真实数据只读 dry-run 验收结果

脚本：`X-Bookmark-Knowledge-Automation/scripts/step5-dryrun`（可复跑；输出仅落临时目录）

| # | 检查项 | 结果 |
|---|---|---|
| C1 | 上游 JSONL → Canonical 校验通过 | ✅ 5/5 条 |
| C2 | 单条失败不拖垮整批（富化警告） | ✅ 0 条警告 |
| C3 | Canonical JSON 落盘 | ✅ 5 条，失败 0 |
| C4 | Markdown 投影 | ✅ 5 个 `.md`，冲突 0 |
| C5 | `rebuild-index` 建内容索引 | ✅ inserted=5 |
| C6 | 三处 `tweet_id` 集合一致（JSON / Markdown / SQLite） | ✅ 5 = 5 = 5 |
| C7 | `content_hash` 与 SQLite 逐条一致 | ✅ 5/5 |
| C8 | **幂等**：二次写入 0 写、SQLite 全 unchanged | ✅ json=0 md=0 sqlite=5 |
| C9 | **R6**：整库重建后运行态回初始态 | ✅ `NEW` / 0 / `NULL` |
| C10 | **只读保证**：真实 `data/`、`knowledge/` 指纹未变 | ✅ 29 / 14 个文件指纹前后完全相同 |

> 只读证明方式：对两个真实目录做「相对路径 + 大小 + `mtime_ns`」指纹，dry-run 前后各取一次并比对，
> 而非只看"我没写"的自述。

## 三、外部审计历史（Muse）

| 轮次 | 范围 | 结论 | 处理 |
|---|---|---|---|
| 1 | Step 1 | FAIL（4 findings：2 MEDIUM / 2 LOW） | F-001 批量异常隔离、F-004 保留设备名、F-002 证据、F-003 diff 完整性 → 全部修复 |
| 2 | Step 1 复审 | **PASS**（0 findings，哈希精确一致） | run 标记 `DONE` |
| 3 | Step 2 | PASS（1 LOW = F-005） | F-005 已修（轮 5 送审）；报告哈希字段录入损坏，已请求重发 |
| 4 | Step 3 | **PASS**（0 findings，哈希精确一致） | run 标记 `DONE` |
| 5 | Step 2 修复轮 | 待审 | — |
| 6 | Step 4 | 待审 | — |

审计发现的**真实缺陷**（非形式问题）：F-001（序列化异常逃逸致批内静默丢条目）、F-004（保留设备名）、
F-005（frontmatter 控制字符未转义）；另有两处审计**指出我方证据/打包缺陷**（F-002、F-003）与
若干协议不一致（哈希字段名、日志路径口径），均已修复。

## 四、如实说明的缺口（未解决 / 未覆盖）

1. **Step 5 的 dry-run 只覆盖 5 条真实书签**：样本量小，且未覆盖含 `x_article` / `quoted_tweet` /
   媒体的分支（当前数据里这些分支的实际覆盖有限）。
2. **未做真实落盘**：Phase 4 全程未写真实 `data/normalized/`、`knowledge/X-Bookmarks/`
   （按授权边界；真实落盘属 Phase 7 `process` 命令范围）。
3. **`tags`/`categories`/`engagement` 等 frontmatter 键未产出**：Canonical 契约中不存在这些字段，
   本 Phase 不编造（已在 S2 章节记录为差异）。
4. **`src/storage/` 与既有 `src/ingest`/`src/markdown`/`src/database` 并存**（R1 未决）：
   Phase 4 新增物未替换旧实现，旧测试 500+ 保持通过。
5. **两处既有测试断言被修改**（硬编码 schema 版本 → 引用 `SCHEMA_VERSION`/`MIGRATIONS`）：
   已在提交信息与审计包中显式披露，等 Muse 判定。

## 五、下一步

Phase 5（CLI）→ Phase 6（跨平台）→ Phase 7（Git 同步）→ Phase 8（Knowledge-Agent）。
Phase 5 前需先裁定 **S2（Collector Protocol 是否拆分）** 与 **R1（新旧模块关系）**。
