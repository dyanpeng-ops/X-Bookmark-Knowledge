# ARCHITECTURE — 跨平台架构设计

> 任务书 Phase 1 交付物。**只设计、不改代码、不实现 Collector。**
> 设计日期：2026-10-07。本文件**取代**旧版 `ARCHITECTURE.md`（旧版为 Phase 0–9 的 Windows-only 单平台架构）。
> 依据：《X-Bookmark-Knowledge 跨平台架构改造任务书》§3–§31，以及 `docs/CURRENT_ARCHITECTURE.md`（Phase 0 审计）。
> 本文件沿用 `research/architecture-decision.md`（ADR）中已获批准且不与任务书冲突的决策；冲突处以任务书为准（见 §10 冲突裁决）。

---

## 1. 设计目标与最高原则

任务书 §31 的架构原则是本设计的根本约束：

> **Collector 是可替换的，Canonical Data 是稳定的，Markdown 是可迁移的，SQLite 是可重建的，Knowledge-Agent 与数据采集完全解耦。**

最终目标不是「fieldtheory 的附属项目」，而是「跨平台的 X Bookmark Personal Knowledge System」，fieldtheory 只是当前最方便的 Collector 之一。

本设计必须同时满足任务书 §1 的 10 项最终要求（Windows/macOS 双平台、统一数据格式、Collector 可替换、fieldtheory 仅为 Adapter、不把上游内部结构当数据标准、SQLite 非同步主源、Markdown/JSON 为交换层、可替换任何 Collector、Agent 可直接用知识库、GitHub 私有仓库双机同步）。

---

## 2. 六层架构与边界

```text
                         X.com
                           │
                           ▼
        ┌─────────────────────────────────────────┐
        │ L1  Collector Layer（可插拔）             │
        │   FieldTheoryCollector / XApiCollector / │
        │   SaveBoxCollector / MockCollector       │
        └──────────────────┬──────────────────────┘
                           │  RawCollectorData（带 collector 标识）
                           ▼
        ┌─────────────────────────────────────────┐
        │ L2  Normalizer Layer（每个 Collector 一个）│
        │   FieldTheoryNormalizer / XApiNormalizer │
        │   ... → CanonicalBookmark                │
        └──────────────────┬──────────────────────┘
                           │  CanonicalBookmark（项目统一标准）
                           ▼
        ┌─────────────────────────────────────────┐
        │ L3  Canonical Data Layer（稳定标准）      │
        │   schema/bookmark.schema.json            │
        │   data/normalized/{tweet_id}.json        │
        └──────────────────┬──────────────────────┘
                           │
             ┌─────────────┼──────────────┐
             ▼             ▼              ▼
        ┌─────────┐  ┌──────────┐  ┌───────────┐
        │ Markdown │  │ JSON     │  │ SQLite    │
        │ 长期可读  │  │ 标准交换  │  │ 本地索引  │
        └────┬────┘  └────┬─────┘  └─────┬─────┘
             └─────────────┼─────────────┘
                           ▼
        ┌─────────────────────────────────────────┐
        │ L4  Knowledge Layer                      │
        │   knowledge/X-Bookmarks/**（Markdown +   │
        │   assets/）                              │
        └──────────────────┬──────────────────────┘
                           ▼
        ┌─────────────────────────────────────────┐
        │ L5  AI Agent Layer（后置、可选、只追加）    │
        │   搜索/读取/分类/摘要/关联/分析/问答        │
        └─────────────────────────────────────────┘
```

> 注：任务书 §3 的图把 Markdown/JSON/SQLite 画在 Canonical Data 与 Knowledge Layer 之间。本设计将其明确定义为 **L3 的三种投影**（见 §5），而非独立层——它们都是 Canonical Data 的不同存储形态。

---

## 3. L1 — Collector Layer

### 3.1 职责与边界

- **唯一职责**：从某个来源（fieldtheory / X API / SaveBox / 自研）获取 X 书签的**原始数据**。
- **不负责**：归一化、状态管理、Markdown、媒体本地化、外链解析。
- **不依赖**：数据库、知识库、AI。

### 3.2 统一接口

任务书 §4.1 要求 `collect()/sync()/get_status()/health_check()`。本设计定义协议（Python `Protocol`，与现有 `Collector` Protocol 对齐并扩展）：

```python
class Collector(Protocol):
    def collect(self) -> Sequence[RawCollectorData]: ...   # 获取一批原始书签
    def health_check(self) -> CollectorHealth: ...          # 可用性/认证态探测
    def status(self) -> Mapping[str, Any]: ...              # 上游自报状态（透传）
```

**关键变化（相对现状）**：`collect()` 返回 `RawCollectorData`，**携带 `collector` 标识**（如 `"fieldtheory"`），**不再返回 fieldtheory 专属的 `UpstreamBookmark`**。fieldtheory 的字段形状由 Normalizer 负责消化。

#### 3.2.1 ★ `RawCollectorData` 契约必须显式定义（审核补充，关键漏洞）

