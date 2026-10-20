"""
Synthetic Test Image Generator for Safe Verification.

Creates a sandbox folder 'test_sample_images/' with:
- Mixed formats (.jpg, .png, .webp)
- Nested subdirectories
- Real EXIF timestamps (using Pillow's built-in EXIF builder)
- Known exact byte duplicates (to test deduplication)
- Non-image files (.txt) to verify file filtering
"""

import sys
from pathlib import Path
from PIL import Image, ImageDraw, ExifTags

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


def create_synthetic_image(
    path: Path,
    size=(400, 300),
    bg_color=(200, 200, 200),
    shape_color=(50, 100, 200),
    label: str = "",
    date_taken_str: str = None
) -> None:
    """Creates a simple PIL image with geometric shapes and optional EXIF."""
    path.parent.mkdir(parents=True, exist_ok=True)
    img = Image.new("RGB", size, color=bg_color)
    draw = ImageDraw.Draw(img)

    # Draw simple geometric patterns to give distinctive visual structure for dHash
    draw.rectangle([20, 20, size[0] - 20, size[1] - 20], outline=shape_color, width=4)
    draw.ellipse([size[0]//4, size[1]//4, size[0]*3//4, size[1]*3//4], fill=shape_color)

    # Add label text indicator
    draw.text((30, 30), label, fill=(255, 255, 255) if sum(bg_color) < 400 else (0, 0, 0))

    # Add EXIF DateTimeOriginal if JPEG and requested
    fmt = path.suffix.lower()
    if fmt in (".jpg", ".jpeg") and date_taken_str:
        exif = img.getexif()
        # Tag 0x9003 is DateTimeOriginal, 0x0132 is DateTime
        exif[0x0132] = date_taken_str
        exif_sub = exif.get_ifd(ExifTags.IFD.Exif)
        exif_sub[ExifTags.Base.DateTimeOriginal] = date_taken_str
        img.save(path, exif=exif, quality=90)
    elif fmt == ".webp":
        img.save(path, format="WEBP", quality=90)
    else:
        img.save(path)


def generate_all_test_data(target_dir: Path) -> Path:
    """Builds the complete synthetic test suite on disk."""
    if target_dir.exists():
        import shutil
        shutil.rmtree(target_dir)

    target_dir.mkdir(parents=True, exist_ok=True)

    # 1. Product Mock
    prod_path = target_dir / "product_headphones.jpg"
    create_synthetic_image(prod_path, (500, 500), (245, 245, 245), (40, 40, 40), "Product: Headphones", "2024:01:10 09:15:00")

    # 2. Portrait Mock
    create_synthetic_image(target_dir / "portrait_person.jpg", (400, 600), (230, 200, 180), (120, 60, 40), "Portrait", "2024:02:14 18:30:00")

    # 3. Nature Landscape Mock
    create_synthetic_image(target_dir / "nature_forest.png", (800, 500), (34, 139, 34), (135, 206, 235), "Nature Forest")

    # 4. Screenshot / UI Mock
    create_synthetic_image(target_dir / "screenshot_browser.png", (1024, 768), (30, 30, 30), (0, 150, 255), "UI Screenshot")

    # 5. Document Mock
    doc_path = target_dir / "document_receipt.jpg"
    create_synthetic_image(doc_path, (400, 700), (250, 250, 240), (80, 80, 80), "Receipt $45.20", "2024:03:01 12:00:00")

    # 6. Food Mock
    create_synthetic_image(target_dir / "food_pizza.jpg", (500, 400), (255, 140, 0), (220, 20, 60), "Hot Pizza", "2024:04:18 20:45:00")

    # 7. AI Artwork Mock (WEBP)
    create_synthetic_image(target_dir / "ai_abstract_art.webp", (600, 600), (75, 0, 130), (255, 0, 128), "AI Art Concept")

    # 8. Nested Directory: subfolder_one/
    sub1 = target_dir / "subfolder_one"
    create_synthetic_image(sub1 / "social_graphic.jpg", (600, 600), (255, 105, 180), (255, 255, 255), "Social Banner", "2024:05:01 14:10:00")
    create_synthetic_image(sub1 / "places_eiffel_tower.png", (450, 700), (100, 149, 237), (180, 180, 180), "Eiffel Tower")

    # 9. Nested Directory: subfolder_two/ with EXACT DUPLICATES
    sub2 = target_dir / "subfolder_two"
    sub2.mkdir(parents=True, exist_ok=True)

    # Exact duplicate 1: Same exact bytes as headphones, different filename & folder
    dup1_path = sub2 / "headphones_backup_copy.jpg"
    dup1_path.write_bytes(prod_path.read_bytes())

    # Exact duplicate 2: Same exact bytes as receipt
    dup2_path = sub2 / "receipt_scanned_copy.jpg"
    dup2_path.write_bytes(doc_path.read_bytes())

    # 10. Non-image file to test file filtering
    (target_dir / "notes_todo.txt").write_text("This text file should be ignored by the scanner.", encoding="utf-8")
    (sub1 / "ignore_script.py").write_text("print('Ignore this too')", encoding="utf-8")

    return target_dir


if __name__ == "__main__":
    out = PROJECT_ROOT / "test_sample_images"
    generate_all_test_data(out)
    print(f"Generated synthetic test image collection in: {out}")

