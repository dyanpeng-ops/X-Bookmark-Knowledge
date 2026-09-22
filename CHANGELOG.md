# CHANGELOG

本项目遵循"每个 Phase 一条记录"的约定。格式：

```text
## [Phase N] YYYY-MM-DD — 名称
### Added / Changed / Fixed / Decided / Deferred
```

---

## [Phase 9] 2026-09-20 — External Link Extraction（实现完毕，**待验收**）

> 状态：**实现完毕、未验收**。待验证清单见 `tasks/CURRENT.md`，未获批准前不得执行。

### Added

- `src/external/fetcher.py` — `HttpFetcher`：标准库 `urllib`，超时 / 重试 / 退避 / 逐跳重定向 /
  `Content-Length` 与读取上限 / BOM + `<meta charset>` 编码探测；传输层可注入（测试全离线，ADR-017）
- `src/external/handlers/` — `base`（`ContentHandler` / `select_handler`）、`web`（`html.parser`：
  标题 / 摘要 / canonical / 正文，skip 标签列表）、`github`（`owner/repo` 标题策略）；`pdf` 暂未实现
- `src/external/resolver.py` — `LinkResolver`：逐条隔离、写入
  `assets/{tweet_id}/links/{link_key}.md`（无时间戳 → 内容幂等）、`FETCHED` 且正文仍在知识库内时
  不联网、`FAILED` 在 `external.max_attempts`（默认 3）后停止重试（`--force` 强制）
- `src/config.py` — `ExternalOptions` + `load_external_options()`；新增键 `delay_seconds` /
  `max_redirects` / `max_attempts` / `skip_domains`（默认 `x.com` / `twitter.com`）/ `links_subdir`
- `src/cli/main.py` — `links [--tweet-id] [--limit] [--force] [--dry-run]` 子命令；
  `status` 报告外链状态计数；流水线顺序 `sync → media → links → process`
- `tests/test_external.py` — 抓取封装 / handler / resolver / CLI 端到端（注入 fake transport，全程无 socket）

### Changed

- `src/database/repository.py` — `set_link_status()` 新增 `title`；新增
  `count_external_links()` / `count_external_links_by_status()` / `list_links_by_status()`
- `src/ingest/ingest.py` — `external_links.fetch_status` 只在**首次插入**时写入 `PENDING`（同
  Phase 8 的 `media.local_path` 规则；回归测试在 `tests/test_ingest.py`）
- `src/markdown/render.py` — `## external_links` 支持富化（`[title](url)` + 正文相对路径 /
  最终地址 / 失败原因）；无富化信息时与 Phase 7 完全一致
- `src/markdown/writer.py` — `MarkdownWriter` 支持 `link_lookup`，把知识库内的 `content_path`
  换算为相对本文件的 POSIX 路径
- `config/config.example.yaml` — `external` 段补充新键与说明（`pdf` 处理器标注为未实现）
- `README.md` / `ARCHITECTURE.md` / `PLAN.md` / `memory/` / `tasks/CURRENT.md` — Phase 9 状态与命令

### Fixed

- Phase 9 前置缺陷（同 Phase 6 缺陷 #1 同族）：重复 `sync` 会把外链的 `fetch_status` 重置为
  `PENDING`，导致已抓取的行每轮同步倒退。修复：ingest 仅在插入时写入 `fetch_status`。

---

## [Review] 2026-09-21 — Phase 9 复审阻断项关闭（实现修复 + 经批准的离线验证）

> 状态：复审三项阻断 + lint 全部关闭；`tests.test_external` 94/94 OK，全量 369/369 OK
> （2026-09-21 经批准运行，exit 0）；`git diff --check` 干净。**真实数据写运行仍待批准**。

### Added

- `src/external/netguard.py` — 非公网目标判定（回环 / 私网 / 链路本地（含 `169.254.169.254`）/
  CGNAT / 组播 / 保留段 / IPv6 ULA；IPv4-mapped 归一）；`host_resolver` 可注入（测试不触 DNS）
- `HttpFetcher` 新增 `BlockedTargetError`；初始目标与每一跳重定向后都复核；策略拒绝不重试
- 配置：`external.block_non_public_hosts`（默认 true）、`external.allow_hosts`（默认 []）
- `tests/test_external.py` 新增 `ReviewFixTests` 8 用例（SSRF、重定向复核、canonical 端到端、
  失败清字段三态、仓储 `clear_fields` 非法字段名）

### Fixed

- 复审阻断 1（SSRF）：`netguard` + 逐跳复核；命中在 resolver 中按策略跳过处理（记原因、不计
  attempt、不联网），满足敏感信息不进 Markdown 的红线
- 复审阻断 2（canonical）：`canonical_url` 优先写入 `external_links.resolved_url`（回退重定向
  最终址）；正文 frontmatter 同时记录 resolved 与 canonical 两个 URL
