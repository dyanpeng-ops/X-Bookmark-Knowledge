"""Normalizer 的错误分类（任务书 §16）。

任务书要求「至少区分」六类错误；本项目沿用既有异常名，映射关系如下
（Collector 侧异常冻结于 Phase 5，为兼容既有测试**不重命名**）：

==================== =========================================
任务书 §16 语义        本项目异常
==================== =========================================
CollectorUnavailable        ``collector.base.UpstreamUnavailableError``
CollectorAuthenticationError ``collector.base.UpstreamAuthError``
CollectorContractError      ``collector.base.UpstreamContractError``
CollectorTimeout            ``collector.base.UpstreamTimeoutError``
NormalizationError          :class:`NormalizationError`（本模块）
CanonicalValidationError    ``canonical.validate.CanonicalValidationError``
==================== =========================================

本模块同时导出 ``RawDataContractError``（Raw 边界结构非法）以便 Normalizer
的使用者只 import 一个错误模块。
"""

from __future__ import annotations

from ..canonical.validate import CanonicalValidationError
from ..collector.raw_data import RawDataContractError


class NormalizationError(ValueError):
    """``RawCollectorData → CanonicalBookmark`` 映射失败。

    出现场景：上游字段缺失/类型不符、时间格式不可解析、media 类型不在
    Canonical 枚举内、tweet_id 与 payload 不一致、富化形状不符合 ``$defs`` 等。
    这类错误表示「这条数据无法表达为 CanonicalBookmark」，而不是「Raw 边界非法」。
    """


__all__ = [
    "NormalizationError",
    "RawDataContractError",
    "CanonicalValidationError",
]
