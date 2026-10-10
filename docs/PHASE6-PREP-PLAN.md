# Phase 6（跨平台）预备方案：9 个平台语义失败的根因与最小修复

> 状态：**方案（待批准）**。本文件只做根因分析、修复选项与验收设计，**未执行任何修复**。
> 依据：Phase 4 任务书 R2「既有 9 个平台语义测试失败构成噪声，容易掩盖真实回归；
> 每步用失败集快照比对判定回归（Phase 6 重建基线）」。

## 一、为什么值得做

当前全量回归固定为 **650 用例 / 9 失败**。这 9 个失败在每个审计包里都要额外解释一遍
（"全部为平台语义噪声"），既是噪声也削弱了"失败集比对"这一回归判据的可读性。
Phase 6 把它们清零后，**任何失败都是真信号**——回归判定从"与基线 9 条逐条比对"简化为"0 失败"。

## 二、根因分类（已逐条实测定位，非推测）

| # | 测试 | 根因 | 归类 |
|---|---|---|---|
| 1 | `test_config_value_beats_machine_env_var` | macOS `/var` 是 `/private/var` 的软链：产品存**已解析**路径，测试比**未解析**路径 | A 路径解析 |
| 2 | `test_relative_paths_resolve_against_project_root` | 同上 | A |
| 3 | `test_require_file_false_falls_back_to_defaults` | 同上 | A |
| 4 | `test_links_fetches_pages_and_records_knowledge_paths` | 同上：断言的 `self.knowledge` 未解析，库里 `content_path` 已解析 | A |
| 5 | `test_media_command_copies_files_and_records_knowledge_paths` | 桩用 `Path("C:\\synthetic\\...\\SAMPLE0000000001.png").name` ——POSIX 上反斜杠**不是分隔符**，实测 `PurePosixPath.name` 返回整串路径 ⇒ 媒体文件被写成带反斜杠的怪名字；测试按 `SAMPLE0000000001.png` 读取故 404 | B 桩的 Windows 路径假设 |
| 6 | `test_media_failure_is_isolated_and_exits_non_zero` | 同 5（`unlink` 目标不存在） | B |
| 7 | `test_resolve_path_helper` | 断言 Windows 盘符语义（`C:/x/C:/abs` → `C:/abs`）；POSIX 上 `C:/abs` 非绝对路径 | C 盘符语义 |
| 8 | `test_cross_drive_lookup_path_does_not_fail_the_record` | 断言跨驱动器的相对路径形状（`![](Z:/elsewhere/abc.png)`） | C |
| 9 | `test_stale_absolute_path_is_resolved_into_configured_media_dir` | 断言基于盘符的"绝对路径"判定 | C |

**共同结论：9 个都在测试/桩侧，未发现产品缺陷。**
但第 5/6 条的桩 bug（反斜杠当分隔符）会**掩盖**真实的媒体落盘回归——它让文件根本没被正确创建，
所以属于"必须先修桩，否则 Phase 8 媒体验收不可信"。

## 三、最小修复方案（按类）

| 类 | 修复 | 位置 | 是否动产品代码 |
|---|---|---|---|
| **A**（4 条） | 断言两侧统一 `Path.resolve()`（或比较 `os.path.realpath`）；**不放松断言强度**，只是消除软链差异 | `tests/test_config.py`、`tests/test_external.py` | 否 |
| **B**（2 条） | 桩改取 basename：`PureWindowsPath(localPath).name`（或 `localPath.replace("\\", "/").rsplit("/", 1)[-1]`），与平台无关 | `tests/support/stub_fieldtheory.py` | 否 |
| **C**（3 条） | 保留断言但**按平台参数化**：`sys.platform == "win32"` 时断言盘符语义，否则断言等价 POSIX 语义（或标 `@unittest.skipUnless(os.name == "nt", ...)` 并**补一条 POSIX 等价断言**，避免"跳过即无声丢失覆盖"） | `tests/test_config.py`、`tests/test_media.py` | 否 |

**红线（防"改测试来过关"）**：每条修复都必须保持原断言的**语义强度**——
A 类只统一路径规范化；C 类用平台参数化/等价断言替代，**不得**改成 `assertTrue(True)` 或删除断言。
建议每条同时保留"修复前失败、修复后通过"的对照记录。

## 四、验收标准（Phase 6 完成后）

| # | 判据 |
|---|---|
| E1 | macOS 全量回归 **0 失败 0 错误**（不再有"9 条已知噪声"） |
| E2 | Windows 路径语义仍被覆盖：C 类改参数化后，`win32` 分支断言仍在（可用桩跑一次验证） |
| E3 | 失败集比对法从"与 9 条基线逐条比"升级为"**期望 0 失败**"，后续回归判据更硬 |
| E4 | 每条修复前后各留一次定向运行记录（`unittest tests.test_config -v` 等） |
| E5 | 不修改产品行为；`src/` 无改动（若确需改，须单独立项并说明理由） |

## 五、待验证清单（批准后执行）

| # | 命令 | 目的 | 影响 |
|---|---|---|---|
| 1 | `.venv/bin/python -m unittest tests.test_config tests.test_media tests.test_external -v`（修复前） | 记录基线失败明细 | 离线、临时目录；约 3 秒 |
| 2 | 按方案修改 A/B/C 三类（测试与桩） | 消除 9 个平台语义失败 | 写盘（测试/桩文件） |
| 3 | 同一命令（修复后） | 确认 3 个模块全绿 | 同上 |
| 4 | `.venv/bin/python -m unittest discover -s tests -t .` | 全量应为 **0 失败**（650 用例） | 同上；约 6 秒 |
| 5 | 更新 `PLAN.md`/`CHANGELOG.md` 并把基线改为"期望 0 失败" | 固化新判据 | 写盘（文档） |

**需你批准后我才执行**（Phase 6 属下一 Phase，且改动测试基线会影响所有后续审计判定）。
