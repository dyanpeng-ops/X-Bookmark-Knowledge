# Phase 3 — Collector Adapter 预检评审（Preflight Review）

> 项目：X Bookmark Knowledge Pipeline
> 阶段：Phase 3 — Collector Adapter（开工前评审）
> 日期：2026-10-08
> 状态：**待老板确认 3 个决策点后进入 Step 3**

本文件依据任务书 §32 产出：先阅读（AGENTS/ARCHITECTURE/CURRENT/PLAN/schema/现有 canonical+collector+tests），再输出 Preflight Review。**未写代码、未联网、未碰真实数据、未改 Schema。**

---

## 一、架构理解（Step 1 结论）

权威链路：`AGENTS.md → ARCHITECTURE.md → CURRENT.md → PLAN.md → 任务书`。

Phase 3 只做一条数据链路，严格边界：只做 Collector / Contract / Normalizer / Validator，不碰 Storage / SQLite / Markdown / CLI / GitSync / Knowledge-Agent / 外链抓取。

目标数据流（任务书 §1）：

```text
Field Theory → Collector Adapter → RawCollectorData
             → Normalizer → CanonicalBookmark → Schema Validator
```

---

## 二、现状盘点（关键发现）

现有 `src/collector/` 里已有一套 **Phase 5 时代的实现**，与任务书要求**不匹配**：

| 现有代码 | 它做什么 | 与任务书的关系 |
|---|---|---|
| `collector/base.py` | 定义 `UpstreamBookmark`/`EnrichedBookmark`/`MediaManifest` + `Collector` Protocol | **直接建模 FT 的 snake_case 结构**，不是 `RawCollectorData` 契约 |
| `collector/contract.py` | 冻结 FT 字段契约（`bookmarks.jsonl` 的 camelCase 键） | 可复用（校验上游），但属"上游契约"非"项目契约" |
| `collector/fieldtheory_adapter.py` | `FieldTheoryAdapter`，读 JSONL/manifest/`list|show --json` | 可复用其读取逻辑，但产出 `UpstreamBookmark` 而非 `RawCollectorData` |

**核心矛盾**：任务书 §6 要求冻结 `RawCollectorData(collector, items, cursor)` + `RawBookmarkItem(tweet_id, payload)`，其中 `payload` 只保留 FT 原始 dict，FT-specific 字段"停在 payload、不进 Canonical"。但现有 `UpstreamBookmark` 把 FT 字段全展开成一等字段，等于让 FT 结构渗透进来。

`src/canonical/` 目前只有 `validate.py`（Phase 2 交付），**没有** `RawCollectorData`、没有 `CanonicalBookmark` dataclass、没有 `src/normalizer/`（目录不存在）。

---

## 三、架构检查 7 问（Step 2 结论）

1. **当前 Collector Interface 是否已存在？** 已存在 `collector.base.Collector` Protocol，但语义是 Phase 5 的 `read_bookmarks() -> Sequence[UpstreamBookmark]`，非 `collect() -> RawCollectorData`。**需新增** `collect()` 方法（复用 base，不重写第二套）。

2. **RawCollectorData 是否已存在？** **不存在**。需新建。

3. **CanonicalBookmark 结构？** 已由 `schema/bookmark.schema.json` 权威定义（12 必填键 + 6 可选键）。内存模型 dataclass 尚未建（见决策点 1）。

4. **FT 如何读取？** 已有 `FieldTheoryAdapter` 可读 JSONL + manifest + `list|show --json`（双源）。可复用。

5. **哪些字段可映射？** 见「五、字段映射表」。

6. **哪些字段不可映射？** 见「六、无法映射字段」。

7. **是否需改 Schema？** **否**。18 字段已覆盖，无需为 FT 改 Schema（任务书 §10 红线）。

---

## 四、RawCollectorData 契约设计（冻结）

完全遵循任务书 §6，不额外加字段：

```python
@dataclass(frozen=True)
class RawBookmarkItem:
    tweet_id: str
    payload: dict            # FT 原始 JSONL 记录（camelCase 原样保留）

@dataclass(frozen=True)
class RawCollectorData:
    collector: str           # "fieldtheory"
    items: tuple[RawBookmarkItem, ...]
    cursor: str | None = None   # 任务书 §6 有 cursor；本阶段 FT 无分页游标，传 None
```

关键决策：**`payload` 保留原始 camelCase dict**（不 snake_case 化），FT-specific 字段天然隔离在 payload 内，Canonical 层看不到。

