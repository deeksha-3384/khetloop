"""Manual check:  python -m tests.backend.try_vision tmp\\leaf.jpg tomato"""
import json
import sys
from pathlib import Path

from backend.services.gemini_vision import analyse_leaf

path = Path(sys.argv[1])
crop = sys.argv[2] if len(sys.argv) > 2 else "tomato"
print(json.dumps(analyse_leaf(path.read_bytes(), crop, None), indent=2, ensure_ascii=False))