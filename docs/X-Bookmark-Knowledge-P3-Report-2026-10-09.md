# X-Bookmark-Knowledge 项目开发进度报告

> **报告日期**：2026-10-09
> **仓库**：`git@github.com:dyanpeng-ops/X-Bookmark-Knowledge.git`（private）
> **分支 / HEAD**：`main` @ `6751452`（与 `origin/main` 同步，工作区干净）
> **报告范围**：跨平台改造 Phase 0 → Phase 3 的进度、交付物、验收证据、审计响应、遗留问题
> **数据边界**：本报告及仓库**不含**真实书签内容、媒体文件、SQLite 状态库与任何凭据
> （`data/`、`knowledge/*`、`config/config.yaml`、`.env*`、`*.db` 均被 `.gitignore` 排除）

---

## 1. 项目定位

把 X（Twitter）书签采集为本地原始数据，加工为逐条 Markdown 写入个人知识库，最终交由
Knowledge-Agent 做 AI 增强。**本项目只读取与本地归档，绝不修改 X.com 上的书签数据。**

目标分层数据流：

```text
X.com → FieldTheoryCollector → RawCollectorData
      → FieldTheoryNormalizer → CanonicalBookmark
      → Schema Validator → Canonical Data
      → （Phase 4 Storage）JSON / Markdown / SQLite 投影
```

核心架构主张：**Field Theory 只是一个可替换的 Collector 实现**，而不是项目的数据模型。
验收判据（任务书 §33）：*若明天完全删除 Field Theory，Canonical Data / Storage /
Knowledge-Agent 是否仍能存在？*

---

## 2. 总体进度

| Phase | 名称 | 状态 | 主要产物 |
|---|---|---|---|
| 0 | 架构审计 | ✅ 完成 | `docs/environment-report.md` |
| 1 | 架构设计 | ✅ 完成 | `ARCHITECTURE.md`（六层架构 + 决策 R1–R7） |
| 2 | Canonical Schema | ✅ 完成 | `schema/bookmark.schema.json` + `src/canonical/validate.py`（28 用例） |
| **3** | **Collector Adapter** | ✅ **完成（含审计修复）** | `src/collector/raw_data.py`、`src/collector/fieldtheory/`、`src/normalizer/`（133 用例） |
| 4 | Storage | ⏳ 待授权 | JSON / Markdown / SQLite 索引 + `rebuild-index` |
| 5 | CLI | ⏳ 待开始 | `xbk` 入口与命令对齐 |
| 6 | Cross Platform | ⏳ 待开始 | Windows + macOS 双平台验证、重建测试基线 |
| 7 | Git Sync | ⏳ 待开始 | Windows ↔ GitHub ↔ macOS |
| 8 | Knowledge-Agent | ⏳ 待开始 | 分类 / 摘要 / 标签 / 关联 / 问答 |

> 说明：Windows 时代的旧 Phase 0–9 记录（含已实现的外链抓取 Phase 9）保留为历史存档，
> 与新「跨平台改造」序列是两条独立时间线。

---

## 3. 当前阶段 Phase 3 交付与验收

### 3.1 交付物

| 文件 | 职责 |
|---|---|
| `src/collector/raw_data.py` | 冻结 Collector ↔ Normalizer 边界契约：`RawCollectorData(collector, items, cursor)`、`RawBookmarkItem(tweet_id, payload, enrichment=None)`、`RawDataContractError` |
| `src/collector/fieldtheory/adapter.py` | `FieldTheoryCollector.collect() -> RawCollectorData`：只读上游 JSONL + `data/raw/{tweet_id}.json` 富化快照；**不执行上游 CLI、不联网、不写盘** |
| `src/normalizer/fieldtheory.py` | `FieldTheoryNormalizer`（输出 CanonicalBookmark dict，固定 19 键）+ `compute_content_hash()`（`ARCHITECTURE.md` §5.4 九项） |
| `src/normalizer/errors.py` | `NormalizationError` + 任务书 §16 六类错误映射表 |
| `src/collector/base.py` | `Collector` Protocol 新增 `collect()`（+12 行，**唯一改动的既有源码**） |
| `tests/test_{raw_data,fieldtheory_collector,normalizer}.py` | 任务书 §18 Test A–L，共 **133 用例**（21 / 23 / 89） |

### 3.2 验收证据

| 项 | 结果 |
|---|---|
| Phase 3 单元测试 | **133 用例全绿**（离线、标准库 `unittest`、零新增第三方依赖） |
| 全量回归 | 530 用例 / **9 失败**，全部位于 `test_config` / `test_media` / `test_external` 的**平台语义**断言（macOS `/var`→`/private/var` 软链、盘符、机器环境变量），与 Phase 3 文件零交集 → 归 Phase 6 |
| 真实数据只读验收 | **5/5 RawBookmarkItem → 5/5 CanonicalBookmark → Schema 校验全通过**；富化 5/5 命中；4 篇 Article；1 条媒体；1 条外链（原 2 条重复已去重） |
| 边界验证 | 不写 `data/`、`knowledge/`、`schema/`、`config/`；未联网；未修改 Canonical Schema 与 Phase 5 既有代码 |
| 测试有效性 | 变异测试 4/4 被捕获（如 `content_hash` 恒常量 → 9 个用例失败），证明测试非空断言 |

