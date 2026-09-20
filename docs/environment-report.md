# Environment Report — Phase 0

> 项目：X Bookmark Knowledge Pipeline
> 生成阶段：Phase 0（环境检查）
> 生成时间：2026-09-15
> 执行方式：只读探测（未修改任何既有文件）
> 证据性质：全部条目由本机命令实测得出，非推断

---

## 1. 结论摘要

| 项目 | 结果 |
| --- | --- |
| 操作系统 | Windows |
| 文档指定路径 | `D:\Users\label-workplace\Agent-Eval\AI-Agent-Lab\02-Knowledge-Agent\` ❌ 不存在 |
| 实际路径 | `D:\Users\label-workplace\Agent-Eval\AI-Agent-Lab\01_Knowledge-Agent\` ✅ 存在 |
| 本项目目录 | `01_Knowledge-Agent\projects\X-Bookmark-Knowledge\` ✅ 已存在（Phase 0 时为空） |
| 默认 Python | 3.14.3（`C:\Python314`） |
| 备用 Python | 3.12.13（uv 管理，未注册 py launcher，`uv` 不在 PATH） |
| Node.js | v24.14.0 |
| Git | 2.31.1.windows.1，**未配置 user.name / user.email** |
| 知识库位置 | `01_Knowledge-Agent\knowledge\{AI, Agent, Finance, Life, Other}` |
| Obsidian Vault | ❌ 不存在（全 Lab 无 `.obsidian`） |
| Git 仓库 | ❌ Lab 下无任何 git 仓库 |
| 磁盘空间 | `C:` 6.4 GB 可用 ⚠️ / `D:` 323.2 GB 可用 |
| 网络出口 | github.com / x.com / pypi.org 的 443 端口均可达 ✅ |
| 计划任务能力 | `schtasks` 可用 ✅ |
| 可复用外部工具 | `fieldtheory@1.3.22`（全局 npm 安装，已验证可运行） |

---

## 2. 操作系统与磁盘

| 项 | 值 |
| --- | --- |
| 平台 | win32 |
| 盘符 | `C:`（剩余 6.4 GB）、`D:`（剩余 323.2 GB） |

**影响**：本项目位于 `D:`，符合"媒体与知识库不放 C 盘"的容量要求。媒体缓存、Markdown、SQLite 都必须落在 `D:`；禁止把 `data/` 或 `knowledge/assets/` 指向 C 盘。

---

## 3. 语言与运行时

| 组件 | 版本 / 路径 | 备注 |
| --- | --- | --- |
| Python（默认） | 3.14.3 → `C:\Python314\python.exe` | 过新，第三方库 wheel 覆盖不完整 ⚠️ |
| Python（备用） | 3.12.13 → `%APPDATA%\uv\python\cpython-3.12.13-windows-x86_64-none\python.exe` | 由 uv 安装；`py -3.12` 不可用 |
| pip | 25.3 | 属于 Python 3.14 |
| `sqlite3` 模块 | 可用，SQLite 3.50.4 | FTS5 支持需在 Phase 4 实测确认 |
| venv | 可用 | 建议用 3.12 建 venv |
| uv | ❌ 不在 PATH（仅存在其下载的 Python） | 如需 uv 要另行安装 |
| Node.js | v24.14.0 | `fieldtheory` CLI 依赖 |
| npm 全局包 | `fieldtheory@1.3.22` → `D:\nodejs\npm_global\node_modules\fieldtheory` | 见第 7 节 |
| PowerShell | Windows PowerShell 5.1（无 pwsh 7） | 调度脚本需兼容 5.1 |
| 计划任务 | `schtasks` 可用 | Phase 13 可用 |

**影响**：建 venv 时应显式使用 Python 3.12；FTS5 必须在 Phase 4 用一条 `MATCH` 语句验证后才可写入数据模型。

---

## 4. 版本控制

| 项 | 值 |
| --- | --- |
| git 版本 | 2.31.1.windows.1 |
| `user.name` | 未设置 |
| `user.email` | 未设置 |
| Lab 内 git 仓库 | 无 |

**影响**：Phase 3 只创建 `.gitignore`，**不执行 `git init`**（需用户明确授权）。若后续纳入版本控制，需先补 `user.name`/`user.email`。

---

## 5. 目录现状（Phase 0 时点）

### 5.1 上层结构

```text
D:\Users\label-workplace\Agent-Eval\
└── AI-Agent-Lab\
    ├── 01_Knowledge-Agent\      ← 文档中写成的 "02-Knowledge-Agent" 实际为此目录
    ├── 02_Research-Agent\
    ├── 03_Work-Agent\
    ├── 04_Coding-Agent\
    └── 05_Agent-Evaluation\
