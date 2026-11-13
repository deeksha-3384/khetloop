import csv
from pathlib import Path

import pytest
from PIL import Image, ImageFilter, ImageStat

from shared.constants import IMAGE_QUALITIES

ROOT = Path(__file__).resolve().parents[2]
IMG_DIR = ROOT / "data" / "test_images"
LABELS = IMG_DIR / "LABELS.csv"
COLUMNS = ["filename", "category", "crop", "expected_quality", "dataset_label",
           "expected_behaviour", "derived_from", "source", "source_file", "notes", "observed"]


def rows():
    with open(LABELS, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def sharpness(path):
    edges = Image.open(path).convert("L").filter(ImageFilter.FIND_EDGES)
    return ImageStat.Stat(edges).var[0]


def test_contract_file_names_exist():
    for name in ("clear_tomato_01.jpg", "blurry_tomato_01.jpg", "ambiguous_tomato_01.jpg", "LABELS.csv"):
        assert (IMG_DIR / name).is_file(), f"missing {name}"


def test_images_are_valid_small_jpegs():
    jpgs = sorted(IMG_DIR.glob("*.jpg"))
    assert len(jpgs) >= 3
    for p in jpgs:
        with Image.open(p) as img:
            assert img.format == "JPEG", p.name
            assert min(img.size) >= 128, p.name
        assert p.stat().st_size < 400_000, f"{p.name} is too large for the repo"


def test_labels_cover_every_image_exactly():
    with open(LABELS, encoding="utf-8", newline="") as f:
        assert next(csv.reader(f)) == COLUMNS
    labelled = [r["filename"] for r in rows()]
    on_disk = sorted(p.name for p in IMG_DIR.glob("*.jpg"))
    assert sorted(labelled) == on_disk
    assert len(labelled) == len(set(labelled))


def test_label_values_make_sense():
    for r in rows():
        assert r["crop"] == "tomato"
        assert r["filename"].startswith(r["category"] + "_")
        assert r["category"] in {"clear", "blurry", "ambiguous"}
        assert r["expected_quality"] in IMAGE_QUALITIES
        assert r["expected_quality"] == ("poor" if r["category"] == "blurry" else "good")
        assert r["source"] and r["source_file"] and r["dataset_label"]


def test_blurry_images_really_are_blurrier():
    for r in rows():
        if r["category"] != "blurry":
            continue
        src = IMG_DIR / r["derived_from"]
        assert src.is_file(), r["derived_from"]
        assert sharpness(IMG_DIR / r["filename"]) < 0.5 * sharpness(src), r["filename"]