"""
Tests for Semantic Renaming, Slugification, and Windows Filesystem Safety.
"""

from pathlib import Path
import pytest

from backend.core.renamer import (
    slugify_description,
    generate_semantic_filename,
    sanitize_proposed_filename,
    resolve_filename_collision,
    WINDOWS_RESERVED_NAMES,
)


def test_slugify_description_basic():
    """Converts natural language description to lowercase kebab-case slug."""
    desc = "Golden Retriever Running On Grass"
    slug = slugify_description(desc)
    assert slug == "golden-retriever-running-on-grass"


def test_slugify_description_strips_punctuation_and_symbols():
    """Strips punctuation, special characters, and extra whitespace."""
    desc = "Receipt #4029! (Target Store, $45.99) -- 2026/03/15..."
    slug = slugify_description(desc)
    assert slug == "receipt-4029-target-store-45-99-2026-03-15"
    assert "!" not in slug
    assert "$" not in slug
    assert "(" not in slug
    assert "/" not in slug
    assert "--" not in slug


def test_slugify_description_enforces_safe_length_limit():
    """Limits slug length to between 30 and 60 chars without cutting words awkwardly."""
    long_desc = "a very long scenic photograph of majestic snow covered mountain peaks during a vibrant orange and purple sunset over a tranquil crystal clear alpine lake"
    slug = slugify_description(long_desc, max_chars=50)
    assert len(slug) <= 50
    # Must not end with a hyphen
    assert not slug.endswith("-")
    assert not slug.startswith("-")


def test_windows_reserved_names_protection():
    """Ensures Windows reserved device names are prefixed with 'img-' to prevent OS errors."""
    for name in ["CON", "PRN", "AUX", "NUL", "COM1", "COM9", "LPT1", "LPT9"]:
        slug = slugify_description(name)
        assert slug.lower() not in WINDOWS_RESERVED_NAMES
        assert slug.startswith("img-")

    # Lowercase check
    assert slugify_description("con") == "img-con"
    assert slugify_description("aux") == "img-aux"
    assert slugify_description("nul") == "img-nul"


def test_generate_semantic_filename_preserves_extension():
    """Preserves original file extension in lowercase."""
    desc = "mountain lake at sunset"
    orig_name = "IMG_9941.JPEG"
    new_name = generate_semantic_filename(desc, orig_name)
    assert new_name == "mountain-lake-at-sunset.jpeg"

    orig_png = "Screenshot_2026-01-01.PNG"
    new_png = generate_semantic_filename("terminal build error log", orig_png)
    assert new_png == "terminal-build-error-log.png"


def test_generate_semantic_filename_fallback_category():
    """Falls back to category and subcategory if visual description is empty or blank."""
    name1 = generate_semantic_filename("", "IMG_001.jpg", category_name="Animals", subcategory="Dogs")
    assert name1 == "animals-dogs.jpg"

    name2 = generate_semantic_filename("   ", "photo.webp", category_name="Nature", subcategory="Mountains")
    assert name2 == "nature-mountains.webp"

    name3 = generate_semantic_filename("", "RAW_123.jpg")
    assert name3.startswith("image-raw-123.jpg") or name3.startswith("image-")


def test_sanitize_user_proposed_filename():
    """Sanitizes user manual edits to ensure valid Windows filename and preserved extension."""
    clean = sanitize_proposed_filename("My Custom File Name! (v2).jpg", original_filename="orig.jpg")
    assert clean == "my-custom-file-name-v2.jpg"

    # Handles reserved name entered by user
    clean_con = sanitize_proposed_filename("con.png", original_filename="orig.png")
    assert clean_con == "img-con.png"

    # Preserves original extension if user removed extension
    clean_no_ext = sanitize_proposed_filename("scanned-invoice", original_filename="doc.pdf")
    assert clean_no_ext == "scanned-invoice.pdf"


def test_resolve_filename_collision_with_numeric_suffix(tmp_path: Path):
    """Appends -2, -3 suffixes when a file with the same name already exists."""
    target_dir = tmp_path / "Animals" / "Dogs"
    target_dir.mkdir(parents=True)

    file1 = target_dir / "golden-retriever-on-grass.jpg"
    file1.write_text("dummy 1")

    # First collision should resolve to -2
    candidate1 = resolve_filename_collision("golden-retriever-on-grass", ".jpg", target_dir)
    assert candidate1 == "golden-retriever-on-grass-2.jpg"

    # Simulate -2 existing
    file2 = target_dir / "golden-retriever-on-grass-2.jpg"
    file2.write_text("dummy 2")

    # Next collision should resolve to -3
    candidate2 = resolve_filename_collision("golden-retriever-on-grass", ".jpg", target_dir)
    assert candidate2 == "golden-retriever-on-grass-3.jpg"


def test_resolve_filename_collision_with_reserved_set():
    """Respects in-memory assigned filename set for batch dry-runs."""
    assigned_in_batch = {"sunset-over-ocean.jpg", "sunset-over-ocean-2.jpg"}
    target_dir = Path("C:/dummy_dest/Nature")

    candidate = resolve_filename_collision(
        "sunset-over-ocean",
        ".jpg",
        target_dir,
        allocated_names=assigned_in_batch
    )
    assert candidate == "sunset-over-ocean-3.jpg"