「Collector 可替换」的前提是**所有 Collector 输出同一种 `RawCollectorData`**。若只定义 Protocol 骨架、不定义 `RawCollectorData` 的字段契约，则 `MockCollector` / `XApiCollector` / `SaveBoxCollector` 无法按同一契约实现，`Normalizer` 的输入类型也悬空——「可替换」会退化为「换一个 Collector 就要改 Normalizer 签名」。

**决策（R7）**：`RawCollectorData` 采用**最小通用契约**，不要求任何 Collector 产出完整字段，只约定「有则填、无则空」的结构：

```text
RawCollectorData
├── collector: str                 # 标识（"fieldtheory" / "x_api" / ...）
├── items: Sequence[RawBookmarkItem]   # 本批原始书签
│     └── RawBookmarkItem
│         ├── tweet_id: str             # 全局唯一主键（必填，跨 Collector 通用）
│         └── payload: Mapping[str, Any] # 该 Collector 的原始载荷（字段形状由各自 Normalizer 消化）
└── cursor: Mapping[str, Any] | None     # 增量同步游标（可选，各 Collector 自定义）
```

**设计要点**：

1. **只冻结 `tweet_id` 一个跨 Collector 字段**，其余全部下沉到 `payload`（自由形状），由**对应 Normalizer** 消化成 Canonical。这样 fieldtheory 的 `authorHandle`/`postedAt` 等专属字段**只存在于 `fieldtheory/` 包 + `normalizer/fieldtheory.py`**，永不进入契约本身。
2. `cursor` 承载增量同步状态（如 fieldtheory 的 `lastSeenIds`/`stopReason`），但**每个 Collector 自定义其结构**，核心代码不解析——仅透传给「下次 collect」。
3. 契约的约束力落在 **Normalizer 的输出**（`CanonicalBookmark`，见 §5）而非 Collector 的输出——只要 Normalizer 能把 `payload` 转成合法 Canonical，上游再脏也能用。

> 这一契约在 Phase 3（Collector Adapter）实现时冻结为 `src/collector/base.py` 中的 dataclass，Phase 2 的 Schema 只需定义 Canonical，不依赖 `RawCollectorData`。

### 3.3 Collector 注册表

```text
src/collector/
├── base.py                 # Collector Protocol + RawCollectorData + CollectorHealth
├── registry.py             # 按 collector.type 查找实现（配置驱动）
├── fieldtheory/
│   ├── adapter.py          # FieldTheoryCollector（唯一 Phase 1 后先实现的）
│   └── contract.py         # 内部字段校验（降级为 fieldtheory 私有，不再是项目标准）
├── x_api/                  # 占位（未来）
├── savebox/                # 占位（未来）
└── mock/                   # 测试用 MockCollector
```

> **任务书 §5 落实**：fieldtheory 的 SQLite schema、文件路径、内部 metadata、JSON 格式、CLI 输出格式、Mac-specific storage、fieldtheory-specific IDs **全部封在 `fieldtheory/` 内**，不向外泄漏。`contract.py` 从「项目级契约」降为「fieldtheory adapter 内部校验」。
>
> **★ 边界修正（审核）**：Normalizer **不属于** Collector 包。`collector/` 只产出 `RawCollectorData`；把 Raw 转成 Canonical 的 `FieldTheoryNormalizer` 是 **L2 独立层**（见 §4），代码位于 `src/normalizer/fieldtheory.py`，**不**放在 `src/collector/fieldtheory/` 内——否则 L2 依赖 L1 包内部，与 §12「核心代码不依赖 fieldtheory 内部结构」冲突。

### 3.4 配置驱动

任务书 §21：

```yaml
collector:
  type: fieldtheory        # 未来可改 x_api / savebox / mock
  # fieldtheory 专属参数下沉到 collector.fieldtheory.*，核心代码不感知
```

`registry.py` 按 `collector.type` 加载对应实现，核心代码只面对 `Collector` 协议。

---

## 4. L2 — Normalizer Layer

### 4.1 职责

把 `RawCollectorData` 转为 `CanonicalBookmark`。**每个 Collector 配一个 Normalizer**（任务书 §7）：

```text
FieldTheory Raw → FieldTheoryNormalizer → CanonicalBookmark
X API Raw       → XApiNormalizer       → CanonicalBookmark
SaveBox Raw     → SaveBoxNormalizer    → CanonicalBookmark
```

最终三者输出**完全一致的 CanonicalBookmark 结构**。

### 4.2 位置与边界（★ 审核澄清）

Normalizer 是**独立于 Collector 的 L2 层**，代码位于：

```text
src/normalizer/
├── base.py          # Normalizer Protocol + 注册
└── fieldtheory.py   # FieldTheoryNormalizer：RawCollectorData → CanonicalBookmark
```

**职责边界**（与 L1 严格区分）：

| 层 | 输入 | 输出 | 是否感知上游格式 |
|---|---|---|---|
| L1 Collector | 上游（fieldtheory/X API/...） | `RawCollectorData`（带 `collector` 标识） | 是（封装在各自包内） |
| L2 Normalizer | `RawCollectorData` | `CanonicalBookmark` | 是（每个 Collector 一个，但输出统一） |
| L3 及以下 | `CanonicalBookmark` | — | **否**（只认 Canonical） |