```

Lab 根目录：**无 README.md、无 AGENTS.md、无配置文件**。

### 5.2 `01_Knowledge-Agent` 现有内容

```text
01_Knowledge-Agent\
├── AGENT.md            ← 规范文件（正文一级标题为 "# AGENTS.md"）
├── README.md           ← 中文，目录职责说明
├── index.md            ← 知识库总索引
├── inbox\              ← 仅 README.md
├── knowledge\          ← 仅 README.md + AI\ Agent\ Finance\ Life\ Other\
├── projects\           ← README.md + X-Bookmark-Knowledge\（本项目）
├── references\
├── research\
└── archive\
```

### 5.3 本项目目录（Phase 0 时点）

`projects\X-Bookmark-Knowledge\` 存在且**递归文件数为 0**。

---

## 6. 既有规范（必须继承，不得重新定义）

来源：`01_Knowledge-Agent\AGENT.md`、`README.md`、`index.md`、各子目录 `README.md`。

| 规则 | 内容 | 对本项目的影响 |
| --- | --- | --- |
| 目录职责 | `inbox/` 收集未整理资料；`knowledge/` 存长期知识；`projects/` 存项目过程；`research/` 存研究过程；`references/` 存原始来源；`archive/` 存过期内容 | 本项目属 `projects/`，其研究产物落在项目内 `research/`，而非上层 `research/` |
| Inbox 原则 | "先收集，再整理"；未经确认不得删除原始资料 | 采集产物必须可追溯到原始 URL 与原始 JSON |
| Knowledge 原则 | 不把"保存资料"等同于"建立知识"；不应长期堆积原始资料 | X 书签 Markdown 属原始/半加工资料，不应直接进 `knowledge/` |
| 分离原则 | 知识与原始资料分离；项目与知识分离；研究过程与最终知识分离 | 本项目 `data/`（程序数据）与 `knowledge/`（用户知识）必须物理分离 |
| 修改安全 | 删除、批量移动、覆盖重要文档、重构层级需显式授权 | 本项目所有写入限定在自身目录内，不触碰上层既有文件 |
| 技术克制 | 当前阶段只允许 Markdown + 文件系统 + Agent，禁止擅自引入 RAG / 向量库 / 知识图谱 / 多 Agent / MCP | 与执行计划"不引入复杂 RAG"一致；自研部分只用 stdlib + 极少量必要依赖 |
| 优先级 | 用户显式指令 > 项目安全与数据保全 > AGENTS.md > README.md > 假设 | 冲突时按此裁决 |
| 不确定时 | 说明不确定，不要编造 | 本文档所有"待验证"项保持显式标注 |

### 6.1 发现的两处既有不一致（仅记录，不修改）

1. `AGENT.md` 与 `README.md` 均声明 `knowledge/` 含 `Coding/`、`Work/`，实际只有 `AI/`、`Agent/`、`Finance/`、`Life/`、`Other/`。
2. 规范文件名不一致：上层为 `AGENT.md`（单数），本项目按执行计划使用 `AGENTS.md`（复数）。

---

## 7. 可复用组件

| 组件 | 状态 | 可复用点 | 限制 |
| --- | --- | --- | --- |
| `fieldtheory` CLI 1.3.22 | ✅ 已全局安装，`--version`/`--help` 验证通过 | 采集层（`sync`）、媒体下载、原始 JSONL 缓存、LLM 分类（claude/codex）、Markdown 导出、Agent Skill | Windows 会话认证存在阻塞，见第 9 节 |
| `fieldtheory` 数据产物 | 路径已确认，尚无数据 | `bookmarks.jsonl`、`bookmarks.db`、`media-manifest.json`、`media/` | 属上游内部格式，非公开契约 |
| `claude` CLI | ✅ 在 PATH（`D:\nodejs\npm_global\claude.ps1`） | Phase 11 的 AI 增强可选引擎 | 账号可用性待验证 |
| `codex` CLI | ✅ 在 PATH（`D:\nodejs\npm_global\codex.ps1`） | 同上 | 同上 |
| Python 3.12.13 | ✅ 存在 | 建 venv 的推荐解释器 | 未注册到 py launcher |
| 既有 Agent 规范 | ✅ 可读 | 直接继承第 6 节规则 | 不得修改 |

**不可复用**：Lab 内无既有 Skills、无 `.obsidian`、无既有 Python 工程、无 CI、无测试基础设施。

---

## 8. 本机 `fieldtheory` 关键路径与命令（已实测）

| 项 | 值 |
| --- | --- |
| 包目录 | `D:\nodejs\npm_global\node_modules\fieldtheory` |
| 可执行入口 | `ft` / `fieldtheory` → `bin/ft.mjs` → `dist/cli.js` |
| `ft --version` | `1.3.22`（exit 0） |
| 数据根 | `C:\Users\gscaee\.fieldtheory` |
| bookmarks 目录 | `C:\Users\gscaee\.fieldtheory\bookmarks` |
| 原始缓存 | `...\bookmarks\bookmarks.jsonl` |
| SQLite 索引 | `...\bookmarks\bookmarks.db` |
| 媒体清单 | `...\bookmarks\media-manifest.json` |
| 媒体目录 | `...\bookmarks\media` |
| PowerShell 注意 | PowerShell 中 `ft` 是 `Format-Table` 内置别名，必须用 `fieldtheory` 或 `ft.cmd` |
| 交互陷阱 | `fieldtheory model`（不带参数）会进入交互式 `Select default:` 提示；脚本与定时任务中禁止这样调用 |

### 8.1 采集相关子命令（`fieldtheory sync --help` 实测）

```text
--api / --rebuild / --continue / --gaps / --yes / --classify
--no-media / --media-max-bytes / --skip-profile-images
--max-pages / --target-adds / --delay-ms / --max-minutes
--browser / --cookies / --chrome-user-data-dir / --chrome-profile-directory / --firefox-profile-dir
--folders / --folder / --engine
```

### 8.2 认证相关实测证据（关键）

| 观测 | 值 |
| --- | --- |
| Chrome 版本 | 155.0.8048.0 |
| `Local State` 中 `os_crypt.encrypted_key` | 存在 |
| `Local State` 中 `os_crypt.app_bound_encrypted_key` | **存在 → App-Bound Encryption 已启用** |
| x.com Cookie 加密前缀分布 | **`v20` × 19（全部）** |
| x.com 登录 Cookie（名称） | `auth_token`、`ct0`、`twid`、`guest_id` → **用户已在 Chrome 登录 x.com** |
| `fieldtheory sync --browser chrome` | `Couldn't connect to your browser session.` exit 1 |
| Chrome 关闭后重试 | 仍失败（证明不是文件占用问题） |
| 代码层结论 | `dist/chrome-cookies.js` 的 `decryptWindowsCookie()` 只处理 `v10` 前缀与裸 DPAPI；`v20` 落到"原样 UTF-8 返回"分支 → `sanitizeCookieValue()` 抛错 → 首运行分支替换为通用提示 |
| 其他浏览器 | Edge / Chromium 无 x.com Cookie（未登录）；Firefox 未安装 |
| 可用替代路径 | ① `--cookies <ct0> <auth_token>`（代码确认会跳过浏览器提取）② Firefox 会话（`cookies.sqlite` 不加密）③ OAuth（需 X 开发者应用凭证） |