---

## 五、字段映射表（Normalizer 核心）

| Canonical 字段 | FT 来源 | 转换规则 |
|---|---|---|
| `tweet_id` | `payload["tweetId"]` | str，直接透传 |
| `author` | `payload["author"]["name"]` | 显示名（决策 D2） |
| `author_id` | `payload["author"]["id"]` | str |
| `author_username` | `payload["author"]["handle"]` | handle（决策 D2） |
| `created_at` | `payload["postedAt"]` | `Sat Jun 20 12:56:42 +0000 2026` → UTC ISO-8601（复用 `parse_twitter_datetime`） |
| `text` | `payload["text"]` | 直接透传 |
| `url` | `payload["url"]` | 直接透传（`https://x.com/...`） |
| `conversation_id` | `payload["conversationId"]` | 可空 |
| `source` | 常量 `"x"` | 决策 D5，**不读** `ingestedVia`（它是 `graphql`） |
| `collector` | 常量 `"fieldtheory"` | 采集器标识 |
| `media` | `payload["mediaObjects"]` | `type/url/expandedUrl/width/height` → `mediaObject`（type 值 `photo` 在 MEDIA_TYPES 内，直接透传） |
| `external_links` | `payload["links"]` | str 数组 → URI 数组；**过滤** `x.com/i/article/...`（属 Article 引用非外链） |
| `x_article` | `EnrichedBookmark.article_*`（`list|show --json`） | `title`/`text`/`site`；需 Collector 先读富化再喂 Normalizer |
| `quoted_tweet` | `EnrichedBookmark.quoted_tweet` | 映射 `tweetId`→`tweet_id`、`authorHandle`→`author_handle`、`text` |
| `content_hash` | 由 Normalizer 计算 | SHA-256，覆盖实质内容字段（排除 metadata，§5.4） |
| `collected_at`/`updated_at` | 采集时刻 | Normalizer 填 UTC now 或上游 syncedAt（见决策点） |

---

## 六、无法映射字段（Schema Gap 清单）

| FT 字段 | 问题 | 处置 |
|---|---|---|
| `ingestedVia`/`sortIndex`/`textExpandedAt` | FT 专属，Canonical 无对应 | 留在 payload，**不映射**（正确行为） |
| `author` 的 `bio`/`followerCount`/`isVerified` 等 | Canonical 只有 author 三字段 | 留在 payload，不展开 |
| `engagement`（like/repost/reply/quote/bookmarkCount） | Canonical Schema **无** engagement 字段 | 记录 gap，不映射（任务书 §14 不扩张） |
| `tags`/`categories`/`domains`/`folders` | Canonical Schema 无 | 记录 gap，留 payload |
| `media`（字符串数组 `pbs.twimg.com/...png`） | 与 `mediaObjects` 重复，后者更完整 | 用 `mediaObjects`，忽略字符串数组 |
| `links` 里的 `x.com/i/article/...` | 是 Article 引用，非外链 | Normalizer 判定：`/i/article/` 归入 x_article 语义，不进 external_links |

> ⚠️ **需老板确认的 gap**：`engagement` 字段当前 Schema 完全没有，但真实数据里有（likeCount 等）。任务书 §14 说"无法表达则记录 gap，不为完整支持扩张 Schema"。建议本轮**不扩张 Schema、engagement 留 payload**，以后要入库再单独开 gap 决策。

---

## 七、可复用部分

| 可复用 | 说明 |
|---|---|
| `collector/contract.py` | 上游字段校验 + `parse_twitter_datetime`/`parse_iso_datetime` |
| `collector/fieldtheory_adapter.py` | `read_bookmarks`/`list_enriched`/`show_enriched`/`check_ready` 的读取与错误分类逻辑 |
| `collector/base.py` | 错误类型（`Upstream*Error`）+ `MediaEntry` 等 |
| `canonical/validate.py` | `validate_bookmark` 直接复用为 Validator |

---

## 八、预计新增/修改文件

**新增**：
- `src/collector/raw_data.py` — `RawCollectorData` + `RawBookmarkItem`
- `src/collector/fieldtheory_collector.py` — `FieldTheoryCollector`（实现 `collect() -> RawCollectorData`，复用 adapter 读数据）
- `src/normalizer/__init__.py` + `src/normalizer/fieldtheory.py` — `FieldTheoryNormalizer`
- `src/normalizer/errors.py` — `NormalizationError` 等（任务书 §16 要求错误分类）
- `tests/test_normalizer.py` — Test A–L 覆盖