> **证据可信度边界（须如实说明）**：真实数据验收依赖本机 `data/`（按设计不入库），
> 因此**无法从仓库独立复跑**；其余证据（单元测试、键集合交叉验证、边界扫描）仓库内可复现。

### 3.3 关键决策（经用户批准）

1. Normalizer **输出 dict**（不建 dataclass），与 Phase 2 校验器无缝衔接。
2. `content_hash` 由 Normalizer 计算，SHA-256，**严格按 `ARCHITECTURE.md` §5.4 九项**：
   `tweet_id` + `text` + `url` + `author_id` + `created_at` + `media[]`（有序）+
   `external_links[]`（有序）+ `quoted_tweet` + `x_article.text`；排除
   `collected_at`/`updated_at`/`collector`/`source`/`engagement`。
3. 旧 `fieldtheory_adapter.py` **保留不动**，新建 `src/collector/fieldtheory/` 包（任务书 §7 路径），注入式复用其读取逻辑。
4. 富化数据源 = 项目内 `data/raw/{tweet_id}.json` 的 `enrichment` 块 → **Phase 3 采集路径完全离线**。
5. `collected_at` / `updated_at` 取 `payload.syncedAt`（确定性，保证幂等 Test L）。

---

## 4. 代码与测试规模

| 项 | 数值 |
|---|---|
| `src/` Python 代码 | 8,751 行 |
| `tests/` 测试代码 | 6,451 行 |
| 全量测试用例 | 530 |
| Phase 3 新增用例 | 133 |
| 新增第三方运行时依赖 | **0**（仅标准库；本机 `.venv` 仅 `pyyaml`） |

---

## 5. 审计响应

### 5.1 第三方 Phase 3 独立审计（结论：通过）

审计提出 2 项严重级 + 8 项建议。经本机逐条实测，其中 **A1–A5 证实为真并已修复**：

| 编号 | 问题 | 处置 |
|---|---|---|
| **A1** | 非 UTF-8 富化快照抛出的 `UnicodeDecodeError` 穿透 `collect()`，**拖垮整批**，违反 AGENTS §2.7「单条失败不得拖垮整批」 | 捕获范围改为 `(OSError, ValueError)`，统一转 `UpstreamContractError`，由 `strict` 决定降级或抛错（+2 回归用例） |
| **A2** | `_iso_utc` 只认大写 `Z`，ISO-8601 合法的小写 `z` 被误拒 | 改为大小写不敏感（+1 用例） |
| **A3** | `tweet_id` 文档称「纯数字」但实现只校验非空 | 改文档为「非空稳定身份字符串」（容纳未来 SaveBox / X API / 人工导入），不加 `isdigit()`（+1 用例） |
| **A4** | `compute_content_hash`（公开 API）缺键时抛裸 `KeyError` | 前置校验，改抛 `NormalizationError`（+1 用例） |
| **A5** | `isinstance` 使用 `typing.Sequence` | 改用 `collections.abc.Sequence` / `Mapping` |

**仍待处理（已记录理由，未自行改动）**：

- **S2｜架构债务**：`FieldTheoryCollector` 只实现 `check_ready` + `collect`，未形式化满足
  `Collector` Protocol（故意不暴露会写上游的 `sync` / `read_bookmarks`）。当前靠鸭子类型、
  仓库内无 `isinstance(x, Collector)`，无实际破坏。**建议 Phase 4 开工前做架构决策**：
  拆 `ReadOnlyCollector` Protocol，或显式实现完整接口。
- **S1｜跨平台基线不存在**：本机 macOS 为 9 失败（平台语义）；第三方 Linux 沙箱复跑为
  3 失败 + 16 错误（其中 14 个 `test_external` 错误是沙箱 DNS 把 `example.com` 解析到
  `198.18.11.198`，触发 `netguard` **正确拦截**）。因此「N 个失败」**不能作为 Phase 4 的回归口径**，
  Phase 6 必须重建分类基线（网络敏感类 / 平台语义类 / 真实缺陷类）。
- A7：`quoted_tweet` 非空形状与 `video`/`animated_gif` media 待真实样本补测。

### 5.2 Phase 9（外链抓取）静态审计 —— 待用户决策，尚未修复