- 复审阻断 3（失败留旧正文）：`LinkUpdate.clear_fields` + `set_link_status(..., clear_fields=...)`
  （`None` 仍表示未提供，ADR-004 不变）；`--force` 失败或 attempts 耗尽时清空
  `content_path` / `title` / `resolved_url`，普通瞬时失败保留上次成功正文
- lint：两处 `__init__.py` 文件末尾空行清除；`git diff --check` 干净
- 新暴露缺陷：`handlers/base.py` 相对导入写错导致 `src.external` 整包不可导入；`repository.py`
  引用 `ALL_LINK_STATUS_VALUES` 未导入；`fetcher._guard` 残留 `attempts_total` 死代码
- CLI 标签 `local links` 更名 `links known`（该计数含 PENDING，原名误导；同步改两处测试）

### Decided

- SSRF 命中记为策略跳过而非 `FAILED`（不计 attempt、不重试、原因入库）。
- 普通瞬时失败保留旧正文；仅在强制重抓失败或重试耗尽时清空。
- 修正记录：`links --dry-run` 并非离线 - 只抑制写盘/写库，仍会发起真实 HTTP；已同步更正
  `tasks/CURRENT.md` 与 README。真实数据写运行（`links` / `process` / 二次 `links` /
  `sync --skip-collect`）改为单独审批项。

### Notes

- 全部改动未提交；提交与推送另行征求批准。


## [Process] 2026-09-20 — 验证分级授权（用户指令）

### Decided

- **用户指令（2026-09-20）：未经允许不得擅自开始验证。** 落地为分级授权：
  - **可直接进行**：只读检查（读取文件、搜索、`git status` / `git log` / `--help` 等不改状态、不联网的命令）
  - **必须先批准**：运行测试或任何验收/探测脚本、任何联网（`ls-remote` / `clone` / `fetch` / `push` / 外链抓取）、任何写盘（文件 / 数据库 / 知识库）、任何使用用户凭据的远端操作
- 请求批准时须提交「待执行清单」：命令原文 + 目的 + 影响范围（是否联网 / 是否写盘 / 预计耗时）
- **实现完毕 ≠ 已验证**：未获批准的阶段只能表述为"实现完毕、未验收"

### Changed

- `AGENTS.md`：第 2 节新增第 16、17 条（验证分级授权与"实现完成先停下"）；第 7 节工作流插入"提交待验证清单 → 等待批准"关卡；第 8 节把"运行测试"从安全动作移入需批准动作，并新增联网动作条目
- `.clinerules/20-execution.md`、`.clinerules/30-testing.md`：写入同一分级规则与禁止"顺手验证"的表述
- `tasks/CURRENT.md`：Hard stop 增列验证授权要求

### Fixed

- 纠正此前的实践偏差（2026-09-20）：Agent 曾在未获批准的情况下自行执行 `git clone`、`git ls-remote`、凭据条目查看等"顺手验证"动作，超出授权范围；已停止此类行为

---

## [Repo] 2026-09-20 — 首次建立版本控制并推送到私有仓库

### Added

- `.gitignore` 新增知识库策略：`knowledge/*` 默认忽略，逐层放行后**仅**跟踪 `knowledge/X-Bookmarks/README.md`（四行式 `!` 规则——被排除目录内部无法用 `!` 找回文件，这是唯一正确写法）
- 提交身份写入**仓库本地**配置：`dyanpeng-ops` / `dyanpeng-ops@users.noreply.github.com`（noreply 邮箱，不暴露真实地址）

### Decided

- 版本控制由用户授权启用（关闭 PLAN.md §5.3）：远程为**私有**仓库 `https://github.com/dyanpeng-ops/X-Bookmark-Knowledge.git`，远程名 `X-Bookmark-Knowledge`（**不是** `origin`），分支 `main`
- 真实书签内容与本地媒体资产**不上传**（仅保留 `knowledge/X-Bookmarks/README.md`）；`.workbuddy/`（宿主侧 Agent 日志）按用户决定保留跟踪

### Verified

- 首个提交 `94da817`：73 个文件 / 12,725 行；`git ls-remote` 远端 `refs/heads/main` 与本地 HEAD 完全一致
- 推送内容核查：不含 `config/config.yaml`、`data/`、`.venv/`、`*.db`；`knowledge/` 下仅 1 个文件（README）
- 磁盘核查：`knowledge/X-Bookmarks/` 下 12 个文件（5 Markdown + 6 媒体 + README）**全部原样保留**，未被删除
- `git check-ignore` 自检：README 未忽略，书签/媒体命中忽略规则；`config/config.yaml`、`data/state/state.db`、`data/upstream/bookmarks.jsonl` 均 `ignored=True`

---

## [Phase 8] 2026-09-20 — Media Localisation

### Added

