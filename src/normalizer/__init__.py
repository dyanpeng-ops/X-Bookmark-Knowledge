"""normalizer —— ``RawCollectorData → CanonicalBookmark`` 归一化层（Phase 3）。

对外入口：

* :class:`~src.normalizer.fieldtheory.FieldTheoryNormalizer` —— Field Theory 实现；
* :func:`~src.normalizer.fieldtheory.compute_content_hash` —— ``ARCHITECTURE.md``
  §5.4 的内容哈希；
* :mod:`src.normalizer.errors` —— ``NormalizationError`` / ``CanonicalValidationError``。

边界（任务书 §24/§25）：本包不执行上游 CLI、不联网、不写 SQLite / Markdown / Git；
所有上游读取都发生在 Collector 层。
"""

from .errors import CanonicalValidationError, NormalizationError, RawDataContractError
from .fieldtheory import FieldTheoryNormalizer, compute_content_hash, is_article_link

__all__ = [
    "CanonicalValidationError",
    "FieldTheoryNormalizer",
    "NormalizationError",
    "RawDataContractError",
    "compute_content_hash",
    "is_article_link",
]