关键点：**fieldtheory 的字段形状只存在于 `collector/fieldtheory/`（读）与 `normalizer/fieldtheory.py`（转）两处**，Canonical 层及其下游完全不知道 fieldtheory 的存在。

### 4.3 与现状的对应

现状把归一化逻辑写在 `fieldtheory_adapter.py` 的私有函数 `_to_bookmark()` / `_to_media_entry()` / `_to_enriched()`。改造后这些函数**迁移到 `src/normalizer/fieldtheory.py`**，输出从 `UpstreamBookmark` 改为 `CanonicalBookmark`。

---

## 5. L3 — Canonical Data Layer（核心，本次改造重点）

### 5.1 Canonical Data Model

任务书 §6。定义 `CanonicalBookmark`，`tweet_id` 为全局唯一主键（**不得用 fieldtheory 内部 ID**）。字段清单：

| 字段 | 类型 | 来源 | 说明 |
|---|---|---|---|
| `tweet_id` | str | 全部 | **全局唯一主键** |
| `author` | str | 全部 | 作者 handle（`@` 或纯名，待定） |
| `author_id` | str | 全部 | X 用户 ID |
| `author_username` | str | 全部 | 用户名 |
| `created_at` | str(ISO-8601) | 全部 | 发帖时间，统一 UTC ISO-8601 |
| `text` | str | 全部 | 正文 |
| `url` | str | 全部 | 推文 URL |
| `conversation_id` | str | 全部 | 会话 ID |
| `quoted_tweet` | dict \| null | fieldtheory 富化 | 被引用推文 |
| `reply_to` | str \| null | fieldtheory 富化 | 回复目标 |
| `thread` | list[str] \| null | fieldtheory 富化 | 线程 |
| `media` | list[dict] | 全部 | 媒体对象数组 |
| `external_links` | list[str] | 全部 | 外链 URL |
| `x_article` | dict \| null | fieldtheory 富化 | X Article 正文 |
| `source` | str | 全部 | 采集来源（`"x"`） |
| `collector` | str | 全部 | collector 标识（`"fieldtheory"`） |
| `collected_at` | str(ISO-8601) | 本项目 | 采集时间 |
| `updated_at` | str(ISO-8601) | 本项目 | 更新时间 |
| `content_hash` | str | 本项目 | 内容哈希（第二层去重） |

> **与任务书 §6 的差异说明**：任务书把 `author`/`author_id`/`author_username` 三者并列，但 X 实际语义中 `author`（显示名）与 `author_username`（handle）不同。本设计保留三者，但建议 Phase 2 定稿时明确 `author` = 显示名、`author_username` = handle（避免歧义）。

### 5.2 JSON Schema

任务书 §6/§10：`schema/bookmark.schema.json` 定义 `CanonicalBookmark`，Phase 2 落地 + 测试。这是**项目的权威数据契约**，取代现状的 `contract.py`。

### 5.3 Canonical JSON 落盘

任务书 §10：

```text
data/
├── raw/          # 上游原始数据（fieldtheory 格式，仅留档、不入 Git、非交换层）
├── normalized/   # ★ Canonical JSON：data/normalized/{tweet_id}.json（标准交换层）
├── state/        # SQLite 本地索引（可删除重建）
├── export/       # 导出产物（可选）
└── logs/
```

`normalized/{tweet_id}.json` 是**跨平台、跨工具的数据交换层**，符合 `schema/bookmark.schema.json`。

> **★ 边界澄清（审核）**：`CanonicalBookmark` 是**内存数据模型**（L3 的概念标准），`normalized/{tweet_id}.json` 是它的**一种持久化投影**（Storage 职责，见 §6.2），`schema/bookmark.schema.json` 是它的**契约定义**。三者关系：
>
> ```text
> schema/bookmark.schema.json   —— 定义「什么算合法 CanonicalBookmark」
>        │（校验）
> CanonicalBookmark（内存）       —— Normalizer 的输出，唯一权威数据形态
>        │（持久化）
> normalized/{tweet_id}.json     —— Storage 层落盘，与 Markdown / SQLite 平级的投影
> ```
>
> 因此 §2 架构图中 L3 与三种投影之间是「**模型 → 投影**」的关系，不是「L3 直接产生 JSON」。落盘动作统一由 Storage 层（§6）负责，避免「同一份 JSON 被 Canonical 层和 Storage 层重复声明」的边界歧义。

### 5.4 content_hash 定义（★ 审核补充，去重的关键）

任务书 §17 要求 `tweet_id`（第一层）+ `content_hash`（第二层）双重去重。**content_hash 必须明确覆盖范围**，否则两台机器对「内容是否变化」判断不一致：

| 项 | 值 |
|---|---|
| 算法 | SHA-256（十六进制字符串） |
| 覆盖字段 | `tweet_id` + `text` + `url` + `author_id` + `created_at` + `media[]`（有序）+ `external_links[]`（有序）+ `quoted_tweet`（若存在）+ `x_article.text`（若存在） |
| **不**覆盖 | `collected_at` / `updated_at` / `collector` / `source`（元数据，变化不应触发重处理）；`engagement`（互动数是流动的，不参与去重） |
| 语义 | 反映「**这条书签的实质内容**是否变化」，而非「采集时间是否变化」 |