- `src/media/localizer.py`：`MediaLocalizer` / `MediaSource` / `MediaUpdate` / `MediaStats`
  - 目标布局 `knowledge/X-Bookmarks/{YYYY}/{MM}/assets/{tweet_id}/{media_key}{ext}`，年月与 Markdown 产物同源（复用新抽出的 `date_parts`）
  - 稳定命名 `{media_key}{ext}`（`media_key = sha1(source_url)[:16]`）：DB 行与文件可直接互查，不随上游命名漂移
  - 幂等：目标已存在且 SHA-256 与源一致 → `unchanged`（不重写、不动 mtime）；源内容变化 → 覆盖重写
  - 原子复制：先写同目录 `.part` 再 `os.replace`，失败清理临时文件
  - 单条失败隔离：缺源/读写失败 → 该行 `FAILED` + `error_message` + `attempts`，其余照常处理
  - `dry_run`：只解析与报告，不建目录、不复制、不落库
- **旧缓存路径归一（独立审计前置条件）**：源文件解析顺序 ① `local_path` 且在知识库内（已本地化）② `local_path` 且在配置的上游媒体目录内 ③ 上游清单索引 `sourceUrl → localPath` 的文件名 ④ `local_path` 文件名 ⑤ `source_url` 文件名；全部落空即如实报 `FAILED`。**只取文件名到配置的 `data/upstream/media/` 解析，从不读取旧 C: 缓存**
- 跳过规则（不复制、不改 `local_path`，只在 `error_message` 记 `skipped: <原因>`）：`media.download=false`、上游状态非 `downloaded`、`media.download_video=false` 且类型为 `video`/`animated_gif`、体积超 `media.max_bytes`
- `src/cli`：新增 `media [--tweet-id X] [--dry-run]` 子命令（退出码 0/1）；`media.download=false` 时打印 warn 并按 skipped 报告
- `src/markdown/render.py`：抽出 `date_parts()`（Markdown 与 assets 共用同一套年月规则）；`_render_section_media` 支持 `media_files` 映射，`render_markdown(..., media_files=...)` 新增关键字参数（缺省保持 Phase 7 行为）
- `src/markdown/writer.py`：`MarkdownWriter(..., media_lookup=...)` 把查询结果换算为**相对该 Markdown 文件**的 POSIX 路径；查询失败降级为远程 URL，不影响渲染
- `src/cli process`：读取 `media.local_path`，**只接受位于 `knowledge_dir` 内且真实存在的文件**，旧缓存/缺失文件一律回退远程 URL；报告新增 `local media : N bookmark(s)`
- `tests/support/stub_fieldtheory.py`：按清单为每个 `downloaded` 条目在上游 `media/` 下生成确定性文件（清单里仍保留合成绝对路径，正是待归一的场景）
- `tests/test_media.py`（44 用例）：命名与布局、复制幂等与源替换、旧缓存路径归一、清单索引重定位、跳过规则、dry-run、落库意图、Markdown 段落与路径换算、CLI 端到端（`sync → media → process`、二次运行不变、失败隔离、`--dry-run` 不落盘、再次 sync 不倒退）

### Changed

- `src/ingest/ingest.py`：`media.local_path` 改为**只在首次插入时写入**——该字段 Phase 8 之后由媒体层接管（存放知识库内路径），重复 `sync` 不得用上游旧缓存路径覆盖（`tests/test_ingest.py` 新增回归用例）
- `media.local_path` 语义收紧为"该媒体字节在本项目内的落点"：成功后写知识库内绝对路径；跳过/失败保持原值，Markdown 侧因此自然回退远程 URL

### Decided

- **清单里的全部媒体行都本地化**（含 `profile_image`），与审计"6 条 `media.local_path` 均需归一"的预期一致；`## media` 段落只引用推文自身的媒体，头像文件不参与渲染
- 跳过**不写** `SKIPPED` 状态，而是保持上游状态 + 写 `error_message = "skipped: ..."`：否则每次 `sync` 都会被清单的 `downloaded` 改回 `DOWNLOADED`，产生"每轮全部更新"的假统计（Phase 6 缺陷 #1 的同族问题）
- 流水线顺序固定为 `sync → media → process`（`process` 读取 `media` 写入的本地路径）

### Verified (real data, 2026-09-20)

- `media --dry-run`：attempted 6 / copied 6 / failed 0（6 条旧 C: 路径全部在配置目录内解析）
- `media` 首次：copied 6 / failed 0；第二次：unchanged 6 / copied 0（幂等）
- SQLite：6/6 行 `local_path` 指向 `knowledge/X-Bookmarks/.../assets/{tweet_id}/`，与 `data/upstream/media/` 源文件 SHA-256 逐条一致
- `process --overwrite`：written 1 / unchanged 4（只有含推文媒体的那 1 份文件变化）；再次 `process`：written 0 / unchanged 5
- `## media` 段由远程 `https://pbs.twimg.com/media/...` 改为 `assets/2099122261772968036/cf1939a0c2c6b71d.png`（文件存在）
- `sync --skip-collect`：`media rows : 0 new, 0 updated, 6 unchanged` → 本地路径不被回退
- 全量离线测试：**272 用例，exit 0**

---

## [Audit] 2026-09-17 — 独立审计跟进（Phase 8 前置条件）

### Verified

