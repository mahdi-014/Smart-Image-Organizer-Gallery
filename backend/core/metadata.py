"""
Image Metadata Extraction & Thumbnail Generation Module.

Concepts Explained for Beginners:
1. EXIF (Exchangeable Image File Format):
   - Digital cameras and smartphones store hidden tags inside images (e.g., date taken, camera model, orientation).
   - EXIF dates often look like '2023:10:15 14:32:00'. We normalize this into standard ISO-8601 '2023-10-15T14:32:00'.
2. EXIF Orientation & Auto-Rotation:
   - When a smartphone takes a vertical photo, the raw sensor bytes might still be horizontal,
     with an EXIF tag saying 'rotate 90 degrees'.
   - Pillow's ImageOps.exif_transpose() automatically applies this rotation so thumbnails are never upside-down or sideways.
3. WebP Thumbnail Optimization:
   - Modern WebP format offers 30% smaller file sizes than JPEG with better clarity.
   - We generate thumbnails keyed by the file's SHA-256 hash. This means identical images share the same cached thumbnail!
4. Multi-frame & Multi-page Formats (Animated GIF & Multi-page TIFF):
   - By default, Pillow decodes the first frame (frame 0) or first page.
   - The initial cataloging indexes the primary static frame for dimensions and thumbnail generation.
"""

from pathlib import Path
from datetime import datetime
from typing import Dict, Any, Optional, Tuple, Union
from PIL import Image, ImageOps, ExifTags

from config.settings import (
    settings,
    THUMBNAIL_MAX_SIZE,
    THUMBNAIL_FORMAT,
    THUMBNAIL_QUALITY
)


def parse_exif_date(date_str: Optional[str]) -> Optional[str]:
    """
    Parses standard camera EXIF date strings (e.g. '2023:08:15 14:30:00')
    into a clean ISO-8601 string ('2023-08-15T14:30:00').
    """
    if not date_str or not isinstance(date_str, str):
        return None

    cleaned = date_str.strip()
    # Common EXIF date patterns
    patterns = [
        "%Y:%m:%d %H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
        "%Y/%m/%d %H:%M:%S",
        "%Y:%m:%d %H:%M:%SZ",
        "%Y-%m-%dT%H:%M:%S",
    ]
    for pattern in patterns:
        try:
            dt = datetime.strptime(cleaned, pattern)
            return dt.isoformat()
        except ValueError:
            continue

    return None


def extract_metadata(file_path: Union[str, Path]) -> Dict[str, Any]:
    """
    Reads image dimensions, format, file stats, and EXIF tags.
    Does NOT modify the file. Opens strictly in read mode.
    """
    path = Path(file_path)
    stat = path.stat()

    file_size = stat.st_size
    date_modified = datetime.fromtimestamp(stat.st_mtime).isoformat()
    date_taken = None
    width = 0
    height = 0
    file_format = path.suffix.lstrip(".").upper()
    exif_tags: Dict[str, Any] = {}

    try:
        with Image.open(path) as img:
            width, height = img.size
            if img.format:
                file_format = img.format.upper()

            # Extract EXIF if available
            raw_exif = img.getexif()
            if raw_exif:
                for tag_id, value in raw_exif.items():
                    tag_name = ExifTags.TAGS.get(tag_id, str(tag_id))
                    # Avoid serializing massive binary tags
                    if isinstance(value, (str, int, float)):
                        exif_tags[tag_name] = value

                # Check for DateTimeOriginal in standard EXIF or Exif sub-IFD
                dt_raw = exif_tags.get("DateTimeOriginal") or exif_tags.get("DateTime")
                if not dt_raw:
                    try:
                        exif_ifd = raw_exif.get_ifd(ExifTags.IFD.Exif)
                        dt_raw = exif_ifd.get(ExifTags.Base.DateTimeOriginal) or exif_ifd.get(ExifTags.Base.DateTimeDigitized)
                    except Exception:
                        pass

                date_taken = parse_exif_date(str(dt_raw)) if dt_raw else None

    except Exception:
        # Fallback if image has corrupt headers or cannot be decoded
        pass

    # If no EXIF date taken exists, fallback to file modification timestamp
    if not date_taken:
        date_taken = date_modified

    return {
        "file_path": str(path.resolve()),
        "file_name": path.name,
        "file_size": file_size,
        "width": width,
        "height": height,
        "file_format": file_format,
        "date_taken": date_taken,
        "date_modified": date_modified,
        "exif_summary": exif_tags
    }


def generate_thumbnail(
    file_path: Union[str, Path],
    sha256_hash: str,
    output_dir: Optional[Path] = None,
    max_size: Tuple[int, int] = THUMBNAIL_MAX_SIZE
) -> Optional[str]:
    """
    Generates a lightweight WebP thumbnail for the web gallery.
    
    1. Loads the source image safely.
    2. Applies ImageOps.exif_transpose() to preserve correct rotation.
    3. Resizes down to max_size while maintaining aspect ratio.
    4. Saves as .cache/thumbnails/{sha256_hash}.webp.
    5. Returns relative path to the thumbnail file.
    """
    out_dir = output_dir or settings.thumbnails_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    dest_file = out_dir / f"{sha256_hash}.webp"
    
    # Helper to format return path cleanly (relative if inside project, absolute otherwise)
    def _format_path(p: Path) -> str:
        try:
            return str(p.relative_to(settings.project_root)).replace("\\", "/")
        except ValueError:
            return str(p.resolve()).replace("\\", "/")

    # If thumbnail already exists (e.g. for duplicates or re-scans), skip re-generating!
    if dest_file.exists():
        return _format_path(dest_file)

    try:
        with Image.open(file_path) as img:
            # Auto-rotate based on EXIF orientation tag
            transposed = ImageOps.exif_transpose(img)

            # Convert color mode for WebP compatibility
            if transposed.mode in ("RGBA", "LA"):
                thumb_img = transposed.copy()
            elif transposed.mode != "RGB":
                thumb_img = transposed.convert("RGB")
            else:
                thumb_img = transposed.copy()

            thumb_img.thumbnail(max_size, Image.Resampling.LANCZOS)
            thumb_img.save(
                dest_file,
                format=THUMBNAIL_FORMAT,
                quality=THUMBNAIL_QUALITY,
                method=6  # Highest compression efficiency
            )

        return _format_path(dest_file)

    except Exception:
        return None
