"""
Ensure the repo root is first on sys.path so root-level modules
(utils.py, storage.py, fetcher.py …) shadow any same-named files
inside subdirectories (e.g. spike/utils.py).
"""
import sys
from pathlib import Path

_ROOT = str(Path(__file__).parent.resolve())
if sys.path and sys.path[0] != _ROOT:
    sys.path.insert(0, _ROOT)
# Remove spike/ from path if it sneaked in
sys.path = [p for p in sys.path if not p.endswith("spike")]

# Prevent pytest from collecting non-test files in tools/ or spike/
collect_ignore_glob = ["tools/*.py", "spike/*.py"]