> 理由：若 content_hash 包含 `collected_at`，则每次重新采集（即便内容未变）都会 hash 不同，导致跨设备同步时永远判定「内容已变」而重复处理，违背幂等。明确覆盖范围是跨设备去重正确性的前提。

---

## 6. L3 的三种投影（Storage 设计）

任务书 §8/§11 的核心：**Markdown 长期可读、JSON 标准交换、SQLite 本地索引可重建**。三者都是 Canonical Data 的投影，地位对等，不再有「唯一权威」。

### 6.1 Markdown（长期可读知识存储）

- 每条 Tweet 独立文件，路径 **`knowledge/X-Bookmarks/{YYYY}/{MM}/{YYYYMMDD}-{tweet_id}.md`**（见 §10 决策 D1）。
- frontmatter 含任务书 §9 要求字段（`collector`/`collected_at`/`content_hash` 等，见 §7）。
- 内容结构（任务书 §26）：`## Original Tweet`（原始内容，可恢复）+ `## AI Analysis`（AI 追加，分离）。

### 6.2 JSON（标准交换）

- `data/normalized/{tweet_id}.json`，符合 JSON Schema。
- 用于程序间交换、跨设备同步的载体（配合 Git，见 §8）。

### 6.3 SQLite（本地索引/缓存，可重建）

- 地位**降级**：从「唯一权威」改为「本地索引/搜索/缓存」。
- 表字段只存索引所需：`tweet_id` / `content_hash` / `path` / `status` / `indexed_at` / `collector` / `processing_status`。
- **必须实现 `rebuild-index`**：删除 SQLite 后，扫描 `normalized/*.json` + Markdown 即可重建（任务书 §11）。

```bash
python -m src.cli rebuild-index   # 或 xbk rebuild-index（见 §10 决策 D4）
```

#### 6.3.1 ★ 可重建范围必须分清「内容」与「运行态」（审核补充，关键漏洞）

现状 `models.py` 的 `bookmarks` 表存有大量**运行时状态字段**：`status` / `attempts` / `first_synced_at` / `last_synced_at` / `error_message`，以及 `media.download_status` / `external_links.fetch_status`。这些字段**不在** `normalized/*.json` 或 Markdown 中（`content_hash` 按 §5.4 明确排除元数据）。

若 `rebuild-index` 只扫「normalized + Markdown」，则**只能重建出「有哪些书签」，重建不出处理状态、重试计数、错误信息、媒体下载状态、外链抓取状态**——「SQLite 完全可重建」的承诺在此落空。

**决策（R6）**：把 SQLite 字段分为两类，重建语义不同：

| 类别 | 字段 | 重建来源 | 丢失后果 |
|---|---|---|---|
| **内容索引** | `tweet_id` / `content_hash` / `path` / 可搜索的 `tweet_text`/`username`/`author_name` | `normalized/*.json`（+ Markdown） | 不可丢失 |
| **运行态** | `status` / `attempts` / `error_message` / `first_synced_at` / `last_synced_at` / `media.download_status` / `external_links.fetch_status` | **无重建来源，重建时重置为初始态** | 可接受（详见下） |

**运行态丢失的语义**：

- 重建后所有书签 `status` 重置为初始态（如 `NEW`），后续 `sync`/`process`/`media`/`links` 靠 `content_hash` 幂等判断「内容未变即跳过」，因此**不会重复处理**，只是状态机从头走一遍。
- `error_message` / `attempts` 清零：重试计数与历史错误是排障辅助信息，非权威数据，丢失不影响知识正确性。
- `media.download_status` / `external_links.fetch_status` 重置为 `PENDING`：媒体与正文**文件本身**在 `assets/`（入 Git）不受影响；状态字段只是「要不要重拉」的标记，重置后 `media`/`links` 命令会按 `content_hash`/本地文件存在性跳过已存在文件，**不产生重复抓取**（幂等由文件存在性保证，不依赖状态字段）。

> **约束**：Phase 4 实现 `rebuild-index` 时必须显式区分这两类字段，且**运行态字段的「重建=重置」语义要写进命令帮助与文档**，避免用户误以为「重建后处理进度丢失」是 bug。这是「SQLite 可重建」正确性的前提。

#### 6.3.2 字段清单修正

§6.3 首段的索引字段清单（`tweet_id/content_hash/path/status/indexed_at/collector/processing_status`）与 `models.py` 实际字段不一致。以 **§6.3.1 的两类划分为准**：内容索引字段以 `normalized` 为准，运行态字段属于「可丢失」的本地缓存。Phase 4 定稿表结构时统一对齐，本设计不再单独罗列「索引字段清单」。

---

## 7. Markdown Frontmatter 对齐

任务书 §9。目标 frontmatter（在现有 13 键基础上补齐）：

