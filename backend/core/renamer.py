"""
Semantic Renaming and Windows-Safe Slug Generation Engine.

Converts AI-generated natural-language visual descriptions into clean,
Windows-compliant, hyphen-separated kebab-case filenames while preserving
original file extensions and preventing collisions.
"""

import re
from pathlib import Path
from typing import Optional, Set

# Windows device reserved names (case-insensitive)
WINDOWS_RESERVED_NAMES: Set[str] = {
    "con",
    "prn",
    "aux",
    "nul",
    "com1",
    "com2",
    "com3",
    "com4",
    "com5",
    "com6",
    "com7",
    "com8",
    "com9",
    "lpt1",
    "lpt2",
    "lpt3",
    "lpt4",
    "lpt5",
    "lpt6",
    "lpt7",
    "lpt8",
    "lpt9",
}


def slugify_description(description: str, max_chars: int = 50) -> str:
    """
    Transforms natural-language visual descriptions into safe, lowercase,
    hyphen-separated slugs (kebab-case).

    Rules:
    - English lowercase characters and numbers (a-z, 0-9)
    - Hyphen-separated words without repeating hyphens
    - Length limited to `max_chars` (default 50 chars, safe limit 30-60)
    - Windows reserved names protected (prefixed with 'img-')
    """
    if not description:
        return ""

    # Replace non-alphanumeric characters with hyphens
    cleaned = re.sub(r"[^a-zA-Z0-9]+", "-", description.strip())
    # Lowercase
    lowered = cleaned.lower()
    # Collapse multiple consecutive hyphens
    collapsed = re.sub(r"-+", "-", lowered).strip("-")

    if not collapsed:
        return ""

    # Truncate to safe length limit, preferring word boundary
    if len(collapsed) > max_chars:
        truncated = collapsed[:max_chars]
        if "-" in truncated:
            # Cut at last hyphen to avoid partial trailing words
            last_hyphen = truncated.rfind("-")
            if last_hyphen >= 20:  # Only trim if we keep reasonable length
                truncated = truncated[:last_hyphen]
        collapsed = truncated.strip("-")

    # Guard against Windows reserved device names
    first_token = collapsed.split("-")[0]
    if collapsed in WINDOWS_RESERVED_NAMES or first_token in WINDOWS_RESERVED_NAMES:
        collapsed = f"img-{collapsed}"

    return collapsed


def generate_semantic_filename(
    description: str,
    original_filename: str,
    category_name: str = "",
    subcategory: str = "",
    max_chars: int = 50,
) -> str:
    """
    Generates a descriptive, semantic filename from visual content description.
    Preserves original file extension and handles fallback taxonomy gracefully.
    """
    orig_path = Path(original_filename)
    ext = orig_path.suffix.lower() if orig_path.suffix else ".jpg"

    slug = slugify_description(description, max_chars=max_chars)

    # Fallback to category / subcategory if description was blank
    if not slug:
        parts = [
            p.strip()
            for p in [category_name, subcategory]
            if p and p.strip().lower() not in ("general", "other", "uncategorized", "needs review")
        ]
        if parts:
            slug = slugify_description("-".join(parts), max_chars=max_chars)

    # Ultimate fallback to original stem or generic prefix
    if not slug:
        stem_slug = slugify_description(orig_path.stem, max_chars=30)
        slug = f"image-{stem_slug}" if stem_slug else "image-photo"

    return f"{slug}{ext}"


def sanitize_proposed_filename(proposed: str, original_filename: str) -> str:
    """
    Validates and normalizes user-provided custom filename overrides.
    Ensures safe Windows filename characters, length bounds, and correct extension.
    """
    orig_ext = Path(original_filename).suffix.lower() if Path(original_filename).suffix else ".jpg"

    proposed_path = Path(proposed.strip())
    # If the user included an extension, check it; otherwise retain original extension
    if proposed_path.suffix:
        user_ext = proposed_path.suffix.lower()
        stem = proposed_path.stem
        final_ext = user_ext
    else:
        stem = proposed.strip()
        final_ext = orig_ext

    slug = slugify_description(stem, max_chars=60)
    if not slug:
        slug = slugify_description(Path(original_filename).stem, max_chars=30) or "image-photo"

    return f"{slug}{final_ext}"


def resolve_filename_collision(
    stem: str,
    ext: str,
    target_dir: Path,
    allocated_names: Optional[Set[str]] = None,
) -> str:
    """
    Resolves naming collisions in target destination directory.
    If 'slug.ext' exists, tests 'slug-2.ext', 'slug-3.ext', etc.
    Checks both filesystem existence and in-memory allocated batch set.
    """
    allocated = allocated_names or set()
    candidate = f"{stem}{ext}"

    if candidate not in allocated and not (target_dir.exists() and (target_dir / candidate).exists()):
        return candidate

    counter = 2
    while True:
        candidate = f"{stem}-{counter}{ext}"
        if candidate not in allocated and not (target_dir.exists() and (target_dir / candidate).exists()):
            return candidate
        counter += 1