- 审计方独立复验：227 个离线测试通过；`status --json` 显示 schema v2 + 5 条 `PROCESSED`；`doctor` 全部 OK
- 媒体路径核查：6/6 条 `media.local_path` 仍指向旧 `C:\Users\gscaee\.fieldtheory\bookmarks\media\...`；
  `data/upstream/media/` 项目内副本逐字节一致（SHA-256 6/6，本侧复核确认）

### Fixed

- `config/config.example.yaml`：更正 `upstream_data_dir` 注释——配置值优先，`FT_DATA_DIR` 仅在配置留空时回退（ADR-013）
- `plans/backlog.md` / `memory/current-state.md`：记录 Phase 8 前置条件——复制媒体前先将旧 C: 绝对路径
  归一到配置的 `data/upstream/media/` 并校验文件；回归测试需覆盖旧绝对路径行与源文件缺失/被替换

---

## [Phase 7] 2026-09-17 — Markdown Generator（M3 达成）

### Added

- `src/markdown/render.py`：`RenderOptions` + `render_markdown()`
  - Frontmatter 固定 13 键（tweet_id / url / author_handle / author_name / created_at / language / media_count / link_count / engagement / tags / primary_category / folder_names / source），日期归一为 UTC ISO-8601
  - 8 个段落：`tweet` / `thread` / `media` / `article` / `external_links` / `metadata` / `ai_analysis` / `source`；未配置段落自动跳过，未知段落名打印警告但不中断
  - 输出路径 `YYYY/MM/YYYYMMDD-{tweet_id}.md` 按**发帖日期**（非同步日期）分组；无日期回退 `unknown/unknown/`
  - 正文统一转义（`|` 等），避免破坏 Markdown 表格；缺失字段渲染为占位（`_无媒体_` / `_无引用推文_` / `_未展开文章_` 等）
- `src/markdown/writer.py`：`MarkdownWriter`
  - 逐条渲染 → 与既有文件**内容哈希比对**：相同跳过、不同拒绝覆盖（`overwrite_existing: false`，`process --overwrite` 可显式覆盖）、单条失败隔离
  - 状态推进 `COLLECTED → PROCESSED` 并记录 `markdown_path`；`stats` 报告 written/unchanged/conflicts/failed
- `src/cli` 新增 `process` 子命令（`process [--overwrite]`）：从 `data/raw/` 读原始归档，逐条渲染写入 `knowledge/X-Bookmarks/`
- `tests/test_markdown.py`（23 用例）：frontmatter 键序与取值、各段落渲染与占位、路径规则、写盘（首写/跳过/拒绝覆盖/失败隔离/状态推进）、端到端 CLI `process`（离线桩，临时目录）

### Fixed

- **中文 Windows 子进程编码崩溃**（14 个测试失败的共同根因）：上游 `fieldtheory` CLI 输出 `✓`、`⠋` 等非 GBK 字符时，Windows 子进程默认 cp936 编码导致 UnicodeEncodeError。
  - `src/collector/fieldtheory_adapter.py`：子进程环境注入 `PYTHONIOENCODING=utf-8`
  - `tests/support/stub_fieldtheory.py`：启动时 `reconfigure` stdout/stderr 为 UTF-8（errors=replace）
  - 详见 ADR-014
- `tests/test_markdown.py` 断言修正：输出按发帖年月分组（夹具记录归 `2026/06/` 而非 `2026/09/`）

### Decided

- **实现 `thread` 与 `ai_analysis` 段落而非从配置移除**：两者是 `config.example.yaml` 声明的契约段落。`thread` 渲染富化 `quotedTweet`（JSONL 不携带，来自 `data/raw/` 归档）；`ai_analysis` 当前为占位段，Phase 11 AI 增强落地时向同一标题写入内容（ADR-015）
- `RenderOptions.include_sections` 默认值与 `config.example.yaml` 的 8 段顺序保持一致

### Deferred

- 媒体本地化后 `## media` 段改用本地相对路径（Phase 8）
- `ai_analysis` 真实内容生成（Phase 11）

### 验收（2026-09-17，真实数据）

- `.venv\Scripts\python.exe -B -m unittest discover -s tests -t .` → **227 passed / exit 0**
- `python -m src.cli sync --skip-collect` 二次运行：`new: 0 / unchanged: 5`，raw 归档 0 重写
- `python -m src.cli process`：5 个 Markdown 全部写入 `knowledge/X-Bookmarks/{2026-03, 2026-06, 2026-09}/`；**二次运行 `written: 0 / unchanged: 5`**，无未知段落警告
- `python -m src.cli status`：DB 5 条全部 `PROCESSED`；上游 `[ok] records=5`

---

## [Phase 6] 2026-09-16 — 增量同步 + CLI 入口（M2 达成）

### Added

