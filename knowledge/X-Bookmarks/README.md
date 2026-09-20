# knowledge/X-Bookmarks/

## 用途

存放本项目产出的**用户知识库文件**：X 书签逐条 Markdown 与本地化媒体资产。

## 目录约定

```text
X-Bookmarks/
└── 2026/
    └── 09/
        ├── 20260910-196123456789.md     1 Tweet = 1 Markdown
        └── assets/
            └── 196123456789/            以 tweet_id 为目录
                ├── 3fadaf2ceea83943.jpg   文件名 = media_key（sha1(url)[:16]）+ 扩展名
                └── cf1939a0c2c6b71d.png
```

- 文件名格式：`{yyyymmdd}-{tweet_id}.md`
- 媒体目录：`assets/{tweet_id}/`，文件名为 `{media_key}{ext}`（与 SQLite `media.media_key` 一一对应），
  内容哈希一致时跳过，因此可重复运行而不产生重复文件
- Markdown 只引用同目录下的相对路径资源，保证知识库**自包含**

## 红线

1. 不允许把程序状态（SQLite、游标、日志）写进本目录。
2. 不允许引用项目外部的媒体路径（例如上游 `~/.fieldtheory/bookmarks/media`）。
3. 覆盖已存在的 `.md` 文件前必须确认（幂等逻辑默认跳过内容未变化的文件）。
4. 未经用户确认，不得删除本目录下任何文件。

## 状态

Phase 8 时点（2026-09-20）：5 份 Markdown（`2026/{03,06,09}/`）+ 6 个媒体资产（`assets/{tweet_id}/`）。
Markdown 生成见 Phase 7，媒体本地化见 Phase 8（`python -m src.cli media`）。
