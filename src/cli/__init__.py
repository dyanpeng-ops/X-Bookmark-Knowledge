"""cli — 入口层（Phase 6 已实现 sync / status / doctor）。

提供 `python -m src.cli` 的命令行入口：参数解析、流程编排、统计报告。
业务算法不在本层（采集在 `src/collector/`、入库在 `src/ingest/`）。
"""

from .main import (
    EXIT_CONFIG,
    EXIT_FAILURE,
    EXIT_OK,
    EXIT_UPSTREAM,
    build_parser,
    main,
)

__all__ = [
    "EXIT_OK",
    "EXIT_FAILURE",
    "EXIT_CONFIG",
    "EXIT_UPSTREAM",
    "build_parser",
    "main",
]