- `requirements.txt`：新增第三方依赖 **PyYAML 6.0.3**（`pyyaml==6.0.3`）；理由与备选见下方 Decided
- `src/config.py`：YAML 配置加载（`load_config`）
  - 强类型配置对象：`PathsConfig` / `CollectorConfig`（含 `SyncConfig`、`AuthConfig`）/ `IngestConfig` / `LoggingConfig` / `AppConfig`
  - **所有相对路径按项目根解析为绝对路径**（AGENTS.md 第 5 节：禁止硬编码盘符）
  - 版本校验（`version: 1`）、类型校验、未知顶层键上报、`require_file=False` 供 `doctor` 探测
  - `paths.state_db_path` = `data/state/state.db`；`paths.raw_json_path(tweet_id)`
- `src/ingest/ingest.py`：`Ingestor` + `IngestStats`
  - 上游 `UpstreamBookmark` + `EnrichedBookmark` + `MediaEntry` 幂等写入 `bookmarks` / `media` / `external_links`
  - 逐条原始 JSON 归档到 `data/raw/{tweet_id}.json`（内容**不含时间戳**，因此"内容未变即跳过重写"）
  - **单条失败隔离**：失败写入 `FAILED` + `error_message` + `attempts`，其余记录照常入库
  - 媒体键稳定派生（`sha1(source_url)[:16]`）、媒体类型推断（profile_image / photo / video）、清单状态映射
  - 外链按 tweet 去重、提取 domain、空白 URL 直接跳过
- `src/cli/main.py` + `src/cli/__main__.py`：`python -m src.cli` 入口
  - `sync`：可选调用上游采集 → 幂等入库 → 打印报告（fetched/new/updated/unchanged/failed/transitions/raw/media/links/状态分布）
  - `status`（支持 `--json`）、`doctor`（配置/项目根/上游可执行/上游版本/上游数据/数据库 schema/日志目录/上游盘符）
  - 退出码：`0` 成功、`1` 业务失败、`2` 配置错误、`3` 上游失败
  - 日志：控制台 + `data/logs/YYYY-MM-DD.log`，并在命令结束时关闭句柄
- `tests/test_config.py`（21 用例）、`tests/test_ingest.py`（25 用例）、`tests/test_cli.py`（17 用例）—— 全部离线，使用临时目录 + 离线桩

### Changed

- `PLAN.md`：Phase 6 完成、M2 达成、§4.4 实施记录、技术栈表补齐 YAML 依赖
- `tasks/CURRENT.md` / `plans/ACTIVE.md` / `memory/current-state.md`：推进到 Phase 7 待授权
- `config/config.example.yaml`：新增 `collector.executable_args`；`FT_DATA_DIR` 说明改为"配置优先，环境变量回退"

### Fixed

- `src/database/repository.py`：`upsert_media()` 与 `upsert_external_link()` 的 `UpsertResult.changed` 被硬编码为 `True`，导致每次同步都报告"媒体/外链全部更新"。现按与 `upsert_bookmark` 相同的语义比较实际差异
- `src/collector/fieldtheory_adapter.py`：传入**命令序列**（如 `python -B stub.py`）时跳过可执行文件解析，`doctor` 因而把不存在的命令误判为可用；现首元素仍经 `shutil.which` 解析
- `src/cli/main.py`：日志 `FileHandler` 从不关闭，Windows 下日志文件保持锁定（临时目录无法清理）；现有 `_teardown_logging` 在命令结束时关闭并移除处理器
- `src/ingest/ingest.py`：仅含空白的 URL（`"   "`）会穿透过滤并让整条书签被标记 `FAILED`；现按空白跳过
- `tests/test_ingest.py` 夹具：`raw` 载荷未跟随字段变化，幂等测试失真

### Decided

- **引入 PyYAML**：标准库无 YAML 解析；配置含嵌套映射与注释，手写子集解析的出错成本高于一个成熟依赖。备选（手写子集解析、改用 TOML/INI）被拒：前者易在引号/转义上出错，后者与已发布的 `config.example.yaml` 不兼容。重新评估条件：若要求"零第三方依赖"，可改为 INI 并同步迁移示例配置
- **配置优先于环境变量**：`collector.upstream_data_dir` 以配置文件为准，`FT_DATA_DIR` 仅在配置留空时回退（ADR-013）
- **新建记录直接落 `COLLECTED`**：采集与入库同时完成，不留 `NEW`
- **原始归档不含时间戳**：时间保存在 SQLite（`first_synced_at` / `last_synced_at`），使归档内容可做"内容相等即跳过"的判断

### Deferred

- `--classify` / `retry` / `process` / `enrich` / `verify` 子命令（后续阶段）
- 媒体本地化到 `knowledge/.../assets/`（Phase 8）；当前只记录上游 `localPath`
- AI 增强（Phase 11）

### Incident（已记录，需用户授权后恢复）

**测试误写真实上游目录**：由于当时"环境变量优先于配置"的优先级设定，`test_cli.py` 的离线桩把 3 条合成夹具记录写进了真实的 `data/upstream/`（JSONL 被覆盖为 3 条夹具记录，`bookmarks.db` 增至 8 行，另有 `stub-argv.txt`）。

