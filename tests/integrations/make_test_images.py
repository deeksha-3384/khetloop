"""Build data/test_images/ from original PlantVillage photos (P4). Run by hand.

Usage (repo root, venv active):
    python -m tests.integrations.make_test_images

Expects exactly one downloaded photo (any file name) in each of these folders:
    tmp/originals/early_blight/    tmp/originals/late_blight/
    tmp/originals/healthy/         tmp/originals/target_spot/
Writes resized JPEGs and LABELS.csv into data/test_images/. The original file name of
each photo is recorded in LABELS.csv (source_file) so its origin can be traced.
"""
import csv
import sys
from pathlib import Path

from PIL import Image, ImageFilter

ORIGINALS = Path("tmp") / "originals"
OUT = Path("data") / "test_images"
MAX_SIDE = 800
EXTS = {".jpg", ".jpeg", ".png"}
SOURCE = ("PlantVillage dataset (Hughes & Salathe 2015; Mohanty et al. 2016). "
          "Licence to be confirmed on the dataset page; attribution required.")

COLUMNS = ["filename", "category", "crop", "expected_quality", "dataset_label",
           "expected_behaviour", "derived_from", "source", "source_file", "notes", "observed"]

# (folder, output name, category, dataset_label, expected_behaviour, notes)
PHOTOS = [
    ("early_blight", "clear_tomato_01.jpg", "clear", "early_blight",
     "preliminary_assessment (escalate_to_expert if the transcript has a severity word)",
     "Backend reads this file to create simulated cluster reports"),
    ("late_blight", "clear_tomato_02.jpg", "clear", "late_blight",
     "escalate_to_expert if confidence is medium (late_blight is high risk)",
     "Tests the high-risk escalation rule"),
    ("healthy", "clear_tomato_03.jpg", "clear", "healthy",
     "preliminary_assessment",
     "Healthy control"),
    ("target_spot", "ambiguous_tomato_01.jpg", "ambiguous", "target_spot (not in KhetLoop issue list)",
     "abstain_request_better_image or escalate_to_expert (should not give a confident known issue)",
     "Disease outside our issue list; lesions can look like early blight"),
]
# (source output name, blurry output name)
BLURRY = [
    ("clear_tomato_01.jpg", "blurry_tomato_01.jpg"),
    ("clear_tomato_02.jpg", "blurry_tomato_02.jpg"),
]


def find_original(folder: str) -> Path:
    files = sorted(p for p in (ORIGINALS / folder).glob("*") if p.suffix.lower() in EXTS)
    if not files:
        raise FileNotFoundError(f"No image found in {ORIGINALS / folder}")
    if len(files) > 1:
        print(f"Note: {len(files)} images in {folder}; using {files[0].name}")
    return files[0]


def load(path: Path) -> Image.Image:
    img = Image.open(path).convert("RGB")
    img.thumbnail((MAX_SIDE, MAX_SIDE))  # only ever shrinks
    return img


def save_jpeg(img: Image.Image, name: str) -> None:
    img.save(OUT / name, "JPEG", quality=85, optimize=True)


def main() -> None:
    try:
        originals = {folder: find_original(folder) for folder, *_ in PHOTOS}
    except FileNotFoundError as exc:
        print(exc)
        print("Put one downloaded photo in each folder listed at the top of this script.")
        sys.exit(1)

    OUT.mkdir(parents=True, exist_ok=True)
    rows, images = [], {}
    for folder, name, category, label, behaviour, notes in PHOTOS:
        img = load(originals[folder])
        save_jpeg(img, name)
        images[name] = img
        rows.append({"filename": name, "category": category, "crop": "tomato",
                     "expected_quality": "good", "dataset_label": label,
                     "expected_behaviour": behaviour, "derived_from": "",
                     "source": SOURCE, "source_file": originals[folder].name,
                     "notes": notes, "observed": ""})

    for source_name, blurry_name in BLURRY:
        base = images[source_name]
        radius = max(8, round(max(base.size) / 25))
        save_jpeg(base.filter(ImageFilter.GaussianBlur(radius=radius)), blurry_name)
        source_row = next(r for r in rows if r["filename"] == source_name)
        rows.append({"filename": blurry_name, "category": "blurry", "crop": "tomato",
                     "expected_quality": "poor", "dataset_label": source_row["dataset_label"],
                     "expected_behaviour": "abstain_request_better_image on the first try; "
                                           "escalate_to_expert if sent again within 30 minutes",
                     "derived_from": source_name, "source": SOURCE,
                     "source_file": source_row["source_file"],
                     "notes": f"Artificially blurred copy of {source_name} (Gaussian blur, radius {radius})",
                     "observed": ""})

    with open(OUT / "LABELS.csv", "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    print(f"Wrote {len(rows)} images and LABELS.csv to {OUT}")


if __name__ == "__main__":
    main()