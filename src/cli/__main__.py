"""`python -m src.cli` 的入口。

用法::

    .venv\\Scripts\\python.exe -m src.cli sync
    .venv\\Scripts\\python.exe -m src.cli status --json
    .venv\\Scripts\\python.exe -m src.cli doctor
"""

from __future__ import annotations

import sys

from .main import main

if __name__ == "__main__":
    sys.exit(main())