- 已修复根因（配置优先 + 测试隔离），并实测验证：整套 204 个测试运行前后 `data/upstream` 的文件名与时间戳**完全不变**
- 真实数据完好保留在 `~/.fieldtheory/bookmarks`（C:，迁移时的源目录，未删除）与 `bookmarks.db` 内
- 待用户在授权后清理 `data/upstream` 并重新采集，见 `tasks/CURRENT.md`

---

## [Phase 5] 2026-09-16 — 实现 Collector（上游 fieldtheory 适配器）

### Added

- `src/collector/contract.py`：**冻结的上游字段契约**——`bookmarks.jsonl`（21 必填键 + 可选 `textExpandedAt`）、嵌套 `author`/`engagement`/`mediaObjects` 必填键、`media-manifest.json`（schemaVersion=1）、`bookmarks-meta.json`、`bookmarks-backfill-state.json`、`list|show --json` 富化记录；两类时间格式解析（RFC822 风格 `postedAt`、ISO-8601 `Z`）；未实测项显式标注 `UNVERIFIED`
- `src/collector/base.py`：`Collector` 协议；错误体系 `CollectorError` / `UpstreamUnavailableError` / `UpstreamContractError` / `UpstreamAuthError` / `UpstreamTimeoutError` / `UpstreamExecutionError`；结果类型 `SyncRunResult` / `UpstreamArtifacts`；数据类 `UpstreamBookmark` / `EnrichedBookmark` / `MediaManifest` / `MediaEntry`
- `src/collector/fieldtheory_adapter.py`：`FieldTheoryAdapter`
  - `sync()`：完整映射 `--browser/--no-media/--rebuild/--continue/--gaps/--folders/--folder/--max-pages/--target-adds/--max-minutes/--delay-ms/--yes`
  - `read_bookmarks()` / `read_media_manifest()` / `read_meta()` / `read_backfill_state()`
  - `list_enriched()` / `show_enriched()`：唯一可取 Article 正文的通道
  - `check_ready()` / `upstream_version()`
  - 数据目录解析优先级：显式参数 > `FT_DATA_DIR` > `~/.fieldtheory/bookmarks`；每次调用都显式设置 `FT_DATA_DIR`
  - 子进程统一 timeout、瞬时错误有界重试（认证类错误不重试）、错误分类、stdout JSON 容忍前后噪声
- `tests/test_collector_contract.py`：34 个用例，含**快照测试**（冻结键集与真实捕获一致）与各类契约违规
- `tests/test_collector_fieldtheory.py`：42 个用例，路径解析 / 参数映射 / 重试 / 错误分类 / 解析 / 幂等
- `tests/support/stub_fieldtheory.py`：离线上游桩（正常、认证失败、瞬时失败、慢响应、噪声输出）
- `tests/fixtures/upstream/`：5 个合成夹具（JSONL / media-manifest / list / meta / backfill-state），结构等同真实样本但内容为虚构

### Changed

- `src/collector/__init__.py`：由占位声明改为对外导出面（`FieldTheoryAdapter` + 结果类型 + 错误类型）
- `PLAN.md`：Phase 5 前置条件 A–D 全部关闭并写入 §4.3 实施记录；§1 状态与 §7 风险登记同步更新
- `research/architecture-decision.md` §4.3：由\"待确认\"替换为**实测冻结的字段映射**（含分页/增量语义与 Article 正文位置）

### Fixed

- `contract.py`：嵌套对象原先只校验\"已出现键的类型\"，缺 `type` 的 `mediaObjects` 条目会被放过 → 新增 `AUTHOR_REQUIRED_KEYS` / `ENGAGEMENT_REQUIRED_KEYS` / `MEDIA_OBJECT_REQUIRED_KEYS`
- `contract.py`：`bookmarks-backfill-state.json` 的 `lastCursor` 被当作必填，导致媒体同步后的真实数据读取失败 → 改为可选并记录已观测 `stopReason` 值
- `tests/test_collector_fieldtheory.py`：漏导入 `UpstreamContractError`
- `tests/support/stub_fieldtheory.py`：`slow` 场景原先只对 `sync` 生效 → 改为对所有命令生效

### Decided

- **认证路径以 Firefox 会话为准**：Firefox 156 的 `cookies.sqlite` 为明文，`ct0`/`auth_token` 可直接读取；Chrome 155 的 App-Bound Encryption（`v20`）在上游 1.3.22 下不可用
- **双源采集**：JSONL 取原始记录 + `list --json` 取富化（Article 正文不在 JSONL）
- 首次全量采集必须用 `--continue` 或 `--rebuild`：默认增量在连续 3 页无新增后即停止
- 数据目录可用 `FT_DATA_DIR` 重定位（用于把媒体落到 D 盘，规避 C 盘仅剩约 6.4 GB 的风险）

### Deferred

- `config/config.yaml` 的 **YAML 解析依赖**仍未决定（Phase 6 前置）
- 视频/多图 `mediaObjects` 变体、`skippedTooLarge`/`failed` 状态字符串未实测（样本中不存在）
- 上游 `classify` 未运行（`primaryCategory` 全为 `unclassified`）；分类是否复用上游留待 Phase 11 决定

---

