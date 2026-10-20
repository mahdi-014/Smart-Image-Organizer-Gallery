"""
Unit tests for Hasher: Cryptographic SHA-256.
"""

from pathlib import Path
from backend.core.hasher import compute_sha256


def test_sha256_exact_duplicates(sample_images_dir: Path):
    """Verifies that identical files in different folders yield identical SHA-256 hashes."""
    orig = sample_images_dir / "product_headphones.jpg"
    dup = sample_images_dir / "subfolder_two" / "headphones_backup_copy.jpg"

    assert orig.exists(), "Original file must exist"
    assert dup.exists(), "Duplicate file must exist"

    hash_orig = compute_sha256(orig)
    hash_dup = compute_sha256(dup)

    assert len(hash_orig) == 64
    assert hash_orig == hash_dup


def test_sha256_different_images(sample_images_dir: Path):
    """Verifies that different images yield distinct SHA-256 hashes."""
    img1 = sample_images_dir / "product_headphones.jpg"
    img2 = sample_images_dir / "portrait_person.jpg"

    assert compute_sha256(img1) != compute_sha256(img2)


def test_sha256_hex_format(sample_images_dir: Path):
    """Verifies that the computed hash is a valid 64-character lowercase hex string."""
    img = sample_images_dir / "food_pizza.jpg"
    result = compute_sha256(img)

    assert len(result) == 64
    assert all(c in "0123456789abcdef" for c in result)
