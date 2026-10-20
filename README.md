# Smart Image Organizer & Gallery

A local-first, privacy-respecting Windows desktop application designed to organize 1,000–10,000 mixed images using Hybrid AI (Local CPU vision + optional Gemini API), deduplicate via cryptographic hashing, and safely copy approved files into categorized folders.

## Current Status: Milestone 1 Completed (Image Scanner & Metadata Catalog)

### Verified Features in Milestone 1:
- **Recursive Read-Only Scanner:** Scans folders and nested subfolders while strictly guaranteeing original source files are never altered, moved, or deleted.
- **Streaming SHA-256 Hasher:** Computes cryptographic byte checksums in 64 KB chunks to guarantee minimal RAM usage on large image files.
- **Metadata & EXIF Extractor:** Safely extracts dimensions, formats, and auto-rotates smartphone photos using EXIF orientation tags.
- **WebP Thumbnail Cache:** Generates lightweight 300x300 WebP thumbnails indexed by file hash.
- **SQLite Database with WAL Mode:** Concurrent read/write catalog with full indexing and idempotent upsert queries.
- **Exact Duplicate Detection:** Groups identical image files across different folders via SHA-256 hash matching.
- **Automated Test Suite:** 10/10 automated tests passing with pytest.

> Note: Perceptual similarity detection (dHash/pHash) is planned for Milestone 5, Web Gallery UI for Milestone 2, and AI classification for Milestones 3 & 4.

---

## Quickstart Guide

### 1. Activate the Virtual Environment
Open PowerShell in this directory:
```powershell
.\venv\Scripts\Activate.ps1
```

### 2. Generate Synthetic Test Images
Before scanning personal folders, test safely using synthetic images:
```powershell
python scripts/generate_test_data.py
```
This creates a sandbox directory at `test_sample_images/` with 11 mixed images, nested subfolders, and intentional duplicate pairs.

### 3. Run the Scanner CLI
```powershell
python scripts/scan.py
```
Or scan any custom folder:
```powershell
python scripts/scan.py "C:\Path\To\Your\Images"
```

### 4. Run Automated Tests
```powershell
pytest -v
```

---

## Project Structure
```text
.
├── backend/
│   ├── core/
│   │   ├── hasher.py          # Streaming SHA-256 cryptographic hasher
│   │   ├── metadata.py        # EXIF parser & WebP thumbnail generator
│   │   └── scanner.py         # Recursive read-only directory scanner
│   └── db/
│       ├── schema.py          # SQLite DDL tables, indices, and constraints
│       ├── session.py         # SQLite connection manager with WAL mode
│       └── repository.py      # CRUD queries and duplicate grouping
├── config/
│   ├── categories.yaml        # Configurable category taxonomy and anchor prompts
│   └── settings.py            # Pydantic configuration and paths
├── data/                      # Local catalog database & cached thumbnails
├── scripts/
│   ├── generate_test_data.py  # Synthetic test image generator
│   └── scan.py                # Command-line scanner runner
└── tests/                     # Pytest automated test suite
```

