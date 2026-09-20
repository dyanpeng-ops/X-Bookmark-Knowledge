"""时间工具：所有持久化时间戳统一为 ISO 8601 UTC 字符串。

约定（Phase 4）：
- 数据库中的时间列一律保存 ``YYYY-MM-DDTHH:MM:SSZ``（UTC）。
- 业务代码通过 ``utc_now_iso()`` 获取当前时间，禁止直接使用本地时间。
- 测试可传入固定的 ``now`` 以获得确定性结果。
"""

from __future__ import annotations

from datetime import datetime, timezone

TIMESTAMP_FORMAT = "%Y-%m-%dT%H:%M:%SZ"


def utc_now(now: datetime | None = None) -> datetime:
    """返回 UTC 时间；``now`` 为 None 时取当前时间。

    传入 naive datetime 时按 UTC 解释，避免依赖本机时区。
    """
    if now is None:
        return datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    return now.astimezone(timezone.utc)


def utc_now_iso(now: datetime | None = None) -> str:
    """返回 ``YYYY-MM-DDTHH:MM:SSZ`` 格式的 UTC 时间戳。"""
    return utc_now(now).strftime(TIMESTAMP_FORMAT)


def parse_iso(value: str) -> datetime:
    """解析本模块生成的时间戳；非法或非 UTC 输入会抛出 ValueError。"""
    if not isinstance(value, str) or not value:
        raise ValueError("timestamp must be a non-empty ISO 8601 UTC string")
    try:
        parsed = datetime.strptime(value, TIMESTAMP_FORMAT)
    except ValueError as exc:  # pragma: no cover - defensive
        raise ValueError(f"unsupported timestamp format: {value!r}") from exc
    return parsed.replace(tzinfo=timezone.utc)
