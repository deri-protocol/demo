#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

WORKSPACE_ROOT = Path(__file__).resolve().parent.parent
if str(WORKSPACE_ROOT) not in sys.path:
    sys.path.insert(0, str(WORKSPACE_ROOT))

from deri_v5_basic_trading_actions.deri_v5_pro_core import main


if __name__ == "__main__":
    main()