**可能新增**（待你定）：
- `src/canonical/model.py` — `CanonicalBookmark` dataclass（若不建，normalizer 直接产 dict）

**不修改**：`schema/bookmark.schema.json`、`src/collector/contract.py`（冻结契约不动）、旧 `fieldtheory_adapter.py`（保留，不删）。

---

## 九、需老板拍板的 3 个决策点

1. **CanonicalBookmark 用 dataclass 还是 dict？**
   任务书 §15 说 Normalizer 输出后经 `validate.py` 验证，`validate.py` 收的是 `Mapping`。倾向 **Normalizer 产出 dict，Validator 收 dict**（与 Phase 2 已建 validate 无缝衔接），暂不建 dataclass。或你要更严谨的 dataclass 模型？

2. **`content_hash` 计算归属**：
   放 Normalizer 内部（任务书未明确），覆盖字段按 §5.4（tweet_id/text/url/author/media/external_links 等实质内容，排除 collected_at/updated_at/source/collector）。是否照此？

3. **旧 `FieldTheoryAdapter` 去留**：
   任务书 §22 说"优先复用 base，不重写第二套接口"。计划**保留 adapter 不动**，新建 `FieldTheoryCollector` 复用 adapter 的读取方法、包装成 `collect()`。但这样 `src/collector/` 里会同时存在 Phase 5 的 `fieldtheory_adapter.py`（产 `UpstreamBookmark`）和 Phase 3 的 `fieldtheory_collector.py`（产 `RawCollectorData`）。是否接受并存？还是把 adapter 的读取逻辑收敛进 collector？

---

## 附：Step 1 已读文件清单

- `tasks/PHASE-3-COLLECTOR-ADAPTER.md`（任务书，33 节）
- `AGENTS.md` / `ARCHITECTURE.md` / `CURRENT.md` / `PLAN.md`（权威链路）
- `schema/bookmark.schema.json`（18 字段 / 12 必填 / 3 $defs）
- `src/canonical/validate.py`（校验器）
- `src/collector/base.py` / `contract.py` / `fieldtheory_adapter.py`
- `tests/test_schema.py` / `tests/test_collector_fieldtheory.py`
- 真实样本 `data/upstream/bookmarks.jsonl`（5 条）+ `tests/fixtures/upstream/list.sample.json`（富化）

---

# 决策与修正记录（2026-10-08，老板批复后）

> 本节由实现阶段追加。预检结论已按老板批复与真实数据核对结果修正，**以本节为准**。
> 未写 `data/`、`knowledge/`、`config/`、`schema/`，未联网，未修改 Schema。

## 10.1 五项决策（已执行）

| # | 决策点 | 裁决 | 实现落点 |
|---|---|---|---|
| 1 | CanonicalBookmark 内存模型 | Normalizer **输出 dict**，直接喂 `validate_bookmark`；不建 `src/canonical/model.py` | `FieldTheoryNormalizer.normalize_item()` / `normalize_and_validate()` |
| 2 | `content_hash` 归属与覆盖范围 | Normalizer 内计算 SHA-256，**严格按 `ARCHITECTURE.md` §5.4 九项** | `compute_content_hash()` |
| 3 | 旧 `FieldTheoryAdapter` 去留与路径 | 新建 `src/collector/fieldtheory/` 包（任务书 §7 路径），旧 `fieldtheory_adapter.py` **保留不动**，注入式复用其读取逻辑 | `FieldTheoryCollector(adapter=...)` |
| 4 | 富化数据源（Article / quote） | 复用 `data/raw/{tweet_id}.json` 的 `enrichment` 块；**Collector 不执行上游 CLI**，Phase 3 采集路径完全离线 | `FieldTheoryCollector._read_enrichment()` |
| 5 | `collected_at` / `updated_at` | 取 `payload.syncedAt`（确定性） | `_timestamp()`；Test L 因此天然稳定 |

## 10.2 预检错误与遗漏的修正