```yaml
---
tweet_id: "123456789"
author: "username"
author_name: "Author"
created_at: "2026-09-01T10:00:00Z"
source: "x"
collector: "fieldtheory"      # ★ 新增：仅记录来源，不构成依赖
collected_at: "2026-10-07T10:00:00Z"   # ★ 新增
content_hash: "..."           # ★ 新增：内容变化检测
tags: []
categories: []
---
```

- `collector: fieldtheory` 只是元数据，**Markdown 格式不依赖 fieldtheory**。
- 现有 `engagement`/`media_count`/`link_count`/`primary_category`/`folder_names` 等键保留（作为扩展键）。

---

## 8. 跨设备同步设计（任务书 §15/§16/§24/§25）

### 8.1 同步机制

```text
Windows                          Mac
   │  Markdown + normalized JSON  │
   └────────── Git ───────────────┘
            GitHub Private Repo
```

**正确链路**（任务书 §16）：

```text
Canonical Data（normalized/*.json + Markdown）
      ↓ Git Sync
GitHub Private Repository
      ↓
Local SQLite Index（每台机器各自 rebuild-index）
```

**禁止**：SQLite 文件经 Git 跨机同步。

### 8.2 `.gitignore` 重新设计

**应该 Git 同步**：`schema/`、`src/`、`config/`（含 example）、`scripts/`、`data/normalized/`（Canonical JSON）、`knowledge/X-Bookmarks/**/*.md`（Markdown 正文）。

**不应该 Git 同步**：cookies / session / OAuth token / API key / browser profile / fieldtheory 凭据 / `data/raw/`（上游原始） / `data/state/*.db` / SQLite 锁文件 / 临时文件 / logs / cache。

### 8.2.1 ★ 媒体资产（assets/）的同步策略（审核补充，关键缺口）

原设计未定义 `knowledge/X-Bookmarks/**/assets/**`（图片/视频）的同步归属，这是跨设备同步的**实际漏洞**——若媒体不入 Git，Mac 端 Markdown 里 `![](assets/...)` 引用会断裂；若盲目入 Git，大文件会让仓库膨胀。

**决策**：

| 方案 | 适用 | 取舍 |
|---|---|---|
| **媒体入 Git**（`knowledge/X-Bookmarks/**/assets/**` 跟踪） | 默认 | Markdown 引用自洽、Mac 端直接可用；需 `media.download_video: false` 控制体积 + 可选 Git LFS |
| 媒体不入 Git（仅 Markdown，媒体走 `media` 命令在每台机器重新本地化） | 体积敏感 | 仓库小，但 Mac 端需先运行 `media` 补拉媒体，Markdown 引用短暂断裂 |

**本设计默认采用「媒体入 Git」**，理由：
1. 满足任务书 §30「Markdown 可迁移」「Mac → Windows 正常」——知识库必须自包含，不能依赖「另一台机器先跑 media」。
2. 现有 `media.download_video: false`（视频不入库）已控制体积；`content_hash` 幂等保证媒体不重复提交。
3. 若未来体积失控，降级为「媒体不入 Git + 每机 media 重建」，是**可逆**的一行 `.gitignore` 改动。

> **同步完整性约束（审核补充）**：跨设备同步的**最小可用集**是「normalized JSON + Markdown + assets」，三者缺一不可：
> - 只有 normalized 无 Markdown → Mac 端需重跑 `process`（可接受，但非「即开即用」）；
> - 只有 Markdown 无 assets → 媒体引用断裂；
> - 只有 normalized 无 assets → 媒体数据丢失，`media` 无法从上游恢复（上游可能已清缓存）。
>
> 富化数据（article 正文、quoted_tweet）**只存在于 normalized JSON**，`data/raw/` 不含富化且不入 Git。因此 normalized 是富化内容的**唯一跨设备载体**，必须完整同步，否则 Mac 端重建会静默丢失富化内容。

### 8.3 冲突原则（任务书 §24/§25）

- 每条 Tweet 独立文件 → 最小化两台机器改同一文件的概率。
- 冲突判定优先 `tweet_id` + `content_hash`（content_hash 覆盖范围见 §5.4）。
- AI 修改与原始采集数据**物理分离**（`raw/` 原始 → `normalized/` 标准化 → `knowledge/` 知识），AI 绝不改原始 Tweet。
- **新增：AI 附加内容与原始内容同文件、不同段**（任务书 §26），冲突时以 `tweet_id`+`content_hash` 判定原始部分，AI 段采用「后写覆盖」（AI 输出可重生成，非权威数据）。

---

## 9. 状态机扩展（任务书 §18）

现状 6 态 `NEW → COLLECTED → PROCESSED → ENRICHED → COMPLETED`（+`FAILED`）。任务书要求 7 态：

```text
NEW → COLLECTED → NORMALIZED → STORED → PROCESSED → ENRICHED
                                                        ↓
                                                      FAILED（任意非终态可入，可重入）
```

新增 `NORMALIZED`（归一化完成）、`STORED`（三种投影落盘完成）。幂等要求不变：任何一步失败可重跑，同状态写为无操作。

---

## 10. 冲突裁决与待决策项

### 10.1 任务书与现状/ADR 的冲突点

