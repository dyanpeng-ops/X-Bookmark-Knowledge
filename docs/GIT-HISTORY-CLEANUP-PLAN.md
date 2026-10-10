# Git 历史中的真实书签标识：清理预案（**待用户裁决**）

> 状态：**方案，未执行**。本文件只做事实陈述、选项对比与影响分析。
> 相关提交：`4922ae4`（受控文件脱敏）——**只清了工作树，未清历史**。

## 一、事实

- 真实书签标识（tweet_id / 作者 handle / 显示名）曾出现在 **5 个受控文件**中：
  `PLAN.md`、`CHANGELOG.md`、`tests/test_markdown.py`、`tests/test_normalizer.py`、
  `schema/bookmark.schema.json`（仅 description 举例）。
- `4922ae4` 已把这些文件替换为合成值；**当前工作树与 `git grep` 全量扫描受控文件 = 0 命中**。
- **但这些标识仍存在于 `4922ae4` 之前的所有提交中**，任何 clone 都能取到。
- 这些值本身：tweet_id（公开推文标识）与公开账号的 handle/显示名——**不是凭据**，
  但属"用户书签集合"的片段（反映用户收藏了谁）。

## 二、选项对比

| 选项 | 做法 | 影响 | 风险 |
|---|---|---|---|
| **A 不处理** | 保持现状；仓库为**私有** | 无 | 协作者/平台若可读，仍可见历史片段 |
| **B 重写历史** | `git filter-repo --replace-text` 或 BFG 清除这些字符串 → 强推 | **所有受影响提交之后的 SHA 全部改变** | ① 破坏所有 clone（需重新克隆或强同步）；② **审计证据失效**（见下）；③ 不可逆（需先做完整备份） |
| **C 另起新仓库** | 导出当前工作树为新仓库、旧库归档只读 | 历史干净、无强推 | 需迁移 remote/CI；旧库仍留副本（除非删除） |

### B 选项的**关键副作用：会作废审计基线**

本项目每个审计包在 `audit-manifest.json` 里声明 `base_commit` / `head_commit` / `git_range`，
审计方按这些 SHA 复核 diff（例如"把 diff 应用到 `fb14bdc` 后与 `c604da1` 逐字节一致"）。
**一旦重写历史，这些 SHA 全部不存在或对不上** ⇒ 已有审计结论的"可复核性"被破坏。
若选 B，必须同时：

1. 把既有 run 标记为 `SUPERSEDED`（或记录"历史已重写，基线失效"）；
2. 之后所有审计包改用重写后的新 SHA，并重跑一遍基线（这本身又需要一轮审计）。

## 三、建议（供裁决，不自作决定）

- **若把这些标识视为可接受**（私有仓库 + 非凭据）⇒ **选 A**，并把本文件作为"已知并接受"的记录；
- **若要彻底清除** ⇒ **选 C 优于 B**：另起干净仓库可避免强推与历史改写带来的一连串失效；
  且应在**下一轮审计之前**完成，否则每多一轮审计，需要失效重做的基线就更多。

## 四、若选 B 的具体步骤（供参考，**未执行**）

```bash
# 0) 先做完整备份（含所有分支与 tag）
git clone --mirror <repo> <backup>.git

# 1) 用 filter-repo 按清单替换（清单文件含真实标识，须放在仓库外、用完即删）
git filter-repo --replace-text /path/outside/repo/denylist-replace.txt

# 2) 验证：全历史不得再命中
git rev-list --all | while read c; do git grep -I -n -F "<token>" "$c" -- . ; done

# 3) 强推（会改写远端历史）
git push --force-with-lease origin --all && git push --force-with-lease origin --tags
```

> 清单文件本身包含真实标识，**必须**放在仓库外并事后销毁（与 `config/pii-denylist.txt` 同规矩）。

## 五、与流水线的关系

自动化侧已有 `config/pii-denylist.txt`（仓库外）与出包前的 `C9` 扫描，
可**防止未来再泄漏**；本文件处理的是**已经进入历史**的部分——两者互补。
