# X-Bookmark-Knowledge 开发报告 · Phase 4 / Step 1

> **报告日期**：2026-10-09
> **循环轮次**：Cycle 2 — Phase 4（Storage）Step 1
> **提交**：`6a9c5c7`（已推送 `origin/main`）
> **上一轮**：Cycle 1 — 外链层审计待办关闭（`fb14bdc`）
> **本轮结论**：Step 1（Canonical JSON 投影）**实现完毕并自验通过**；另有一项待用户决策（R1）
> **数据边界**：未写真实 `data/`、`knowledge/`；未联网；无新增第三方依赖

---

## 1. 本轮范围

依 `tasks/PHASE-4-STORAGE.md`（本轮新建）实施 **Step 1：Canonical JSON 投影**。

目标数据流（本轮只做第一段）：

```text
CanonicalBookmark（Phase 3 已产出，内存 dict）
      └─→ data/normalized/{tweet_id}.json      ← 本轮
          （后续 Step 2–5：Markdown / SQLite 索引 / rebuild-index）
```

## 2. 交付物

| 文件 | 内容 |
|---|---|
| `tasks/PHASE-4-STORAGE.md` | Phase 4 任务书：5 个 Step、验收 A–H、边界、风险、与 S2 的关系澄清 |
| `src/storage/__init__.py` | Storage 层包（ARCHITECTURE §13 指定位置） |
| `src/storage/json_projection.py` | `write_canonical_json()` / `write_all_canonical_json()` / `normalized_path_for()` |
| `tests/test_storage_json.py` | 24 个用例 |

### 关键设计

1. **契约前置**：写盘前强制 `validate_bookmark`，磁盘上永远不存在非法 normalized JSON。
2. **原子写**：同目录临时文件 → `flush` + `fsync` → `os.replace`；异常路径清理临时文件
   （`data/` 与 Git 同步，半截 JSON 会污染跨设备同步，必须杜绝）。
3. **幂等**：目标文件 `content_hash` 与本次相同 → 不重写、不动 mtime。
4. **路径穿越防护**：`tweet_id` 来自不可信上游，拒绝 `/`、`\`、NUL、首字符 `.`、首尾空白。
5. **单条失败隔离**（AGENTS §2.7）：`write_all_canonical_json` 逐条 try/except，
   返回 `JsonProjectionReport`（`outcomes` + `failures`），单条坏数据不中断整批。
6. **序列化确定性**：`ensure_ascii=False` + `sort_keys=True` + 固定缩进 + 结尾换行，
   同一 bookmark 产生逐字节相同的文件（便于 Git diff 与跨设备比对）。

## 3. 验收证据（全部离线）

| 项 | 命令 / 方式 | 结果 |
|---|---|---|
| 单元测试 | `python -m unittest tests.test_storage_json` | **24/24 绿** |
| 测试有效性 | 变异测试 | **2/2 被捕获**：幂等读哈希失效 → 2 个用例失败；路径安全校验失效 → 15 个用例失败 |
| 端到端（真实数据**只读**） | 5 条 `data/upstream` + 富化快照 → Phase 3 管道 → 落盘**临时目录** | 5/5 规范化 → **5/5 落盘**；文件名 = `{tweet_id}.json`；样例 19 键 |
| **幂等实证** | 同批数据二次运行 | **0 写 / 5 跳过**（`unchanged=5`） |
| 全量回归 | `python -m unittest discover -s tests -t .` | **556 用例 / 9 失败**；失败集与上一轮**逐条一致**（平台语义，归 Phase 6）→ 零新增回归 |
| 边界 | `git status` / 目录检查 | 未写真实 `data/`、`knowledge/`；未联网；`requirements.txt` 未变 |

## 4. 待用户决策（本轮未自行决定）

**R1：`src/storage/` 与既有模块的并存 / 替换策略**

- 现状：`src/ingest/`、`src/markdown/`、`src/database/` 是 Windows 时代实现，消费
  `UpstreamBookmark` / raw JSON；Phase 4 的目标是消费 **CanonicalBookmark**。
- `ARCHITECTURE.md` §14 定义为「移 + 改」，但**未规定迁移顺序与回滚方式**。
- 两个选项：
  - **A（增量并存）**：新建 `src/storage/`，既有模块保持可用，逐步切换 → 不破坏既有 500+ 测试，
    但短期内有两套存储路径，需要明确的「谁是权威」说明。
  - **B（原地替换）**：直接改造 `src/ingest`/`src/markdown`/`src/database` → 最终结构更干净，
    但会大面积破坏既有测试与 CLI 行为，需要一次性完成并重写相关测试。
- 本轮已按 **A 的方向**落地（只新增 `src/storage/`，未动既有模块），因此该决策**尚未被锁定**；
  若选 B，`src/storage/` 可平滑并入既有模块。

## 5. 明确未做（避免误解）

- 未实现 Markdown 投影、SQLite 索引、`rebuild-index`（Step 2–5）
- 未改动 `src/markdown/`、`src/database/`、`src/ingest/`、`src/cli/`
- 未修改 `schema/bookmark.schema.json`（契约冻结）
- 未对真实 `data/normalized/` 落盘（需另行批准）
- 未处理 SEC-01 / S2（待用户决策）

## 6. 下一轮计划

1. **等待审计报告**（Drive「audit report」文件夹；截至本报告上传时仍只有 Phase 3 那份 20:18）。
2. 依审计结论修复/记录后，进入 **Step 2：Markdown 投影**
   （路径 `knowledge/X-Bookmarks/{YYYY}/{MM}/{YYYYMMDD}-{tweet_id}.md`、frontmatter 14 键、
   正文 `## Original Tweet` / `## AI Analysis` 两段式、不覆盖内容不同的既有文件）。

*本报告所有结论均附验证方式；未实测项与待决策项已显式标注。*
