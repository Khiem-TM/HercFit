"""HercFit Agentic Multi-Agent Package."""

import sys
from pathlib import Path

_AGENTIC_ROOT = str(Path(__file__).resolve().parent)
if _AGENTIC_ROOT not in sys.path:
    sys.path.insert(0, _AGENTIC_ROOT)

__all__ = ["_AGENTIC_ROOT"]
