# Phase 7（Git 同步）预备方案：`.gitignore` 与设计规格**相反**（待裁决）

> 状态：**方案，未执行**。本文件给出实证、后果与选项；**我没有改动 `.gitignore`**（原因见文末）。

## 一、规格要求（`ARCHITECTURE.md` §8.2 / §8.2.1）

**应该 Git 同步**：
- `schema/`、`src/`、`config/`（含 example）、`scripts/`
- **`data/normalized/`（Canonical JSON）**
- **`knowledge/X-Bookmarks/**/*.md`（Markdown 正文）**
- **`knowledge/X-Bookmarks/**/assets/**`（媒体，§8.2.1 默认「媒体入 Git」）**

**不应该 Git 同步**：凭据 / session / token / browser profile / `data/raw/`（上游原始）/
`data/state/*.db` / SQLite 锁文件 / 临时文件 / logs / cache。

§8.1 的同步链路：`Canonical Data（normalized + Markdown） → Git → 每台机器各自 rebuild-index`；
并明确**禁止** SQLite 经 Git 同步。

## 二、实测现状：**恰好相反**

`git check-ignore -v` 输出（本机实测）：

```text
$ git check-ignore -v data/normalized/1900000000000000101.json
.gitignore:15:data/                              data/normalized/1900000000000000101.json
$ git check-ignore -v knowledge/X-Bookmarks/test.md
.gitignore:48:knowledge/X-Bookmarks/*            knowledge/X-Bookmarks/test.md
```

即 `.gitignore` 第 15 行的 `data/` 与第 48 行的 `knowledge/X-Bookmarks/*`
把 §8.2 要求同步的**三类内容全部挡住**（Markdown、assets、normalized JSON）。

## 三、后果（不是风格问题，是功能问题）

| # | 后果 |
|---|---|
| C1 | **§8.1 的跨设备链路无法成立**：没有任何 Canonical 数据会进入 Git，Mac/Windows 之间无从同步 |
| C2 | **`rebuild-index` 依赖 `normalized/*.json`**（本实现只扫该目录）：即使 Markdown 同步过去，新机器也**无法重建内容索引** |
| C3 | **富化内容会不可逆丢失**：按 §8.2.1，article 正文与 quoted_tweet **只存在于 normalized JSON**，`data/raw/` 不含富化且不入 Git——normalized 不同步 ⇒ 换机后富化内容彻底消失 |
| C4 | **Markdown 引用会断裂**：assets 不入 Git ⇒ `![](assets/...)` 在另一台机器上指向不存在的文件 |

## 四、选项（附**精确补丁**，供裁决后一键执行）

### 选项 A：按 §8.2 实现（Markdown + normalized + assets 入 Git）

```gitignore
# 允许 Canonical 数据入 Git（ARCHITECTURE §8.2 / §8.2.1）
!data/normalized/
!data/normalized/**
!knowledge/X-Bookmarks/**
```
（需保证 `data/` 与 `knowledge/*` 的忽略规则不被 `**` 回溯覆盖，必要时把它们改成更精确的规则。）

**代价**：真实书签内容（正文、作者 handle/显示名、媒体文件）进入 **GitHub 私有仓库**。
这是 §8.1 的**既定设计**，但**与你当前的"不触碰真实数据"边界直接冲突**，且我方的自动化
提交使用 `git add -A`——若不加护栏，可能在你未逐次确认的情况下把真实内容推上去。

### 选项 B：只同步 Markdown（normalized 留本地）

仓库体积小、正文可跨机阅读；但 **C2/C3 依然存在**（无法重建索引、富化丢失）。
需要额外机制把 normalized 带过去，否则等于放弃 §8.1。

### 选项 C：完全不进 Git，改用非 Git 同步（云盘/同步目录）

与 §8.1 冲突，需要重新定义"跨设备同步"机制（属**架构决策**，我不自行改）。

**我的建议**：选 **A**，但必须同时满足三条护栏：
1. 确认仓库为**私有**（当前 remote 为 GitHub 私有仓库）；
2. 引入 **提交前护栏**：拒绝把 `data/raw/`、`data/state/*.db`、凭据/令牌类文件、
   `logs/`、cache 纳入提交（自动化侧已提供 `scripts/guard-staged`，见下）；
3. 明确 **assets 体积策略**（§8.2.1 的默认是"媒体入 Git"；若体积失控则降级为"媒体不入 Git +
   每机 `media` 补拉"，那是一次可逆的 `.gitignore` 改动）。

## 五、配套护栏（我已实现，自动化侧）

`X-Bookmark-Knowledge-Automation/scripts/guard-staged`：
- 输入：`git diff --cached --name-only`；
- **拒绝**（退出码非 0）当暂存集中出现：`data/raw/`、`data/state/`、`*.db`、`cookies*`/`tokens*`/
  `credentials*`/`.env*`、`*.log`、`__pycache__`、`*.tmp`；
- 并对暂存 diff 扫描凭据特征（`auth_token`、`ct0`、`client_secret`、私钥头）与真实书签标识
  （复用出包用的 `config/pii-denylist.txt`）。

**用途**：选项 A 生效后，每次提交前先跑它；也可作为 `pre-commit` 钩子（钩子安装属另一决策）。

## 六、为什么我**不自行**改 `.gitignore`

1. 改完之后的**下一个 `git add -A`（我的提交流程正在用）就可能把真实知识库纳入提交**——
   这属于"触碰真实数据"，超出当前授权边界；
2. 媒体入 Git 会显著增大仓库（不可逆地进入历史），属需你知情的取舍；
3. 该决定影响数据外发面（私有仓库仍是"外发"），必须由你拍板。

## 七、裁决后我方将执行的验收（供参考）

| 步骤 | 验证 |
|---|---|
| 应用补丁 | `git check-ignore -v data/normalized/x.json` **不再命中**；`knowledge/X-Bookmarks/a/b.md` 不命中 |
| 护栏 | 故意 `git add data/raw/x.json` → `guard-staged` 必须拒绝（非零退出） |
| 端到端 | 在一台机器 `normalize --apply` + `render --apply` → 提交 → 另一台 clone → `rebuild-index` 成功且内容索引与源机一致 |
| 体积 | 记录 `.git` 增长；超过约定阈值则触发 §8.2.1 的降级方案 |