| 编号 | 预检说法 | 修正 |
|---|---|---|
| E1 | Schema「18 字段 / 12 必填 / 6 可选」 | **19 属性 / 12 必填 / 7 可选**（多出 `conversation_id`、`quoted_tweet`、`reply_to`、`thread`、`x_article`、`collected_at`、`updated_at`） |
| E2 | `content_hash` 覆盖「…等」 | 九项确定清单：`tweet_id`+`text`+`url`+`author_id`+`created_at`+`media[]`有序+`external_links[]`有序+`quoted_tweet`+`x_article.text`；§5.4 出自 `ARCHITECTURE.md`（非任务书） |
| E3 | 「`collected_at` 填 now 或 syncedAt（见决策点）」但无对应决策 | 由决策 5 解决：一律 `syncedAt`；否则 Test L 必失败 |
| D1 | 路径 `src/collector/fieldtheory_collector.py` | 改为任务书 §7 的 `src/collector/fieldtheory/adapter.py` |
| D2 | `items` 用 tuple | 保留（**有意偏差**，见 §10.3） |
| D3 | 映射表漏 `reply_to` / `thread` | 显式写 `null` = 已记录 gap（FT 无此数据源） |
| M1 | 未提 `data/raw/{tweet_id}.json` | 定为富化数据源（决策 4） |
| M2 | 缺任务书 §32 的「两实现设计」「需授权操作」 | §八 补充文件清单；授权清单见实现前提交的「待执行清单 A/B」 |
| N1 | Article 过滤未定 scheme | scheme 无关（http+https），host 覆盖 `x.com` / `twitter.com` 及其 `www.`/`mobile.` 变体 |
| N2 | 未提外链重复 | 保序去重（真实数据 `https://cobalt.tools` 出现两次） |
| N3 | media type 仅 `photo` 实测 | `video`/`animated_gif` 按 Schema enum 支持，标注**待验证** |
| N4 | author 取 `author.*` | 采纳；`authorName`/`authorHandle` 作兜底，`author.id` 缺失即报错（不编造） |
| N5 | `conversation_id` | 透传（真实值 = tweetId） |
| N6 | 「Normalizer 计算 content_hash」看似复用 | 实为**新增能力**（`src/` 原先零实现，`data/normalized/` 不存在） |

## 10.3 与任务书 §6 的两处显式偏差

1. `RawCollectorData.items` 为 `tuple`（任务书写 `list`）——不可变更，利于幂等与测试。
2. `RawBookmarkItem` 增加可选字段 `enrichment`：Article 正文与被引用推文只存在于富化数据，
   必须跨过 Collector→Normalizer 边界。任务书 §6.1 措辞为「**至少**含 `tweet_id` + `payload`」，
   故允许；`payload` 本身仍是**未改动的上游原记录**。

## 10.4 实际交付文件

新增：`src/collector/raw_data.py`、`src/collector/fieldtheory/{__init__,adapter}.py`、
`src/normalizer/{__init__,errors,fieldtheory}.py`、`tests/test_raw_data.py`、
`tests/test_fieldtheory_collector.py`、`tests/test_normalizer.py`。

修改：`src/collector/base.py`（`Collector` Protocol 增 `collect()`，并 re-export `RawCollectorData`，+12 行）。

**未修改**：`schema/bookmark.schema.json`、`src/canonical/validate.py`、`src/collector/contract.py`、
`src/collector/fieldtheory_adapter.py`、`src/collector/__init__.py`（Phase 5 导出面保持冻结）。

## 10.5 验收结果（2026-10-08，全部离线）

| 项 | 命令 / 方式 | 结果 |
|---|---|---|
| 新模块单测 | `python -m unittest tests.test_raw_data tests.test_fieldtheory_collector tests.test_normalizer` | **127 用例全绿**（20 + 21 + 86；审核后为 128，见 §10.7），覆盖 Test A–L |
| 全量回归 | `python -m unittest discover -s tests -t .` | 524 用例，**9 失败**，全部位于 `tests/test_config.py` / `test_media.py` / `test_external.py` 的 Windows 路径语义断言，与本 Phase 文件无交集（归 Phase 6）。注：`tasks/CURRENT.md` 原记录为「11 失败」，数字与新基线不一致，需在 Phase 6 更新 |
| 真实数据只读验收 | `FieldTheoryCollector(data_dir=data/upstream, raw_dir=data/raw).collect()` → `normalize_and_validate()` | **5/5 RawBookmarkItem → 5/5 CanonicalBookmark → validate 全通过**；富化 5/5 命中；4 篇 Article；1 条媒体；1 条外链（原 2 条重复去重）；4 条 Article-only `links` 过滤后 `external_links = []`（符合预期） |
| 写盘影响 | `git status` | 未新增/修改 `data/`、`knowledge/`、`schema/`、`config/`；唯一被改的既有源码为 `src/collector/base.py` |