## [Phase 4] 2026-09-15 — 设计数据模型（SQLite）

### Added

- `.venv/`：项目内虚拟环境，解释器固定 Python 3.12.13（默认 3.14.3 过新）
- `requirements.txt`：当前**无第三方运行时依赖**（数据层仅用标准库）
- `src/database/clock.py`：UTC 时间戳工具（`YYYY-MM-DDTHH:MM:SSZ`），支持注入固定时间以便测试确定性
- `src/database/states.py`：书签状态机（`NEW → COLLECTED → PROCESSED → ENRICHED → COMPLETED`，`FAILED` 可重入）+ 媒体/外链状态词表；`InvalidStateTransition`
- `src/database/schema.py`：`Migration` 数据结构、版本化 DDL（v1 书签 / v2 媒体+外链+FTS5）、`SCHEMA_VERSION = 2`；CHECK 约束由枚举生成
- `src/database/transaction.py`：`transaction()` 显式事务上下文（`BEGIN IMMEDIATE`，异常含 `BaseException` 均回滚）、`in_transaction()`
- `src/database/migrations.py`：`current_version` / `recorded_versions` / `pending_migrations` / `apply_migrations`（单事务原子应用、幂等）/ `is_up_to_date`
- `src/database/models.py`：`BookmarkRecord` / `MediaRecord` / `ExternalLinkRecord`（含 `from_row`）
- `src/database/repository.py`：`BookmarkRepository` —— 幂等 upsert（书签/媒体/外链）、状态流转、错误记录、计数、按状态列表、FTS5 检索、级联删除、媒体/外链状态更新
- `src/database/connection.py`：`connect()`（自动建目录、`foreign_keys=ON`、`busy_timeout`、文件库 WAL、可选自动迁移）+ `schema_status()`
- `src/database/__init__.py`：对外导出面（`__all__`）
- `tests/test_database.py`：68 个用例，覆盖初始化、迁移（幂等/旧库升级/失败回滚/版本校验）、事务提交与回滚、唯一与 CHECK 约束、状态机、幂等 upsert、媒体、外链、FTS5、级联删除、时间戳
- `tests/__init__.py`：使 `tests` 成为可发现的包

### Changed

- `config/config.example.yaml`：修正采集器文案（原写"唯一已实现的适配器"，但 Adapter 属 Phase 5 工作项）；`executable` 由 `fieldtheory` 改为 `fieldtheory.cmd`
- `PLAN.md`：新增 4.2 Phase 4 实施记录；技术栈表更新（venv 已建、测试运行器已定）；阶段状态更新
- `tests/README.md`：由"计划文件"改为"已实现文件 + 运行方式"
- `README.md`：安装章节补充 venv/requirements 现状，状态章节更新

### Decided

- **测试运行器：标准库 `unittest`**（而非 pytest）。理由：零第三方依赖，符合"依赖最小化"原则；当前断言与夹具需求用 unittest 即可充分表达。若将来出现参数化测试、夹具组合等明确痛点，再评估 pytest 并在本文件记录理由。
- **状态机语义**：同状态写入视为无操作（幂等）；`FAILED` 允许重入流水线以支持 `retry`；`COMPLETED` 为终态。
- **部分更新语义**：输入结构中 `None` 表示"本次未提供"，不覆盖库中已有值；由此 `MediaRecord.download_status` 与 `ExternalLinkRecord.fetch_status` 的默认值由 `PENDING` 改为 `None`。
- **时间戳语义**：`last_synced_at` 只在 sync 写入（`upsert_bookmark`）时更新，状态流转不改它，避免"同步时间"与"处理时间"混淆。

### Fixed

- 幂等缺陷：媒体/外链的 `download_status` / `fetch_status` 默认值会被误判为显式提供，导致重复 upsert 重置已 `DOWNLOADED` / `FETCHED` 的状态 → 改为 `None` 默认 + `_status_value()` 回退，并补 2 条回归测试
- `tests/test_database.py` 漏导入 `parse_status`

### Deferred

- Collector、CLI、Markdown、媒体、外链抓取均未开始；Phase 5 四项前置条件仍全部未满足
- YAML 解析依赖仍未决定（`requirements.txt` 已注明决定时间点）

### Verification

```text
.venv\Scripts\python.exe -m unittest discover -s tests -t .
Ran 68 tests in 2.71s
OK        (exit 0)
```

---

## [Phase 3] 2026-09-15 — 建立项目骨架

### Added

