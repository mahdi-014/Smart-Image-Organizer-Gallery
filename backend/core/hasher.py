"""
Cryptographic Hashing Module (SHA-256).

Concepts Explained for Beginners:
1. What is SHA-256?
   - A cryptographic hash function that produces a unique 64-character hexadecimal fingerprint
     from the raw bytes of a file.
   - If even a single byte, pixel, or metadata tag changes, the resulting hash changes completely.
   - Used for 100% exact duplicate detection, tracking file identity, and verifying file integrity.

2. Why Streaming Chunks (64 KB)?
   - If we read a 50 MB high-resolution image into memory all at once with `f.read()`,
     RAM usage spikes.
   - By reading in chunks of 65,536 bytes (64 KB) in binary mode (`'rb'`), our memory
     footprint remains virtually zero (<1 MB) regardless of file size.

Note on Perceptual Similarity:
   - Approximate/visual similarity detection (perceptual hashing / dHash) is deferred
     to Milestone 5 per the project roadmap.
"""

import hashlib
from pathlib import Path
from typing import Union

from config.settings import HASH_CHUNK_SIZE


def compute_sha256(file_path: Union[str, Path], chunk_size: int = HASH_CHUNK_SIZE) -> str:
    """
    Computes the SHA-256 cryptographic checksum of a file in streaming chunks.

    Parameters:
        file_path: Path to the target file.
        chunk_size: Number of bytes to read per iteration (defaults to 64 KB).

    Returns:
        64-character lowercase hexadecimal hash string.
    """
    hasher = hashlib.sha256()
    path = Path(file_path)

    with open(path, "rb") as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            hasher.update(chunk)

    return hasher.hexdigest()
