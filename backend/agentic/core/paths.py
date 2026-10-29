"""Stable resource roots, independent of the process working directory."""
from pathlib import Path

AGENTIC_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = AGENTIC_ROOT.parent
