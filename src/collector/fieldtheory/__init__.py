"""``src.collector.fieldtheory`` —— Field Theory Collector 实现包（Phase 3）。

对外入口：:class:`~src.collector.fieldtheory.adapter.FieldTheoryCollector`。

路径说明：任务书 §7 指定实现位置为 ``src/collector/fieldtheory/adapter.py``；
Phase 5 的 ``src/collector/fieldtheory_adapter.py`` 按用户决策**保留不动**，
新 Collector 组合复用它的读取逻辑，不重写第二套接口（任务书 §22）。
"""

from .adapter import COLLECTOR_NAME, FieldTheoryCollector

__all__ = ["COLLECTOR_NAME", "FieldTheoryCollector"]
