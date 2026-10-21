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


def test_extract_metadata_invalid_image_raises(tmp_path: Path):
    """
    Verifies that extract_metadata raises an exception for unreadable or corrupt
    image files rather than silently returning 0x0 placeholder dimensions.
    """
    import pytest

    corrupt_file = tmp_path / "corrupt.jpg"
    corrupt_file.write_bytes(b"corrupt header and payload content that is not an image")

    with pytest.raises(Exception):
        extract_metadata(corrupt_file)


def test_extract_metadata_exif_resilience(tmp_path: Path):
    """
    Verifies that images with missing or empty EXIF metadata succeed
    and extract valid dimensions without raising errors.
    """
    img_path = tmp_path / "plain_photo.png"
    # Create plain PNG with no EXIF
    Image.new("RGB", (250, 180), "blue").save(img_path)

    meta = extract_metadata(img_path)
    assert meta["width"] == 250
    assert meta["height"] == 180
    assert meta["file_format"] == "PNG"
    assert meta["date_taken"] is not None


def test_generate_thumbnail_palette_png_preserves_transparency(tmp_path: Path):
    """
    Verifies that palette-mode (P) PNG images with transparency metadata
    retain their alpha transparency in the generated WebP thumbnail,
    preventing transparent areas from turning into opaque black boxes.
    """
    fpath = tmp_path / "palette_transparent.png"
    # Create image with transparent background and opaque red foreground
    img = Image.new("RGBA", (10, 10), (0, 0, 0, 0))
    for x in range(3, 7):
        for y in range(3, 7):
            img.putpixel((x, y), (255, 0, 0, 255))

    # Convert to palette mode with adaptive palette preserving transparency
    p_img = img.convert("P", palette=Image.Palette.ADAPTIVE)
    p_img.save(fpath, format="PNG")

    # Verify source file is indeed palette mode with transparency
    with Image.open(fpath) as src:
        assert src.mode == "P"
        assert "transparency" in src.info

    thumb_rel = generate_thumbnail(fpath, "hash_pal_png", output_dir=tmp_path)
    assert thumb_rel is not None

    thumb_file = tmp_path / "hash_pal_png.webp"
    assert thumb_file.exists()

    with Image.open(thumb_file) as thumb:
        # Must be RGBA to preserve alpha channel
        assert thumb.mode == "RGBA"
        # Background pixel must remain transparent (alpha == 0)
        bg_pixel = thumb.getpixel((0, 0))
        assert bg_pixel[3] == 0, f"Expected transparent alpha 0, got pixel: {bg_pixel}"
        # Foreground pixel must remain opaque (alpha == 255)
        fg_pixel = thumb.getpixel((5, 5))
        assert fg_pixel[3] == 255, f"Expected opaque alpha 255, got pixel: {fg_pixel}"


def test_generate_thumbnail_transparent_gif_preserves_transparency(tmp_path: Path):
    """
    Verifies that transparent GIF images (palette mode with transparency index)
    retain their alpha transparency in the generated WebP thumbnail.
    """
    fpath = tmp_path / "transparent_sample.gif"
    img = Image.new("RGBA", (10, 10), (0, 0, 0, 0))
    for x in range(3, 7):
        for y in range(3, 7):
            img.putpixel((x, y), (0, 128, 255, 255))

    img.save(fpath, format="GIF", transparency=0)

    # Verify source is palette GIF with transparency index
    with Image.open(fpath) as src:
        assert src.mode == "P"
        assert "transparency" in src.info

    thumb_rel = generate_thumbnail(fpath, "hash_trans_gif", output_dir=tmp_path)
    assert thumb_rel is not None

    thumb_file = tmp_path / "hash_trans_gif.webp"
    assert thumb_file.exists()

    with Image.open(thumb_file) as thumb:
        assert thumb.mode == "RGBA"
        bg_pixel = thumb.getpixel((0, 0))
        assert bg_pixel[3] == 0, f"Expected transparent alpha 0, got pixel: {bg_pixel}"
        fg_pixel = thumb.getpixel((5, 5))
        assert fg_pixel[3] == 255, f"Expected opaque alpha 255, got pixel: {fg_pixel}"


def test_generate_thumbnail_opaque_palette_uses_rgb(tmp_path: Path):
    """
    Verifies that opaque palette images (no transparency metadata) are converted
    to RGB WebP thumbnails, avoiding unnecessary alpha channel storage.
    """
    fpath = tmp_path / "opaque_palette.png"
    img = Image.new("RGB", (10, 10), (200, 100, 50))
    p_img = img.convert("P")
    p_img.save(fpath, format="PNG")

    with Image.open(fpath) as src:
        assert src.mode == "P"
        assert "transparency" not in src.info

    thumb_rel = generate_thumbnail(fpath, "hash_opaque_pal", output_dir=tmp_path)
    assert thumb_rel is not None

    thumb_file = tmp_path / "hash_opaque_pal.webp"
    assert thumb_file.exists()

    with Image.open(thumb_file) as thumb:
        assert thumb.mode == "RGB"



