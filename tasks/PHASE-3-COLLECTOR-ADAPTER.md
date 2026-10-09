# Phase 3 — Collector Adapter 实施任务书

> 项目：X Bookmark Knowledge Pipeline
> 当前阶段：Phase 3 — Collector Adapter
> 项目目标：建立与具体采集器解耦的 `Collector → RawCollectorData → CanonicalBookmark` 数据转换链路
> 执行对象：WorkBuddy / Cline / Codex
> 文档状态：Phase 3 开工任务书
> 日期：2026-10-08

---

## 1. 任务目标

本 Phase 的唯一核心目标：**把现有 Field Theory 上游数据安全、可验证地转换为项目自己的 CanonicalBookmark，而不让 Field Theory 的数据结构继续成为项目内部标准。**

目标数据流：

```text
Field Theory
      │ Collector Adapter
      ▼
RawCollectorData
      │ Normalizer
      ▼
CanonicalBookmark
      │ Schema Validator
      ▼
Canonical Data
```

本阶段完成后，应能够证明：Field Theory 只是一个 Collector 实现，而不是整个项目的数据模型。

未来可替换成：Field Theory / X API / SaveBox / 其他浏览器采集器 / 人工导入，而不改变：CanonicalBookmark / Storage / Knowledge-Agent / Markdown / SQLite Index。

---

## 2. 当前项目状态

- Phase 0：架构审计 — 已完成
- Phase 1：跨平台架构设计 — 已完成
- Phase 2：Canonical Schema — 已完成
- 当前：Phase 3 Collector Adapter — 开始实施

CURRENT.md 已明确 Phase 3 的工作：冻结 RawCollectorData 最小契约 → 实现 FieldTheoryCollector → 实现 FieldTheoryNormalizer → 通过 Canonical Schema Validator。

---

## 3. 权威文档优先级

```
AGENTS.md → ARCHITECTURE.md → CURRENT.md → PLAN.md → 本任务书
```

冲突时：不自行猜测、不直接修改架构、停止实施、列出冲突、请求用户确认。

PLAN.md 中 Windows 时代旧 Phase 记录仅属历史档案，不得据此重新设计当前架构。当前唯一有效路线：Phase 0 → 1 → 2 → **3（CURRENT）** → 4 → 5 → 6 → 7 → 8。

---

## 4. Phase 3 严格边界

### 4.1 必须完成

RawCollectorData、FieldTheoryCollector、FieldTheoryNormalizer、CanonicalBookmark 转换、Canonical Schema Validation、相关单元测试。

### 4.2 不得实现

Storage、SQLite 重构、Markdown Generator 重构、CLI 重构、Git Sync、Knowledge-Agent、AI 分类/摘要/标签、Embedding、RAG、知识图谱、外部 URL 抓取、新的 Scheduler、跨平台完整适配、新的 Collector。

即使发现这些部分有问题，只能「记录问题 → 写入 Phase 3 Review → 不在本 Phase 修改」，除非用户明确授权。

---

## 5. 核心架构原则

**R1 — Collector 可替换**：项目不得依赖 Field Theory 的内部数据模型。

- 正确：`FieldTheoryCollector → RawCollectorData`
- 错误：`FieldTheoryCollector → FieldTheoryBookmark → 整个项目继续使用 FieldTheoryBookmark`

---

## 6. RawCollectorData

Phase 3 首先冻结最小 Collector 输出契约：

```python
RawCollectorData(
    collector: str,
    items: list[RawBookmarkItem],
    cursor: str | None,
)

RawBookmarkItem(
    tweet_id: str,
    payload: dict,
)
```

核心原则：RawCollectorData 是 Collector 与 Normalizer 之间的边界，**不是项目的最终数据模型**。

### 6.1 RawBookmarkItem

必须至少含 `tweet_id` + `payload`。`tweet_id` 负责稳定身份；`payload` 保留 Collector 原始结构。Field Theory 可产生：

```json
{
  "tweet_id": "123456",
  "payload": {
    "text": "...",
    "author": {},
    "engagement": {},
    "mediaObjects": [],
    "...": "Field Theory specific fields"
  }
}
```

Field Theory-specific 字段只能停留在 `payload`，不能自动进入 Canonical Schema。

---

## 7. FieldTheoryCollector

实现位置：`src/collector/fieldtheory/adapter.py`

职责：`Field Theory → 读取/执行 → RawCollectorData`。负责调用 Field Theory、读取 JSONL、读取必要富化数据、获取 tweet_id、保留原始 payload、返回统一 RawCollectorData、报告 Collector 层错误。

不负责：AI 分类/摘要、标签、Embedding、Markdown、SQLite 最终数据模型、Knowledge-Agent、外链正文抓取。

---

## 8. Field Theory 数据来源

