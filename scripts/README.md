# scripts/

## 用途

存放运维脚本。**必须兼容 Windows PowerShell 5.1**（本机无 pwsh 7）。

## 计划文件

| 文件 | 作用 | 阶段 |
| --- | --- | --- |
| `install-scheduler.ps1` | 注册 Windows 计划任务（默认每天 08:00 执行 `python -m src.cli sync`） | Phase 13 |
| `uninstall-scheduler.ps1` | 注销计划任务 | Phase 13 |
| `run-sync.ps1` | 计划任务实际调用的包装脚本：激活 venv、写日志、返回退出码 | Phase 13 |

## 计划任务要求（Phase 13）

- 名称：`XBookmarkKnowledge-Sync`（可在 `config.yaml` 的 `scheduler.task_name` 修改）
- 默认时间：每天 08:00
- 无交互运行；禁止任何会等待输入的参数
- 输出写 `data/logs/YYYY-MM-DD.log`
- 失败返回非零退出码（供 Task Scheduler 记录）
- 支持手工运行同一条命令
- 可通过 `uninstall-scheduler.ps1` 完整关闭

## 安全约定

- 脚本中不得出现任何 Cookie / Token / Secret 的字面值。
- 脚本不得修改 `knowledge/` 下的文件，只负责调度与日志。

## 当前可用命令（Phase 8 起）

本项目自身的入口是 `python -m src.cli`；`scripts/` 下的 PowerShell 脚本属 Phase 13，尚未实现。

```powershell
# 项目根目录
.\.venv\Scripts\python.exe -m src.cli sync               # 采集 + 幂等入库 + 报告
.\.venv\Scripts\python.exe -m src.cli sync --skip-collect  # 只入库已有上游数据（离线）
.\.venv\Scripts\python.exe -m src.cli media              # 上游媒体 -> 知识库 assets/（Phase 8 起）
.\.venv\Scripts\python.exe -m src.cli media --dry-run    # 只解析并报告，不写文件、不写数据库
.\.venv\Scripts\python.exe -m src.cli process            # 由 data/raw/ 生成 Markdown（Phase 7 起）
.\.venv\Scripts\python.exe -m src.cli process --overwrite # 内容变化时允许覆盖既有 Markdown（默认拒绝）
.\.venv\Scripts\python.exe -m src.cli status --json      # 只读状态（机器可读）
.\.venv\Scripts\python.exe -m src.cli doctor             # 环境自检（退出码 0/1）
```

退出码约定：`0` 成功、`1` 业务失败（有条目入库/本地化/处理失败）、`2` 配置错误、`3` 上游失败。

流水线顺序：`sync → media → process`（`process` 读取 `media` 写入的知识库内媒体路径）。

媒体幂等语义（Phase 8）：目标文件已存在且 SHA-256 与上游源一致 → `unchanged`（不重写）；
源内容变化 → 覆盖重写；源缺失 → 只该行 `FAILED`（`media.error_message` + `attempts`），其余照常。

Markdown 幂等语义（Phase 7）：内容未变 → 跳过；内容已变 → 默认**拒绝覆盖**并计入 `conflicts`
（退出码 1），除非显式 `process --overwrite`。

注意：上游 CLI 在 PowerShell 中必须写作 `fieldtheory` / `fieldtheory.cmd`
（`ft` 是 `Format-Table` 的内置别名）；本项目已在 `config/config.yaml` 固定使用 `fieldtheory.cmd`。

## 状态

Phase 8 时点：本目录仅含本说明文件，脚本在 Phase 13 实现。