| # | 冲突 | 裁决 |
|---|---|---|
| X1 | ADR 定「SQLite 唯一权威」 vs 任务书「SQLite 仅本地索引」 | **以任务书为准**，SQLite 降级 |
| X2 | ADR 定「fieldtheory 字段契约为项目标准」 vs 任务书「不得以上游内部结构为标准」 | **以任务书为准**，引入 Canonical 模型 |
| X3 | ADR 定「Windows Task Scheduler」 vs 任务书「跨平台」 | **以任务书为准**，调度平台化（Phase 6 处理，不阻塞 Phase 1） |
| X4 | ADR 定「`.venv\Scripts\python.exe` / `fieldtheory.cmd`」 vs 任务书「禁硬编码路径」 | **以任务书为准**，用 `pathlib` + 平台抽象 |

### 10.2 待决策项（Phase 1 需老板拍板，我给出推荐）

| # | 决策点 | 我的推荐 | 理由 |
|---|---|---|---|
| D1 | Markdown 布局 | **保留 `YYYY/MM/YYYYMMDD-{tweet_id}.md`**（不采用任务书 §8.1 的纯 `{tweet_id}.md` 平铺） | 任务书 §24 要求「每条独立文件」已满足；按日期分组便于浏览、避免单目录数千文件；任务书 §8.1 是「建议」非「强制」 |
| D2 | `author` 字段语义 | `author` = 显示名，`author_username` = handle | 消除任务书 §6 的三字段歧义 |
| D3 | 旧数据迁移 | 提供一次性迁移脚本：`data/raw/*.json`(fieldtheory) → `normalized/*.json`(canonical) → rebuild-index | 见 §11 |
| D4 | CLI 入口 | **Phase 1 保留 `python -m src.cli`**，`xbk` 入口延后到 Phase 5 引入（entry point） | 避免 Phase 1 就动打包/入口，聚焦架构；命令名语义对齐任务书 §20 |
| D5 | `source` 字段值 | `source: "x"`（任务书 §9）替代现状 `source: graphql` | 语义对齐；`graphql` 是 fieldtheory 内部采集途径，应封在 collector 层 |

---

## 11. 旧数据迁移方案（任务书 §32 要求先说明再执行）

**问题**：现有 `data/raw/{tweet_id}.json` 是 fieldtheory 格式，`data/state/state.db` 是 fieldtheory 语义的 schema v2。改造后需迁到 Canonical 模型 + `normalized/` + 新 SQLite 索引。

**原因**：Canonical 模型字段与 fieldtheory 形状不同（新增 `collector`/`content_hash`/`x_article` 等），SQLite 表结构需重新投影。

**修改方案**：
1. 保留 `data/raw/`（fieldtheory 原始）不动，作为迁移源。
2. 迁移脚本逐条：`raw/{tweet_id}.json` → 经 `FieldTheoryNormalizer` → `normalized/{tweet_id}.json`。
3. 生成 `content_hash` 并写回。
4. 重建 SQLite 索引（`rebuild-index`）。

**影响范围**：仅 `data/` 内部（`raw/` 只读、新增 `normalized/`、重建 `state/`）；`knowledge/` 的 Markdown 需补 frontmatter 键（`collector`/`collected_at`/`content_hash`）。

**迁移方式**：一次性 CLI 子命令（如 `migrate-v2`），幂等、可重复、失败可重跑。

> 此方案在 Phase 4（Storage）实施时细化，Phase 1 仅立项说明。

---

## 12. 分层依赖方向（约束）

```text
cli        → collector, normalizer, storage, markdown, external, database, scheduler
normalizer → collector（RawCollectorData）, schema（CanonicalBookmark）
storage    → schema, database, markdown
database   → 标准库 only（保持现状的纯净存储定位）
collector  → 各自上游（fieldtheory/x_api/savebox），不依赖 database
```

**禁止**：
- 任何模块 → `cli`（无反向引用）
- `database` → 业务逻辑或任何 collector
- 核心代码 → fieldtheory 内部结构（只能经 `fieldtheory/` 包 + Normalizer）
- 任何模块 → 写上游目录 / 写项目外路径

---

## 13. 目录结构（目标态）

```text
X-Bookmark-Knowledge/
├── schema/
│   └── bookmark.schema.json       # ★ CanonicalBookmark 权威契约（Phase 2）
├── src/
│   ├── collector/                 # L1：base.py + registry.py + fieldtheory/ + x_api/ + mock/
│   ├── normalizer/                # L2：各 collector 的 Normalizer（fieldtheory.py 等）
│   ├── canonical/                 # L3：CanonicalBookmark 内存模型 + schema 解析
│   ├── storage/                   # L3 三种投影的落地：markdown/json/sqlite-index
│   ├── database/                  # SQLite 本地索引（降级后，可重建）
│   ├── media/                     # 媒体本地化（复用现有，输入经 normalizer）
│   ├── external/                  # 外链解析（复用现有，独立）
│   ├── markdown/                  # Markdown 渲染（复用现有，frontmatter 对齐）
│   ├── scheduler/                 # 跨平台调度封装
│   └── cli/                       # 统一入口
├── data/
│   ├── raw/                       # 上游原始（fieldtheory，不入 Git）
│   ├── normalized/                # ★ Canonical JSON（入 Git，交换层）
│   ├── state/                     # SQLite 索引（不入 Git，可重建）
│   ├── export/                    # 导出
│   └── logs/
├── knowledge/
│   └── X-Bookmarks/               # Markdown + assets（入 Git）
├── config/
│   ├── default.yaml               # 跨平台默认（任务书 §13）
│   ├── windows.yaml               # Windows 平台差异（尽量少）
│   └── macos.yaml                 # macOS 平台差异（尽量少）
└── tests/
    ├── unit/
    ├── integration/
    └── cross_platform/            # 任务书 §23：跨平台测试
```

