"""
Unit tests for Metadata extraction and Thumbnail generation.
"""

from pathlib import Path
from PIL import Image
from backend.core.metadata import extract_metadata, generate_thumbnail, parse_exif_date


def test_parse_exif_date():
    """Verifies that non-standard EXIF date formats convert to standard ISO-8601."""
    raw = "2024:05:12 14:30:25"
    iso = parse_exif_date(raw)
    assert iso == "2024-05-12T14:30:25"

    assert parse_exif_date(None) is None
    assert parse_exif_date("invalid-date") is None


def test_extract_metadata(sample_images_dir: Path):
    """Verifies image metadata, dimensions, and date extraction."""
    img_path = sample_images_dir / "product_headphones.jpg"
    meta = extract_metadata(img_path)

    assert meta["file_name"] == "product_headphones.jpg"
    assert meta["width"] == 500
    assert meta["height"] == 500
    assert meta["file_format"] in ("JPEG", "JPG")
    assert meta["file_size"] > 0
    assert "2024-01-10" in meta["date_taken"]


def test_generate_thumbnail(sample_images_dir: Path, tmp_path: Path):
    """Verifies WebP thumbnail creation with dimension constraints."""
    img_path = sample_images_dir / "screenshot_browser.png"
    dummy_hash = "abcdef0123456789"

    thumb_rel_path = generate_thumbnail(
        file_path=img_path,
        sha256_hash=dummy_hash,
        output_dir=tmp_path,
        max_size=(300, 300)
    )

    assert thumb_rel_path is not None
    thumb_file = tmp_path / f"{dummy_hash}.webp"
    assert thumb_file.exists()

    # Verify thumbnail constraints
    with Image.open(thumb_file) as thumb:
        assert thumb.format == "WEBP"
        assert thumb.width <= 300
        assert thumb.height <= 300


def test_metadata_and_thumbnails_extended_formats(tmp_path: Path):
    """
    Verifies metadata extraction and WebP thumbnail generation for
    BMP, GIF, TIFF, and TIF formats.
    """
    test_cases = [
        ("test.bmp", (320, 240), "RGB", "BMP"),
        ("test.gif", (160, 120), "P", "GIF"),
        ("test.tiff", (400, 300), "RGB", "TIFF"),
        ("test.tif", (250, 250), "RGB", "TIFF"),
    ]

    for fname, (w, h), mode, expected_fmt in test_cases:
        fpath = tmp_path / fname
        img = Image.new(mode, (w, h), color=0 if mode == "P" else (100, 150, 200))
        img.save(fpath)

        meta = extract_metadata(fpath)
        assert meta["file_name"] == fname
        assert meta["width"] == w
        assert meta["height"] == h
        assert meta["file_format"] == expected_fmt
        assert meta["file_size"] > 0

        thumb_hash = f"hash_{fname}"
        thumb_path = generate_thumbnail(fpath, thumb_hash, output_dir=tmp_path)
        assert thumb_path is not None

        thumb_file = tmp_path / f"{thumb_hash}.webp"
        assert thumb_file.exists()
        with Image.open(thumb_file) as thumb:
            assert thumb.format == "WEBP"
            assert thumb.width <= 300
            assert thumb.height <= 300


