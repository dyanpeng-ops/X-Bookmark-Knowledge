# tests/

## 用途

存放本项目测试。核心验收要求：

> **同一个同步任务运行两次，第二次不得产生重复数据。**

## 已实现文件

| 文件 | 覆盖内容 | 状态 |
| --- | --- | --- |
| `test_database.py` | 初始化、迁移（幂等/旧库升级/失败回滚/版本校验）、事务（提交与回滚）、唯一与 CHECK 约束、状态机、幂等 upsert、媒体、外链、FTS5、级联删除、时间戳 | ✅ Phase 4（68 用例） |
| `test_collector_contract.py` | 上游字段契约：快照冻结键集、JSONL/manifest/meta/backfill/富化记录的必填键与类型、两种时间格式 | ✅ Phase 5（34 用例） |
| `test_collector_fieldtheory.py` | Adapter：数据目录解析、`sync` 参数映射与重试、认证/超时/执行错误分类、JSONL 与 manifest 解析、`list|show --json` 富化读取、幂等读取 | ✅ Phase 5（42 用例） |
| `test_config.py` | 配置加载：示例/本机配置可解析、相对路径解析、**配置优先于环境变量**、版本与类型校验、未知键上报 | ✅ Phase 6（21 用例） |
| `test_ingest.py` | 入库：字段映射、原始 JSON 归档、**两次运行幂等**、媒体/外链、单条失败隔离与恢复 | ✅ Phase 6（25 用例） |
| `test_cli.py` | 端到端：`sync`/`status`/`doctor`、**M2 的 New=0 断言**、退出码 0/1/2/3、失败记录写入 | ✅ Phase 6（17 用例） |
| `test_markdown.py` | 渲染（frontmatter 键序、8 段落、占位、转义）、路径规则、写盘（首写/跳过/拒绝覆盖/失败隔离/状态推进）、CLI `process` 端到端 | ✅ Phase 7（23 用例） |
| `test_media.py` | 媒体命名与布局、SHA-256 幂等与源替换、**旧缓存绝对路径归一**、清单索引重定位、跳过规则（download/video/max_bytes/上游状态）、dry-run、落库意图、Markdown 本地路径与**知识库外路径拒绝**、CLI `sync → media → process` 端到端 | ✅ Phase 8（44 用例） |
| `test_external.py` | 抓取封装（超时/重试/退避/重定向/体积上限/scheme 白名单/编码探测）、handler 抽取与选择、resolver 幂等与失败保留 URL、跳过规则、CLI `sync → links → process` 端到端（注入 fake transport，全程无 socket） | ✅ Phase 9 |
| `support/stub_fieldtheory.py` | 离线上游桩（正常/认证失败/瞬时失败/慢响应/噪声输出），使 Adapter 与 CLI 测试无需网络与浏览器 | ✅ Phase 5 |
| `fixtures/upstream/*` | 5 个合成夹具：`bookmarks.sample.jsonl`、`media-manifest.sample.json`、`list.sample.json`、`bookmarks-meta.sample.json`、`bookmarks-backfill-state.sample.json`（结构等同真实样本，内容虚构） | ✅ Phase 5 |
| `__init__.py` | 使 `tests` 成为包，便于 `python -m unittest discover` | ✅ |

## 计划文件（后续阶段）

| 文件 | 覆盖内容 | 阶段 |
| --- | --- | --- |
| `test_pipeline.py` | 端到端：采集 → 媒体 → 外链 → markdown → 知识库 | Phase 10/12 |

## 运行方式

```powershell
# 项目根目录
.\.venv\Scripts\python.exe -m unittest discover -s tests -t . -v
```

测试运行器为**标准库 unittest**（决定与理由见 `CHANGELOG.md` 的 Phase 4 记录）。

当前全量：**272 个用例**（Phase 4：68 + Phase 5：76 + Phase 6：60 + Phase 7：23 + Phase 8：44 + 入库回归：1）+ Phase 9 新增（`tests/test_external.py`、ingest/database 回归用例），全部离线；
整套运行**不会触碰真实上游目录**（有专门校验，见 `CHANGELOG.md` Phase 6 的 Incident）。

## 必须覆盖的异常场景

- 重复 Tweet
- 网络失败（超时 / DNS 失败 / 非 2xx）
- 图片下载失败
- 外链抓取失败
- 数据库异常（锁定 / 半写入）
- Markdown 已存在（同内容 / 不同内容）
- 中途退出后重跑
- 同一命令重复执行

## 约定

- 测试不得访问真实网络：网络层必须可注入 fake fetcher。
- 测试不得读取真实上游目录：使用 `tests/fixtures/` 下的样本 JSONL。
- 测试不得写入真实 `knowledge/`：使用临时目录（当前用 `tempfile.TemporaryDirectory`）。