| 编号 | 结论 | 说明 |
|---|---|---|
| **SEC-01** | **真实**（结构性缺口） | `netguard` 解析并校验 IP 后，`urllib` 在连接时**再次独立解析**，无 IP 绑定 → 理论存在 DNS rebinding / TOCTOU 窗口。每跳重定向**已**重新校验（审计建议 3 已实现）。修复需改传输层（绑定已验证 IP + 保留 SNI/Host），属设计变更 |
| **CFG-01** | **真实**（配置一致性 bug，**非安全放宽**） | `LinkResolver` 默认分支构造 `HttpFetcher` 时漏传 `block_non_public_hosts` / `allow_hosts`，而这两个参数默认值恰是最严格侧；生产路径 `xbk links` 已正确传参。实际影响：白名单被忽略 → 合法自建服务误拦。**零测试覆盖**该分支 |
| **QA-01** | **成立** | `README.md` 的「最近一次通过：Ran 369 tests … OK」已过期；运行命令仍为 Windows 路径 `.\\.venv\\Scripts\\python.exe` |

---

## 6. 已知问题与遗留 gap

- **平台语义失败**：全量测试本机 macOS 9 失败，非代码缺陷，归 Phase 6（基线口径见 §5.1 S1）。
- **`engagement`**（like/repost 等）Canonical 无字段 → 留在 `payload`（任务书 §14：不为完整支持扩张 Schema）。
- **`reply_to` / `thread`** 无上游数据源 → 恒为 `null`，已记为 Schema gap。
- **`quoted_tweet` 非空形状待验证**：5 条真实样本与 fixtures 中均为 `null`；映射按字段名直译，
  形状不符即报 `NormalizationError`（**不静默丢数据**）。
- **`video` / `animated_gif`** media 未实测。
- **非绝对 URI 外链**被丢弃（无法满足 `format: uri`），属静默 gap。
- **`src/normalizer` 的 import 闭包**会连带加载 Phase 5 适配器模块（仅模块加载，运行期无上游调用；
  已加「屏蔽 subprocess/urlopen 后仍跑通」的行为测试作为证据）。
- **采集器失败策略**：`collect()` 对「原始 payload 缺失 / `RawBookmarkItem` 构造失败」**故意让整批失败**
  （仅富化环节做单条降级）——因为静默跳过会在 `items` 中丢失该 tweet，Phase 4 可能误判「该书签已不存在」
  而造成数据丢失；**宁可整批报错**。

---

## 7. 待决策事项（阻塞后续 Phase）

| # | 事项 | 影响 | 建议时点 |
|---|---|---|---|
| 1 | **S2**：拆分只读 `Collector` Protocol，或显式实现完整接口 | 防止 Phase 4/5 调用方踩 `isinstance` 坑 | **Phase 4 开工前** |
| 2 | **SEC-01**：是否实现「解析一次 → 绑定已验证 IP 连接」（保留 SNI/Host） | 外链抓取的 SSRF 加固完整性 | Phase 9 补验收时 |
| 3 | **CFG-01**：是否修 `LinkResolver` 默认分支传参（2 行 + 2 测试） | 配置一致性；白名单是否生效 | 与 SEC-01 同批 |
| 4 | **QA-01**：是否更新 README 过期测试声明与 macOS 运行命令 | 文档准确性 | 随时（低风险） |
| 5 | **Phase 9 状态**：CHANGELOG 记为「实现完毕、待验收」 | 按 AGENTS 不应在未验收阶段继续开发 | Phase 4 前 |

---

## 8. 数据与安全边界（合规声明）

- 所有网络请求均有 timeout / retry / 错误记录；外链抓取有非公网目标拦截与逐跳重校验。
- Cookie / OAuth Token / API Secret **不进 Git、日志、Markdown 产物**；文档中只出现字段名（是否存在），不出现值。
- 原始 X 数据（`data/upstream/`、`data/raw/`）与知识数据（`knowledge/`）严格分离，且**均不入库**。
- 采集层只读上游：不修改 `~/.fieldtheory`、`bookmarks.db`、`bookmarks.jsonl`，不修改 X 书签。
- 验证分级授权：运行测试 / 联网 / 写盘均先提交「待执行清单」并经用户批准后执行。

---

## 9. 提交记录（跨平台改造）

| 提交 | 说明 |
|---|---|
| `6751452` | fix(phase3)：修复第三方审计确认的 5 项问题（A1 违反 AGENTS §2.7） |
| `e039c0b` | docs：标记 Phase 2/3 已提交并记录提交前审核结论 |
| `498236a` | feat(phase3)：Collector Adapter — RawCollectorData + FieldTheoryNormalizer（含 Phase 2 交付物） |
| `bf740ca` | docs：记录真实数据迁移与 Phase 0-1 推送 |
| `63f8af7` | docs：同步 Python 解释器版本为 3.13.12（macOS 重建） |
| `da273c2` | docs：更新架构文档与当日工作日志 |

---

*本报告由项目开发方生成，内容与仓库 `docs/phase3-preflight-review.md` §10、`CHANGELOG.md`、
`PLAN.md`、`tasks/CURRENT.md` 一致；未实测结论均已标注。*