## 10.6 遗留 gap（记录，不在 Phase 3 修改）

- `engagement`（like/repost/…）Canonical 无字段 → 留 `payload`（任务书 §14）。
- `reply_to` / `thread` 无上游数据源 → 恒为 `null`。
- `quotedTweet` **形状待验证**：5 条真实样本与 fixtures 中均为 `null`，无实测非空样本；
  映射按字段名直译，形状不符即报 `NormalizationError`（不静默丢数据）。
- `video` / `animated_gif` media 未实测。
- 非绝对 URI 的外链被丢弃（无法满足 `format: uri`），属静默 gap。
- `Collector` Protocol 仍含写上游的 `sync()`；Phase 3 的 `FieldTheoryCollector` **故意不暴露** `sync`/`read_bookmarks`，
  未来可考虑拆出只读 Protocol（需架构决策，未自行改动）。
- `schema`（`additionalProperties: false`）与 `validate.py` 在 `quoted_tweet` / `x_article` 内部
  未知键上的宽松差异，属 Phase 2 遗留，本 Phase 未修改。
- **`content_hash` 对 `media` 元素键集合敏感**：Normalizer 恒输出
  `{type,url,expandedUrl,width,height}` 五键，故同内容哈希稳定；Phase 4 若自行构造 media 入口，
  必须复用同一形状，否则「同内容不同哈希」。
- **`src/normalizer` 的 import 闭包**会连带加载 Phase 5 适配器模块（见 §10.7 发现 1）；
  运行期无任何上游调用，彻底解耦需拆包（架构决策）。

## 10.7 第二轮独立审核记录（提交前）

审核方式（全部只读，不依赖首轮结论）：重读全部实现源码 + 4 项变异测试 + AST 静态边界检查 +
`schema` 键集合与 Normalizer 输出的交叉验证 + 真实数据端到端复验。

**结论：通过，可提交。**

| 检查 | 结果 |
|---|---|
| 变异测试（破坏实现看测试是否失败） | 4/4 被捕获：`content_hash` 恒常量→9 失败；Article 过滤失效→2；外链不去重→6；media 校验失效→9。**测试非空断言** |
| `schema.properties`（19）↔ Normalizer 输出键集合 | 完全相等；12 个必填全部存在；`mediaObject` 嵌套键集合与 `$defs` 完全一致 |
| 真实数据端到端复验（最终代码） | 5/5 items → 5/5 CanonicalBookmark，19 键齐备 |
| 全量回归 | 525 用例 / 9 失败，失败集与提交前基线一致（Windows 路径语义，归 Phase 6） |
| 是否存在 `isinstance(x, Collector)` 依赖 | 无（故 Protocol 增 `collect()` 不影响既有代码） |
| 敏感信息 | 待提交文件中仅出现 Cookie **字段名**（既有文档描述），无任何值；`config/config.yaml`、`data/`、`knowledge/*` 均被 ignore |

**发现与处置**

1. **import 闭包连带上游适配器**（真实、轻微）：`src/normalizer/*` 通过
   `from ..collector.base / ..collector.contract` 触发 `src.collector.__init__`，而后者立即
   `import FieldTheoryAdapter`（含 `subprocess`）。即 `import src.normalizer` 后
   `src.collector.fieldtheory_adapter` 已在 `sys.modules`。
   *影响*：仅是模块加载，不产生上游调用；不违反验收 F 的行为要求。
   *处置*：在 `fieldtheory.py` 模块文档中精确写明该残留与原因；不擅自改动 Phase 5 的
   `collector/__init__.py` 导出面（属架构决策）。
2. **原静态边界测试基于字符串扫描**（脆弱）：文档里出现 `subprocess` / `fieldtheory_adapter`
   等词就会误报（本次修正文档措辞时即触发）。*处置*：改为 **AST 分析**（只检查 import 与
   代码引用的 API 名，不看注释/文档），并**新增行为测试**——屏蔽
   `subprocess.run/Popen`、`os.system/fork`、`urllib.request.urlopen` 后完整链路仍跑通，
   作为「Normalizer 不读上游、不联网」的强证据。
3. 未发现字段映射错误、键集合漂移、写盘/联网行为或对既有 Phase 5 代码的破坏。

审核后用例数由 127 增至 **128**（`test_normalizer` 86 → 87）。

