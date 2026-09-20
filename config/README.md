# config/

## 用途

存放本项目的配置。

## 文件规则

| 文件 | 是否进 Git | 说明 |
| --- | --- | --- |
| `config.example.yaml` | ✅ | 模板，不含任何真实密钥 |
| `config.yaml` | ❌ | 本机真实配置，由用户从模板复制后修改 |
| `.gitignore` | ✅ | 本目录的忽略规则（白名单式） |

## 使用方式

```powershell
Copy-Item config\config.example.yaml config\config.yaml
```

## 安全要求

1. `config.yaml` 严禁提交到 Git。
2. 密钥类信息一律通过**环境变量**注入，不写进任何文件；配置里只允许出现环境变量名。
3. 禁止在 `config.yaml` 中粘贴 `ct0` / `auth_token` / `client_secret` 的真实值。
4. 任何日志与错误输出都不得打印密钥值，只允许打印"是否存在"的布尔结果。

## 备注

- 配置解析器与 schema 校验在 Phase 4 实现（需引入 YAML 解析依赖，理由将记入 `CHANGELOG.md`）。
- 当前模板中的键均为"设计意图"，实现进度以 `PLAN.md` 为准。
