import json
import re
from pathlib import Path

from shared.constants import ISSUES

ROOT = Path(__file__).resolve().parents[2]
GUIDANCE_FILE = ROOT / "data" / "approved_guidance.json"

BANNED_WORDS = ["outbreak", "spray", "per litre", "per liter", "mancozeb",
                "chlorothalonil", "copper", "streptomycin", "imidacloprid"]
DOSAGE = re.compile(r"\d+\s*(ml|g|kg|l)\b", re.IGNORECASE)


def load():
    with open(GUIDANCE_FILE, encoding="utf-8") as f:
        return json.load(f)


def test_all_issues_present():
    data = load()
    for issue in ISSUES:
        if issue == "unknown":
            continue
        assert issue in data, f"missing issue: {issue}"
    assert "default" in data


def test_shape_and_lengths():
    data = load()
    for name, entry in data.items():
        assert set(entry.keys()) == {"guidance", "source"}, name
        assert isinstance(entry["source"], str) and entry["source"], name
        assert set(entry["guidance"].keys()) == {"en", "hi", "kn"}, name
        for lang, lines in entry["guidance"].items():
            assert 3 <= len(lines) <= 5, f"{name}/{lang}: {len(lines)} sentences"
            assert all(isinstance(s, str) and s.strip() for s in lines), f"{name}/{lang}"


def test_no_banned_content():
    data = load()
    for name, entry in data.items():
        for lang, lines in entry["guidance"].items():
            for s in lines:
                low = s.lower()
                assert not DOSAGE.search(s), f"dosage-like text in {name}/{lang}: {s}"
                for w in BANNED_WORDS:
                    assert w not in low, f"banned word '{w}' in {name}/{lang}: {s}"


def test_agri_officer_sentence_everywhere():
    data = load()
    for name, entry in data.items():
        assert any("agri officer" in s.lower() for s in entry["guidance"]["en"]), name