> 注：任务书 §13 建议 `config/{default,windows,macos}.yaml`。本设计认同，但强调**平台差异最小化**、集中在 `platform/` 抽象模块；实际落地时若差异极少，可仅保留 `default.yaml` + 运行时探测，Phase 6 定稿。

---

## 14. 与现状的映射（改造范围总览）

| 现状模块 | 目标去向 | 改动类型 |
|---|---|---|
| `src/collector/base.py` | `src/collector/base.py`（扩展 Protocol + RawCollectorData） | 改 |
| `src/collector/contract.py` | `src/collector/fieldtheory/contract.py`（降级为内部） | 移 + 改 |
| `src/collector/fieldtheory_adapter.py` | `src/collector/fieldtheory/adapter.py`（Adapter）+ `src/normalizer/fieldtheory.py`（Normalizer，L2 独立） | 拆 + 改 |
| `src/database/models.py`/`schema.py` | `src/database/`（按 Canonical 投影重写表） | 改 |
| `src/ingest/ingest.py` | `src/storage/`（消费 Canonical，不再消费 UpstreamBookmark） | 移 + 改 |
| `src/markdown/` | `src/markdown/`（frontmatter 对齐 Canonical） | 改 |
| `src/media/` | `src/media/`（输入经 normalizer） | 微改 |
| `src/external/` | `src/external/`（零改造复用） | 不动 |
| `src/config.py` | `src/config.py`（`collector.type` 驱动 + 平台抽象） | 改 |
| `src/cli/` | `src/cli/`（命令对齐 + rebuild-index + 迁移命令） | 改 |
| 无 | `schema/bookmark.schema.json` | 新增 |
| 无 | `src/normalizer/`、`src/storage/`、`src/canonical/` | 新增 |

---

## 15. 实施顺序（对应任务书 §29）

| Phase | 内容 | 状态 |
|---|---|---|
| 0 审计 | `docs/CURRENT_ARCHITECTURE.md` | ✅ 完成 |
| 1 架构设计 | **本文档** | ✅ 完成 |
| 2 Schema | `schema/bookmark.schema.json` + 测试 | ⏳ |
| 3 Collector Adapter | `FieldTheoryCollector → CanonicalBookmark`（含 Normalizer） | ⏳ |
| 4 Storage | Markdown / JSON / SQLite Index + `rebuild-index` | ⏳ |
| 5 CLI | `xbk` 入口 + 命令对齐 | ⏳ |
| 6 Cross Platform | Windows + macOS 验证 | ⏳ |
| 7 Git Sync | Windows↔GitHub↔Mac | ⏳ |
| 8 Knowledge-Agent | 分类/摘要/标签/关联/问答 | ⏳ |

> **Phase 1 边界声明**：本阶段只产出架构设计，**不实现 Collector、不写 `schema/`、不建 `normalizer/`、不改任何代码**。Phase 2 起才进入实现。

---

## 16. 完成标准（任务书 §30，逐条对照）

### 架构
- [ ] Collector 与 Knowledge Layer 解耦 —— 本设计 §2/§3 定义边界
- [ ] Field Theory 只是 Adapter —— §3.3 落实
- [ ] 有 Canonical Data Model —— §5.1
- [ ] 有 JSON Schema —— §5.2（Phase 2 落地）

### 跨平台
- [ ] Windows 可运行 / macOS 可运行 —— Phase 6
- [ ] 无硬编码路径 —— §3.4/§10 X4
- [ ] 平台差异集中管理 —— §13 `platform/` + config 分层

### 数据
- [ ] Markdown 长期可读 / JSON 标准交换 / SQLite 本地索引 —— §6
- [ ] SQLite 可删除重建 —— §6.3 `rebuild-index`

### 同步
- [ ] GitHub Private 可同步 / Windows↔Mac / 不同步凭据 —— §8

### Collector
- [ ] fieldtheory 正常 / 可替换 / 核心不依赖其内部 DB —— §3/§5

### Agent
- [ ] Codex/Cline 可读知识库 / Agent 不依赖具体 Collector / AI 与原始分离 —— §6.1/§8.3

---

## 附录：本文件对任务书 §31 原则的落地对照

