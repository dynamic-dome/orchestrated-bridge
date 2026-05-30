from __future__ import annotations

import sys
from pathlib import Path

# This demo has no database layer. Tests isolate filesystem writes via tmp_path.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC))