数据并非全在单一 JSONL：
- `bookmarks.jsonl` 含基础字段；
- Article 正文 / 分类 / 文件夹 / 被引用推文等富化信息需 `fieldtheory list --json` / `show --json`。

允许 `JSONL + list/show --json` 双源读取。但双源只是 FieldTheoryCollector 内部实现细节，**不得让 Canonical 层知道字段来自哪个源**。

---

## 9. FieldTheoryNormalizer

实现位置：`src/normalizer/fieldtheory.py`，职责 `RawCollectorData → CanonicalBookmark`。

- 9.1 字段映射（`FT tweet_id → CanonicalBookmark.tweet_id`）
- 9.2 类型归一化（时间/数字/None/空数组/URL/media/author → Canonical Schema 格式）
- 9.3 数据结构归一化（`FT author → Canonical author`，不原样暴露 FT 结构）
- 9.4 来源标记：`source = "x"`（不自造 `source = "fieldtheory"`；FT 是 Collector，数据来源是 X）

---

## 10. CanonicalBookmark

权威定义：`schema/bookmark.schema.json`（已完成，28/28 通过）。Phase 3 **不得为适配 FT 而修改 Schema**。字段无法映射 → 判断是否属 Canonical → 记录 gap → 停止 → 请求批准。

---

## 11. Author 映射规则

`author` = 显示名，`author_username` = X handle。例：`{ "author": "OpenAI", "author_username": "OpenAI" }`。不得因 FT 原始结构不同而改变语义。

---

## 12. Media

`media` 保持统一结构。FT 的 `mediaObjects` 只在 Normalizer 阶段转换，不得直接作 Canonical 字段。Canonical 层不得出现 FT 专属字段名。

---

## 13. External Links

`external_links` 保持项目统一结构。Phase 3 只做 `URL → external_links`，**不执行外部网页抓取**（属其他 Phase）。

---

## 14. Article / Quote / Thread

只在已有 FT 数据能可靠映射时映射，不为「完整支持」扩张 Schema。无法表达则记录 gap。

---

## 15. Validator

Normalizer 输出后必须经 `src/canonical/validate.py` 验证：

```text
RawCollectorData → Normalizer → CanonicalBookmark → validate → success/failure
```

禁止 Normalizer 直接写数据库。

---

## 16. 错误处理

至少区分：`CollectorUnavailable`、`CollectorAuthenticationError`、`CollectorContractError`、`CollectorTimeout`、`NormalizationError`、`CanonicalValidationError`。不要全包装成 `Exception`。

---

## 17. 不修改上游数据

Collector 只读 FT 数据。禁止修改 `~/.fieldtheory`、`bookmarks.db`、`bookmarks.jsonl`、删除媒体、修改 X 书签，除非明确授权。

---

## 18. 测试要求（Test A–L）

| Test | 内容 |
|---|---|
| A | 最小 RawCollectorData：collector/items/cursor 结构正确 |
| B | 单条 Bookmark：RawBookmarkItem → CanonicalBookmark，验证必填字段 |
| C | tweet_id 正确传递 |
| D | author / author_username 映射正确 |
| E | 时间：正常/不同格式/None |
| F | mediaObjects → media 正确转换 |
| G | URL → external_links 正确转换 |
| H | Article：用真实样本，不丢已能表达的信息 |
| I | Quote/referenced tweet：Schema 支持则测，不支持记录 gap |
| J | 缺失字段：删必填字段必须 validation failed |
| K | FT 特有字段：payload 可含，CanonicalBookmark 不得出现 |
| L | Idempotency：相同 RawCollectorData 重复 Normalization 结果稳定 |

---

## 19. 真实数据测试

代码完成后**不自行运行联网或写盘**，先输出「Phase 3 待验证清单」等批准：离线单元测试 / 读真实 bookmarks.jsonl / 读真实富化数据 / 生成 CanonicalBookmark / Schema validation / 是否写 data/normalized/ / 是否改现有数据。

---

## 20. 真实数据验收建议

获批后用真实数据（5 条 bookmark / 6 媒体 / 4 篇 Article）只读转换：

```text
Field Theory → 5 RawBookmarkItem → 5 CanonicalBookmark → 5 Schema validation passed
```

确认 tweet_id / author / author_username / text / created_at / media / external_links / source 正确。

---

## 21. 跨平台要求

Phase 3 起不得新增 Windows-only 设计。禁止 `"C:\\Users\\..."`、`Path("C:/...")`、`\\` 作业务路径分隔符，统一 `pathlib.Path`。`fieldtheory.cmd` 不得写死到整个项目，只存在于 FT Adapter 或配置层。

---

## 22. Collector Interface

若 `src/collector/base.py` 已存在，优先复用，不重新设计第二套接口：

```python
class Collector(Protocol):
    def collect(...) -> RawCollectorData: ...
```

若与 Phase 1 架构冲突：先报告，不直接删除重写。

---

## 23. 不得污染 Canonical 层

