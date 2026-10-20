# Smart Image Organizer & Gallery

A local-first, privacy-respecting Windows desktop application designed to organize 1,000–10,000 mixed images using Hybrid AI (Local CPU vision + optional Gemini API), deduplicate via cryptographic hashing, and safely copy approved files into categorized folders.

## Current Status: Milestone 1 Completed (Image Scanner & Metadata Catalog)

### Verified Features in Milestone 1:
- **Recursive Read-Only Scanner:** Scans folders and nested subfolders while strictly guaranteeing original source files are never altered, moved, or deleted. Supports JPG, JPEG, PNG, WEBP, BMP, GIF, TIF, and TIFF formats (case-insensitive) with top-down traversal that prunes ignored directories (`.git`, `venv`, `node_modules`, `__pycache__`), captures filesystem traversal errors, and rejects corrupt or unreadable files without halting accessible processing.
- **Streaming SHA-256 Hasher:** Computes cryptographic byte checksums in 64 KB chunks to guarantee minimal RAM usage on large image files.
- **Metadata & EXIF Extractor:** Safely extracts dimensions, formats, and auto-rotates smartphone photos using EXIF orientation tags. For animated GIFs and multi-page TIFFs, the primary (first) frame/page is indexed.
- **WebP Thumbnail Cache:** Generates lightweight 300x300 WebP thumbnails indexed by file hash.
- **SQLite Database with WAL Mode:** Concurrent read/write catalog with full indexing and idempotent upsert queries.
- **Exact Duplicate Detection:** Groups identical image files across different folders via SHA-256 hash matching.
- **Automated Test Suite:** Comprehensive pytest suite verifying all scanner, hasher, metadata, and database operations.

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

### 5. Start the Local API Server
Start the local FastAPI development server:
```powershell
.\venv\Scripts\python.exe -m uvicorn backend.api.app:app --host 127.0.0.1 --port 8000 --reload
```
Once the server is running, access:
- **Health Check Endpoint:** [http://127.0.0.1:8000/api/health](http://127.0.0.1:8000/api/health)
- **Interactive API Documentation (Swagger UI):** [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)

---

## Project Structure
```text
.
├── backend/
│   ├── api/
│   │   └── app.py             # FastAPI application and route endpoints
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