- 目录骨架：`config/` `docs/` `research/` `src/{collector,ingest,processor,media,external/handlers,markdown,database,scheduler,cli}` `data/{raw,state,logs}` `knowledge/X-Bookmarks` `tests/` `scripts/`
- `AGENTS.md`：项目级 Agent 规范，声明对上级 `01_Knowledge-Agent/AGENT.md` 的继承与冲突裁决顺序
- `README.md`：项目说明（目标 / 架构 / 安装 / 配置 / 认证 / 同步 / 调度 / 故障排查 / 安全 / 开发）
- `PLAN.md`：阶段进度、Phase 5 硬性前置条件、技术栈决策表、里程碑、风险登记
- `CHANGELOG.md`：本文件
- `.gitignore`：敏感信息、程序数据、数据库、日志、虚拟环境等忽略规则
- `config/.gitignore`：白名单式忽略（仅保留模板与说明）
- `config/config.example.yaml`：完整配置模板（含认证方式、采集开关、媒体、外链、AI、调度、安全开关）
- `config/README.md`、`knowledge/X-Bookmarks/README.md`、`tests/README.md`、`scripts/README.md`：目录职责说明
- `data/raw/.gitkeep`、`data/state/.gitkeep`、`data/logs/.gitkeep`
- `data/environment-report.md`：指向 `docs/environment-report.md` 的指针（满足执行计划 §三的输出路径要求，同时避免权威文档落在被忽略的 `data/` 中）
- `src/__init__.py` 及各子包 `__init__.py`：仅声明职责，**不含任何实现**（按执行计划 Step 5，不开始实现 Collector）

### Decided

- 技术路线：`fieldtheory` CLI 作 Collector（Adapter 隔离）+ 其余自研（用户于 2026-09-15 批准）
- 项目根路径修正为 `01_Knowledge-Agent/...`（执行计划原文的 `02-Knowledge-Agent` 不存在）
- 解释器选 Python 3.12.13 建 venv（默认 3.14.3 过新）
- 知识库终点改为"项目内产出 → 交接上级 `inbox/X-Bookmarks/`"，不直接写上级 `knowledge/`
- 仅创建 `.gitignore`，**不执行 `git init`**（待用户授权）

### Deferred

- 数据库 schema、Collector、CLI 实现均不在此阶段进行
- `scripts/*.ps1`（调度器安装/卸载）留待 Phase 13
- 配置解析器与依赖选型留待 Phase 4

---

## [Phase 2] 2026-09-15 — 确定采集策略

### Added

- `research/architecture-decision.md`：候选方案（A–E）对比与排除理由、数据流与边界、上游字段映射（待样本确认）、认证方案、调度方案、复用/自研边界、风险与缓解、待确认事项、复审触发条件

### Decided

- 采用执行计划"第二优先"：成熟项目作为 Collector
- Collector 选 `fieldtheory`（MIT / 活跃 / CLI / 本机已装验证 / 产物可 ingest）
- TweetKB 降为备选与设计参考；自研 GraphQL Collector 仅作最后兜底
- 本项目不实现 Cookie 解密（属上游职责），以便上游修复后零改动受益

### Fixed

- 修正执行计划中对"整体复用"（第一优先）的隐含预期：现有项目均为扩展/桌面形态或规范冲突，第一优先实际不可行

---

## [Phase 1] 2026-09-15 — GitHub 开源项目技术评估

### Added

- `research/open-source-comparison.md`：9 个候选项目的元数据、能力矩阵、逐项目分析、适配度排序、未决问题清单

### Findings

- `xmarks` 无法解析：Xmarks 是 2018 年停服的浏览器书签同步服务，与 X 书签无关
- `SaveBox`、`twitter-bookmark-archiver` **无 LICENSE 文件** → 不可复用
- `XClipper` 为 **PolyForm Noncommercial** 许可 → 不可商用二开
- `MarkHarbor` / `xarchive` / `twitter-web-exporter` 为扩展形态 → 无法无人值守
- `TweetKB` 架构最接近目标（SQLite+FTS5+`status_id` 去重+`content_hash`+导出适配器+测试），但 Windows 采集未声明
- `fieldtheory-cli`（2020 stars、MIT、活跃、CLI 完整、本机已装）为最佳 Collector 候选

### Notes

- 本阶段未 clone 源码（本机无 git 身份），凡未经源码确认的项均标注 `待验证`

---

## [Phase 0] 2026-09-15 — 检查现有项目环境

### Added

- `docs/environment-report.md`：OS / 磁盘 / Python / Node / Git / 目录结构 / 既有规范 / 可复用组件 / 冲突与风险 / 偏差记录 / 复现命令

### Findings

- 执行计划指定路径 `02-Knowledge-Agent` 不存在，实际为 `01_Knowledge-Agent`
- 目标目录 `projects/X-Bookmark-Knowledge` 已存在且为空
- Lab 内无 git 仓库、无 Obsidian Vault、无既有 Skills；git 未配置 `user.name`/`user.email`
- 默认 Python 3.14.3，另有 uv 管理的 3.12.13（`uv` 不在 PATH）
- `C:` 仅剩 6.4 GB，`D:` 剩 323.2 GB
- **Chrome 155 的 x.com Cookie 为 `v20`（App-Bound Encryption），`fieldtheory@1.3.22` 只支持 `v10`/裸 DPAPI → 会话采集失败**（已用代码与实测双重确认）

### Fixed

- 记录并纠正执行计划的三处与实际不符：项目路径、`data/environment-report.md` 与 `.gitignore` 的冲突、知识库终点与上级 Inbox 规范的冲突
