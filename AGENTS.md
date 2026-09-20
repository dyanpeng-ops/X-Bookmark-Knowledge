# AGENTS.md — X Bookmark Knowledge Pipeline

> 本文件是本项目的 Agent 工作规范。
> 继承上级规范：`01_Knowledge-Agent/AGENT.md`（与本文件冲突时，按上级"优先级"章节裁决）。
> 冲突裁决顺序：**用户显式指令 > 项目安全与数据保全 > 上级 AGENT.md > 本文件 > README.md > Agent 假设**

---

## 1. 项目定位

把 X.com Bookmarks 采集为本地原始数据，加工为逐条 Markdown，写入个人知识库，并最终交由 Knowledge-Agent 做 AI 增强。

**本项目默认只做读取与本地归档，绝不修改 X.com 上的书签数据。**

---

## 2. 最高优先级原则（不可违反）

1. 先研究，后开发；技术路线未明确前不写实现代码。
2. 优先复用成熟开源项目，不重复造轮子。
3. 不因为发现一个开源项目就替换整体技术路线；先评估再决策。
4. 原始 X 数据与加工后的知识数据必须分离。
5. 每条 Tweet 以 `tweet_id` 为唯一标识。
6. 同步必须支持增量处理与幂等执行。
7. 单条 Tweet 处理失败不得导致整个同步任务失败。
8. 所有网络请求必须有 timeout、retry 与错误记录。
9. Cookie、OAuth Token、API Secret 等敏感信息**禁止**写入 Git、日志、Markdown 产物或对话记录。
10. 第一阶段不引入复杂 RAG、向量数据库、知识图谱。
11. AI 分析属后处理阶段，不得成为基础数据采集的依赖。
12. 所有重要功能必须有测试。
13. 每完成一个 Phase，更新 `PLAN.md` 与 `CHANGELOG.md`。
14. **不得未经确认删除或覆盖用户现有知识库文件**。
15. 不得跨越失败的 Phase 继续开发。

---

## 3. 目录职责（严格遵守）

```text
data/       程序数据（原始 JSON、SQLite 状态、日志）—— 被 gitignore，非知识库
knowledge/  用户知识库（逐条 Markdown 与媒体资产）—— 人类可读，可维护
config/     配置（真实配置 config.yaml 被 gitignore，仅 example 入 Git）
src/        实现代码
tests/      测试
scripts/    运维脚本（PowerShell，兼容 5.1）
docs/       项目文档（含 Phase 0 环境报告）
research/   研究过程与决策记录
```

**红线**：

- `data/` 与 `knowledge/` 不得混用；不允许把状态文件写进 `knowledge/`，也不允许把 Markdown 产物写进 `data/`。
- 所有写操作限定在本项目根目录内。**禁止**写入 `~/.fieldtheory/**`（上游数据只读）、**禁止**直接写入上级 `01_Knowledge-Agent/knowledge/**`。
- 向上层知识库的交接必须显式、可回滚，且需用户确认（见 Phase 12）。

---

## 4. 架构约定

- Collector 通过 **Adapter** 复用上游 `fieldtheory` CLI，不直接散落调用其内部模块。
- 上游数据（`bookmarks.jsonl` / `media-manifest.json` / `media/`）视为**只读输入**。
- 本项目的 SQLite 是**唯一权威状态**。
- 状态机：`NEW → COLLECTED → PROCESSED → ENRICHED → COMPLETED`，失败为 `FAILED`。
- 新增功能前先判断是否属于"Ingest / Processor / Media / External / Markdown / Scheduler / CLI"其中之一，不允许在 `cli/` 里堆放业务逻辑。

---

## 5. 编码约定

- 语言：Python（venv 固定 3.12.13，见 `PLAN.md`）。
- 依赖最小化：优先标准库；新增第三方依赖必须在 `CHANGELOG.md` 说明理由。
- 网络：统一走 `src/external/` 中的抓取封装，集中实现 timeout / retry / 重定向 / 编码探测。
- 路径：全部通过配置解析为绝对路径，禁止在代码中硬编码 `D:\...`。
- 失败处理：逐条 try/except，错误写入 `error_message` 字段与日志，绝不因单条失败中断批次。
- 幂等：任何写文件操作前先检查目标是否存在且内容哈希一致。

---

## 6. 安全约定

- `config/config.yaml`、`.env*`、`cookies*`、`tokens*`、`credentials*`、`*.db`、`data/` 全部不进 Git。
- 任何日志、异常、Markdown 中都不得出现 `auth_token`、`ct0`、`client_secret` 等值；只允许出现"是否存在"的布尔判断。
- 手工 Cookie（`fieldtheory sync --cookies`）仅限临时排障，用完立即清理 shell 历史。

---

## 7. 工作流（每个 Phase 必做）

1. 修改代码 → 2. 运行测试 → 3. 检查文件 → 4. 更新 `PLAN.md` → 5. 更新 `CHANGELOG.md` → 6. 汇报完成内容 → 7. 标记下一阶段。

Phase 顺序：`0 → 1 → 2 → 3 → 4 → 5 → 6 → 7 → 8 → 9 → 10 → 11 → 12 → 13`。

**Phase 5 前置条件（硬性）**：Windows 认证路径已打通 + 上游 JSONL 字段契约已用真实样本确认。未满足则不得开始写 Collector。

---

## 8. 修改安全

以下动作需用户显式确认：

- 删除任何文件（包括本项目内的产物）
- 批量移动或重命名知识库文件
- 覆盖已存在的 Markdown
- 重构目录层级
- 修改 `config/` 之外的项目级配置
- 向 `01_Knowledge-Agent/inbox/` 或 `knowledge/` 做任何写入

安全动作：读取、搜索、分析、生成草稿、运行只读命令、运行测试。

---

## 9. 不确定时的行为

- 不确定就说明不确定，不要编造字段名、API 行为或数据格式。
- 未实测得出的结论，必须在文档中标注 `待验证`。
- 遇到与上级规范冲突时，先停下并向用户报告冲突点与建议方案。
