"""handlers — 外链分站处理器。

（Phase 9 实现）按站点类型实现抽取策略，例如 web / github / pdf。
每个 handler 必须独立可测，且失败不得影响其他 handler。
"""