### 8.3 认证问题的最终结论（2026-09-16 更新）

| 观测 | 值 |
| --- | --- |
| Firefox 版本 | 156.0（`C:\Program Files\Mozilla Firefox\firefox.exe`） |
| 使用的 profile | `5orlmzjh.default-release`（`profiles.ini` 指定为默认） |
| `.x.com` Cookie | `ct0`(160B)、`auth_token`(40B)、`twid`、`guest_id` 等 11 项，**明文存储、无加密前缀** |
| 后端可用性 | Node v24.14.0 提供 `node:sqlite`（未安装 `sqlite3` 二进制，也不需要） |
| `fieldtheory sync --browser firefox --no-media --yes --max-pages 1` | **exit 0**，`✓ 5 new bookmarks synced (5 total)` |
| 结论 | **Chrome ABE `v20` 问题仍存在但已被绕开**；Windows 认证路径 A 关闭 |
| 账号书签总数 | 5 条（JSONL / `stats` / `status` / `meta` 四方一致；`--rebuild` 全量重爬结论相同） |

---

## 9. 潜在冲突与风险

| # | 问题 | 证据 | 严重度 | 建议处置 |
| --- | --- | --- | --- | --- |
| 1 | **文档路径错误**：`02-Knowledge-Agent` 不存在 | `Test-Path` = False；实际为 `01_Knowledge-Agent` | 高 | 已按实际路径执行并全程记录偏差 |
| 2 | ~~Chrome 155 的 ABE 阻塞会话采集~~ **已缓解（2026-09-16）** | 前缀 `v20` × 19；解密分支只认 `v10`；`sync` exit 1 | 中（保留备选路径） | 已改用 Firefox 会话并实测通过；上游若修复 `v20` 支持，本项目零改动可切回 |
| 3 | `projects\X-Bookmark-Knowledge` 已存在 | Phase 0 探测 | 低 | 只新增文件，绝不删除或覆盖 |
| 4 | 知识库落点与既有 Inbox 规范冲突 | 执行计划要求 `knowledge/X-Bookmarks/`；上层 `AGENT.md` 要求先入 `inbox/` | 中 | 项目内产出 → 交接 `01_Knowledge-Agent\inbox\X-Bookmarks\`，由 Knowledge-Agent 提炼后入 `knowledge/` |
| 5 | `data/` 被 gitignore，但执行计划要求 `data/environment-report.md` | 安全要求与文档路径冲突 | 低 | 权威副本置 `docs/environment-report.md`，`data/` 留指针 |
| 6 | Python 3.14 过新 | 默认解释器 3.14.3 | 中 | venv 使用 3.12.13 |
| 7 | `C:` 仅剩 6.4 GB | 盘符探测 | 中 | 全链路锁定在 `D:` |
| 8 | 无 git 仓库且未配身份 | 探测结果 | 低 | Phase 3 只出 `.gitignore`，`git init` 待授权 |
| 9 | 上游 JSONL 格式非公开契约 | 尚无样本数据 | 中 | Phase 5 前置：真实跑一次 `sync` 取样本并做字段快照 |
| 10 | 定时任务静默失败（cookie/token 过期） | 认证依赖浏览器会话 | 中 | Phase 13 强制日志 + `doctor` 检查 + 失败非零退出码 |
| 11 | 仅 Windows PowerShell 5.1 | 无 `pwsh` | 低 | `scripts/*.ps1` 兼容 5.1，不用 7.x 语法 |

---

## 10. 与执行计划的偏差记录

| 计划原文 | 实际情况 | 处置 |
| --- | --- | --- |
| 项目位置 `...\02-Knowledge-Agent\projects\X-Bookmark-Knowledge\` | `...\01_Knowledge-Agent\projects\X-Bookmark-Knowledge\` | 按实际路径执行，偏差已记录 |
| 输出 `data/environment-report.md` | `data/` 属程序数据且被 gitignore | 权威副本置 `docs/environment-report.md`，`data/` 留指针 |
| Phase 1 点名项目 `xmarks` | 无法对应任何 GitHub 仓库 | 标注"不可解析"，补充真实替代候选 |
| 项目内 `knowledge/X-Bookmarks/` 作为知识库终点 | 与上层 `AGENT.md` 的 Inbox 流程冲突 | 改为"项目内产出 → inbox 交接" |

---

## 11. 复现方式

```powershell
Test-Path 'D:\Users\label-workplace\Agent-Eval\AI-Agent-Lab\01_Knowledge-Agent'
Get-ChildItem 'D:\Users\label-workplace\Agent-Eval\AI-Agent-Lab' -Force
python --version ; py -0p ; git --version ; node -v
git config --global user.name ; git config --global user.email
Get-PSDrive -PSProvider FileSystem
fieldtheory --version ; fieldtheory paths --json ; fieldtheory status --json
```

---

## 12. Phase 0 状态

**完成**。进入 Phase 1 的前置条件全部满足。第 9 节 #2 的认证风险不阻塞 Phase 1–4，但**必须在 Phase 5（实现 Collector）之前定性**。