`src/canonical/` 不得依赖：fieldtheory、fieldtheory_adapter、bookmarks.jsonl、bookmarks.db、FT_DATA_DIR、fieldtheory.cmd。Canonical 层只能理解 CanonicalBookmark 与项目 Schema。

---

## 24. Normalizer 不得反向依赖 Collector

`Collector → RawCollectorData → Normalizer`。Normalizer 不得调用 FT，`FieldTheoryNormalizer(...)` 内部不得执行 `fieldtheory list/show`。所有上游读取必须在 Collector 完成。

---

## 25. Storage 解耦

Phase 3 不允许 Normalizer 直接写 SQLite/Markdown/Git。输出只能是 CanonicalBookmark；`CanonicalBookmark → Storage` 属 Phase 4。

---

## 26. CLI 解耦

Phase 3 不实现 `xbk sync/normalize/process`。测试走 unit/integration test，不提前设计 CLI。

---

## 27. 文件变更控制

- 允许：`src/collector/`、`src/normalizer/`、`tests/`、`docs/`；原则上可更新 CURRENT/PLAN/CHANGELOG 的 Phase 3 记录。
- 禁止无授权修改：`schema/bookmark.schema.json`（除非明确 gap 并先报告）。
- 禁止修改：`data/upstream/`、`data/raw/`、`data/state/`、`knowledge/`（除非获验证授权）。

---

## 28. 执行顺序

1. **Step 1 阅读**：AGENTS.md、ARCHITECTURE.md、CURRENT.md、PLAN.md、schema、validate.py、src/collector/、tests/test_schema.py
2. **Step 2 架构检查**：回答 7 问（当前 Collector Interface / RawCollectorData 是否已存在 / CanonicalBookmark 结构 / FT 如何读取 / 哪些字段可映射 / 哪些不可 / 是否需改 Schema）。需改 Schema → 立即停止。
3. **Step 3 冻结 RawCollectorData** + 测试
4. **Step 4 实现 FieldTheoryCollector**（`src/collector/fieldtheory/adapter.py`）
5. **Step 5 实现 FieldTheoryNormalizer**（`src/normalizer/fieldtheory.py`）
6. **Step 6 Schema Validation**
7. **Step 7 单元测试**（先列验证清单等授权）
8. **Step 8 Review**：停止，不进入 Phase 4，输出 Implementation Review

---

## 29. Phase 3 验收标准（A–J）

| 项 | 标准 |
|---|---|
| A | 存在 RawCollectorData、RawBookmarkItem |
| B | 存在 FieldTheoryCollector，能转 FT 数据 → RawCollectorData |
| C | 存在 FieldTheoryNormalizer，能转 RawCollectorData → CanonicalBookmark |
| D | CanonicalBookmark 能通过 schema 验证 |
| E | Canonical 层不依赖 FT |
| F | Normalizer 不读取 FT |
| G | Collector 不写 SQLite/Markdown/Knowledge/Git |
| H | 测试覆盖正常/异常/缺失/media/external_links/Article/author/timestamp/tweet_id/FT-specific payload |
| I | 无新增 Windows-only 核心代码 |
| J | 未修改 Schema（除非明确批准） |

---

## 30. Phase 3 完成后的目标架构

```text
X.com → FieldTheoryCollector → RawCollectorData → FieldTheoryNormalizer
      → CanonicalBookmark → Schema Validator → Canonical Data
```

之后 Phase 4 接 `Canonical Data → JSON/Markdown/SQLite Index`；Phase 8 接 `Canonical/Knowledge → Knowledge-Agent`。

---

## 31. 最终禁止事项

出现以下情况必须停止并报告：修改 Canonical Schema、修改 ARCHITECTURE 核心原则、改变 tweet_id 定义、让 Normalizer 调用 FT、让 Canonical 层依赖 FT、写真实数据、联网、修改 X 书签、修改 `~/.fieldtheory`、引入新第三方运行时依赖、改变 Python 主版本、提前实现 Storage/CLI/Knowledge-Agent。**不得自行做架构性决策。**

---

## 32. 给 Agent 的执行指令

不要直接写代码。先阅读（AGENTS/ARCHITECTURE/CURRENT/PLAN/schema/现有 canonical+collector+tests），再输出 **Phase 3 Preflight Review**（架构理解 / RawCollectorData 设计 / 两实现设计 / 映射表 / 无法映射字段 / Schema Gap / 可复用部分 / 预计新增与修改文件 / 需授权操作）。用户确认前不实施联网、写真实数据、改 Schema。完成后**立即停止**，输出 Completion Review，等下一阶段授权。

---

## 33. Phase 3 的核心判断标准

> 如果明天完全删除 Field Theory，项目的 Canonical Data、Storage、Knowledge-Agent 是否仍能继续存在？

YES → 解耦成功；NO → FT 仍渗透核心，需继续整改。

---

End of Phase 3 Task