| 任务书原则 | 本设计落地位置 |
|---|---|
| Collector 可替换 | §3（Protocol + registry + 配置驱动） |
| Canonical Data 稳定 | §5（CanonicalBookmark + JSON Schema） |
| Markdown 可迁移 | §6.1（独立文件 + 跨设备 Git 同步） |
| SQLite 可重建 | §6.3（rebuild-index） |
| Knowledge-Agent 与采集解耦 | §2（L5 只依赖 L4，不依赖 L1/L2） |

---

## 附录 B：Phase 1 审核修订记录（2026-10-07）

本轮审核聚焦职责边界 + 跨设备同步，修复 4 处漏洞，**未改代码**。架构决策如下：

| # | 决策 | 说明 |
|---|---|---|
| R1 | **Normalizer 定位为独立 L2 层**，代码住 `src/normalizer/`，不放 `src/collector/fieldtheory/` 内 | 修正 §3.3/§4/§13/§14 四处不一致；否则 L2 依赖 L1 包内部，违反「核心代码不依赖 fieldtheory 内部结构」 |
| R2 | **Canonical 层与 Storage 层边界澄清**：`CanonicalBookmark`（内存模型）→ `schema/*.json`（契约）→ `normalized/*.json`（Storage 投影），落盘由 Storage 层统一负责 | 消除「同一份 JSON 被 Canonical 层和 Storage 层重复声明」的歧义 |
| R3 | **媒体资产（assets/）默认入 Git**，构成「normalized + Markdown + assets」三件套的完整同步集 | 修复跨设备同步缺口：媒体不入 Git 会导致 Mac 端 Markdown 引用断裂、富化内容丢失；体积由 `download_video:false` 控制，可逆降级 |
| R4 | **content_hash 定义明确化**：SHA-256，覆盖实质内容字段，排除 `collected_at`/`engagement` 等元数据 | 修复去重漏洞：否则每次重采集 hash 都变，跨设备永远误判「内容已变」 |
| R5 | **AI 段冲突策略**：原始段以 `tweet_id`+`content_hash` 判定，AI 段「后写覆盖」（可重生成、非权威） | 补齐任务书 §25「AI 与原始分离」在跨设备冲突场景下的具体裁决 |
| R6 | **SQLite 字段二分**：内容索引（`tweet_id`/`content_hash`/`path`/可搜索字段）可重建；运行态（`status`/`attempts`/`error_message`/`*_at`/`*_status`）重建时重置为初始态 | 修复「SQLite 完全可重建」承诺与 `models.py` 实际运行态字段冲突：运行态无重建来源，丢失可接受（幂等由 content_hash/文件存在性保证） |
| R7 | **定义 `RawCollectorData` 最小通用契约**：只冻结 `tweet_id` + `payload`（自由形状）+ `cursor`（透传） | 修复「Collector 可替换」的前提空缺：没有统一输出契约，换 Collector 就要改 Normalizer 签名 |

---

## 附录 C：架构验收审计记录（2026-10-07）

对照任务书 §30「完成标准」的 6 项硬指标，逐条核对「设计文档声称」与「代码现状」的落差。**结论：6 项指标在设计文档全部达标，但代码全部零实现（Phase 2 起才落地），其中 2 处是设计本身的漏洞，已在 §3.2.1 / §6.3.1 修复。**

| # | 验收指标 | 设计达标 | 代码现状 | 关键事实 |
|---|---|---|---|---|
| 1 | Canonical JSON 是跨平台事实数据层 | ✅ | ❌ 零实现 | `src/` 无 `CanonicalBookmark`/`normalized`/`schema/`；事实标准是 `UpstreamBookmark`（镜像 fieldtheory 字段，违反任务书 §5） |
| 2 | Markdown 只是可读知识表现层 | ⚠️ | ❌ 尚不是 | `render.py` 消费 fieldtheory 的 `raw/{id}.json`，不经 Canonical；frontmatter 缺 `collector`/`collected_at`/`content_hash` |
| 3 | SQLite 完全可重建 | ⚠️→✅（R6 修复） | ❌ 不可重建 | 运行态字段无重建来源；§6.3 字段清单与 `models.py` 冲突 |
| 4 | Field Theory 可完全替换 | ⚠️→✅（R7 修复） | ❌ 不可替换 | CLI 硬编码 `FieldTheoryAdapter`；`RawCollectorData` 契约未定义 |
| 5 | Knowledge-Agent 不知道 Collector | ✅ | ❌ 强耦合 | `render.py` `from src.collector.contract import ...`，知识层反向依赖 collector |
| 6 | 无 SQLite 恢复完整知识库 | ⚠️ | ❌ 无法恢复 | 富化内容唯一载体是 `data/raw/`（fieldtheory 格式、不入 Git），normalized 未实现 → 无跨设备载体 |

> 说明：第 3、4 项原为「设计有漏洞」，本轮已通过 R6/R7 补齐；第 2、6 项的「⚠️」是**实现缺失**（依赖 normalized/Canonical 落地后自动满足），非设计缺陷。真正的实现性返工风险已收敛到「rebuild-index 字段对齐」（§6.3.2）与「RawCollectorData 契约冻结」（§3.2.1）两处，均在进入对应 Phase（4 / 3）前定稿。
