"""Use restaurant packages from this checkout during offline regression tests."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for name in ("tabelog", "tablecheck", "pocket-concierge"):
    sys.path.insert(0, str(ROOT / "skills" / name / "scripts"))
