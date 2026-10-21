# Smart Image Organizer & Gallery

A **local-first, privacy-respecting Windows desktop application** designed to organize 1,000–10,000 mixed images using Hybrid AI (Local CPU vision + optional Gemini API), deduplicate via cryptographic hashing, and safely copy approved files into categorized folders.

> **Single Source of Truth:** This file combines the comprehensive project documentation, architectural roadmap, hard development rules, and execution guide.

---

## 1. Project Overview & Student Viva Context

- **Student Learning & University Project:** This project is designed for university examination and viva voce defense. Every architectural decision is engineered for explainability, modularity, and algorithmic rigor.
- **Problem Statement:** Large personal photo collections (1,000–10,000 images) are frequently scattered across deeply nested folders with duplicate copies, missing metadata, and no organized directory taxonomy.
- **Solution:** 
  1. Recursively scan folders in strictly read-only mode (`"rb"`).
  2. Extract EXIF metadata, compute streaming SHA-256 hashes, and render content-addressed WebP thumbnails.
  3. Catalog everything into SQLite (WAL mode) with composite index acceleration.
  4. Detect byte-identical exact duplicates in a single SQL query.
  5. Provide a responsive, local Web Gallery UI with search, filtering, and inspection modal.
  6. Classify images using zero-shot AI (Local Vision model + optional consented Gemini fallback).
  7. Safely organize files by copying byte-for-byte (`shutil.copy2`), verifying SHA-256 fidelity, and preserving originals untouched.
- **Tech Stack:** Python 3.14 (Windows 11 64-bit), FastAPI, SQLite (WAL mode + migrations), Pillow, Pydantic v2, Vanilla HTML5/CSS/JavaScript (zero npm dependencies), pytest.

---

## 2. HARD RULES (Never Break These)

1. **Strictly Read-Only Source Images:** Never modify, move, rename, or delete the user's original images. Source files are opened exclusively in read-only mode (`"rb"`).
2. **Byte-for-Byte File Copies:** The organization step **copies original files byte-for-byte** (`shutil.copy2`). It never creates re-encoded images and never overwrites an existing file.
3. **Cryptographic Copy Verification:** After every copy, **verify the destination SHA-256 equals the source SHA-256**. If they do not match, abort and log an error.
4. **Dry-Run Default:** The organization step **defaults to dry-run** (previewing planned source-to-destination paths). Physical file copying occurs only after explicit user approval.
5. **Thumbnails for Preview Only:** 300×300 WebP thumbnails are exclusively for gallery previews and cloud AI classification. They are never copied into category folders.
6. **AI Only Suggests:** AI models only propose candidate categories with confidence scores. Files are never moved or copied automatically without user review.
7. **Cloud Privacy Guarantee:** Gemini API is **disabled by default**. When enabled with explicit user consent, transmit **only 300×300 thumbnail bytes**—never original image files, source paths, or filenames.
8. **No Secrets in Code:** API keys and environment overrides reside in `.env` (enforced by `.gitignore`). Keep `.env.example` updated.
9. **Test-Driven Development (TDD):** Every bug fix or feature starts with a failing pytest regression test before modifying production code.
10. **Pre-flight Dependency & OS Checks:** Check Python version and OS compatibility (Python 3.14 on Windows) before introducing external packages.

---

## 3. Architecture & Data Flow

```text
Source Folders (Strictly Read-Only)
   │
   ▼
Scanner (Recursive Traversal, Ignored Dirs Pruning, Long Path Resilience)
   │
   ├─► Hasher (Streaming 64 KB Chunk SHA-256)
   ├─► Metadata / EXIF Extractor (Orientation Auto-rotation, Resolution, MTime)
   └─► Thumbnail Cache (300×300 WebP, method=4, Content-Addressed by SHA-256)
   │
   ▼
SQLite Catalog (WAL Mode, Schema Versioning, Composite Gallery Indices)
   │
   ├─► Exact Duplicate Detection (Single-Query Grouping by SHA-256)
   ├─► Near-Duplicate Detection (M5: pHash / dHash Perceptual Similarity)
   │
   ▼
Local AI Classification (M3: Zero-Shot Vision Model matching categories.yaml)
   │
   └─► (Optional Fallback, M4: Consented Gemini Vision on Thumbnails Only)
   │
   ▼
Web Gallery UI (M2: Responsive Grid, Modal Viewer, Live Search & Filters)
   │ (User reviews suggestions, corrects tags, approves organization plan)
   ▼
Safe Organizer (M6: Dry-Run Plan ──► Collision Resolution ──► shutil.copy2 ──► SHA-256 Verify ──► Operation Log)
   │
   ▼
Categorized Output Folders (Byte-for-Byte Copies of Originals)
```

---

## 4. Current Milestone Status

| # | Milestone | Scope | Status |
|---|:---|:---|:---:|
| **M1** | Catalog Core | Scanner, Hasher, Metadata/EXIF, WebP Thumbnails, SQLite, Exact Duplicates | **Complete** |
| **M1.5**| Hardening | Schema Versioning, Composite Indices, 1-Query Duplicates, Cache Headers, Unicode | **Complete** |
| **M2** | Web Gallery UI | Responsive Grid, Detail Modal, Category/Status Filters, Debounced Search, API Serving | **Complete** |
| **M3** | Local AI Vision | Zero-Shot Text-vs-Image Classification using `categories.yaml` anchor prompts | **In Progress** |
| **M4** | Cloud AI Fallback | Optional Gemini API classification (thumbnails only, explicit user consent) | Planned |
| **M5** | Perceptual Duplicates | pHash/dHash similarity clustering and "best shot in group" suggestions | Planned |
| **M6** | Safe Organizer | Dry-run engine, collision renaming, `shutil.copy2`, SHA-256 validation, audit logging | Planned |

---

## 5. Verified Features to Date

- **Recursive Read-Only Scanner:** Scans directories and subfolders without ever altering, moving, or deleting files. Prunes ignored folders (`.git`, `venv`, `node_modules`, `__pycache__`), handles filesystem errors gracefully, and supports Bangla (`বাংলা_স্মৃতি_২০২৪.png`), emoji, and deep Windows MAX_PATH (>260 chars) paths.
- **Incremental Scanning & Caching:** Avoids redundant SHA-256 hashing and EXIF parsing when file path, size, and modification time (`st_mtime`) match existing catalog records.
- **Crash-Resilient Transaction Batching:** Commits SQLite records every 200 items to prevent long database write locks and preserve progress on mid-scan interruptions.
- **Missing & Transient File Tracking:** Detects files moved/deleted between scans or disappearing transiently, marking them `needs_review` in the database without halting.
- **Streaming SHA-256 Hasher:** Processes files in 64 KB memory chunks, ensuring minimal RAM consumption regardless of image file size.
- **High-Speed WebP Thumbnail Generator:** Generates 300×300 WebP thumbnails using `method=4` with transparency support (`RGBA`/palette) and decompression bomb protection (>178M pixels).
- **Fast Content-Addressed Caching:** Serves thumbnails with HTTP `Cache-Control: public, max-age=31536000, immutable` for zero-latency local browser caching.
- **SQLite Database with WAL Mode & Versioning:** Fully indexed database catalog featuring PRAGMA `user_version` migrations and composite query optimization (`idx_images_gallery_order`, `idx_images_cat_date`, `idx_images_status_date`).
- **Single-Query Duplicate Grouping:** Efficient single-query subquery grouping (`WHERE file_hash_sha256 IN (...) GROUP BY ... HAVING COUNT(*) > 1`) avoiding N+1 query overhead.
- **Responsive Web Gallery UI:** Zero-dependency vanilla JavaScript frontend served directly at `/`, complete with debounced search, category/status filters, page size customization (12, 24, 48, 96), and keyboard-navigable image inspection modal.
- **REST API Endpoints:**
  - `GET /api/health`: Health status and app metadata with typed Pydantic models.
  - `GET /api/categories`: Returns active taxonomies loaded from `categories.yaml`.
  - `GET /api/images`: Paginated catalog listing with search and filter parameters.
  - `GET /api/images/{image_id}/thumbnail`: Content-addressed thumbnail streaming with traversal protection.
- **Automated Test Suite:** 100 passing pytest tests covering unit, edge-case, and end-to-end integration scenarios.

---

## 6. Quickstart Guide

### 1. Environment Setup
Open PowerShell in the project directory:
```powershell
.\venv\Scripts\Activate.ps1
```

### 2. Generate Synthetic Test Images
Before scanning personal folders, test safely using synthetic images:
```powershell
python scripts/generate_test_data.py
```
This generates sandbox images in `test_sample_images/` with intentional duplicates and mixed dimensions.

### 3. Run the CLI Scanner
```powershell
python scripts/scan.py
```
Or scan an arbitrary folder:
```powershell
python scripts/scan.py "C:\Path\To\Your\Photos"
```

### 4. Run Automated Test Suite
```powershell
pytest -v
```

### 5. Launch the Local Web Gallery
```powershell
.\venv\Scripts\python.exe -m uvicorn backend.api.app:app --host 127.0.0.1 --port 8000 --reload
```
Open your browser to:
- **Web Gallery UI:** [http://127.0.0.1:8000/](http://127.0.0.1:8000/)
- **Swagger API Docs:** [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)
- **Health Check:** [http://127.0.0.1:8000/api/health](http://127.0.0.1:8000/api/health)

---

## 7. Project Structure

```text
.
├── backend/
│   ├── api/
│   │   ├── app.py             # FastAPI application and route endpoints
│   │   ├── deps.py            # Read-only database session & path validators
│   │   └── schemas.py         # Pydantic response models
│   ├── core/
│   │   ├── hasher.py          # Streaming SHA-256 cryptographic hasher
│   │   ├── metadata.py        # EXIF parser & WebP thumbnail generator
│   │   └── scanner.py         # Recursive read-only directory scanner
│   └── db/
│       ├── schema.py          # SQLite DDL tables, composite indices, migrations
│       ├── session.py         # SQLite connection manager with WAL mode
│       └── repository.py      # CRUD queries and duplicate grouping
├── config/
│   ├── categories.yaml        # Configurable category taxonomy and anchor prompts
│   └── settings.py            # Multi-tier configuration precedence and paths
├── data/                      # Local catalog database & cached thumbnails
├── frontend/                  # Web Gallery UI (Vanilla HTML5 / CSS3 / JS)
│   ├── index.html             # Gallery layout, toolbar, and modal viewer
│   ├── style.css              # Dark neutral responsive CSS grid theme
│   └── app.js                 # API communication, debounced search, modal controls
├── scripts/
│   ├── generate_test_data.py  # Synthetic test image generator
│   └── scan.py                # Command-line scanner runner
├── tests/                     # Automated pytest test suite (100 tests)
├── .env.example               # Environment variables template
├── requirements.txt           # Python package requirements
└── README.md                  # Unified documentation and project roadmap
```

---

## 8. Detailed Milestone Implementation Guide

### Milestone 3: Local AI Classification (Zero-Shot)
- **Model Architecture:** Lightweight zero-shot vision model (ONNX Runtime / quantized MobileCLIP) comparing image embeddings against category anchor prompts in `config/categories.yaml`.
- **Decision Engine:**
  - High confidence ($\ge 0.65$, margin $\ge 0.15$): Propose primary category.
  - Low confidence or ambiguous margin: Mark `status = 'needs_review'` without assigning a category.
- **Evaluation:** Benchmark accuracy on a labeled test subset.

### Milestone 4: Optional Gemini Fallback
- **Privacy Enforcement:** Strictly disabled by default (`ENABLE_GEMINI=false`).
- **Consent Gate:** Activated only when explicitly enabled in configuration and consented to by the user.
- **Payload Safety:** Transmits **only the 300×300 WebP thumbnail bytes** to Gemini. Source filesystem paths and original image bytes are never transmitted.

### Milestone 5: Perceptual Duplicate Detection
- **Algorithms:** Perceptual difference hashing (dHash/pHash) computing 64-bit fingerprint integers.
- **Clustering:** Group photos by Hamming distance ($\le 10$).
- **Selection Assistance:** Suggest the highest-quality image in each group based on pixel resolution and sharpness. The user decides which to retain.

### Milestone 6: Safe Organizer Engine
- **Pre-flight Dry-Run:** Generate a preview manifest showing `source_path ──► destination_path` for all proposed copies.
- **Collision Resolution:** When destination file exists, append numerical suffix (`photo (2).jpg`)—**never overwrite**.
- **Execution:** Copy original files using `shutil.copy2` preserving filesystem timestamps.
- **Integrity Validation:** Re-compute destination file SHA-256 and assert exact equality with source SHA-256.
- **Audit Logging:** Record every copy operation in SQLite `operation_logs` with batch UUIDs for full traceability.

---

## 9. Known Risks & Mitigation Matrix

| Risk Category | Technical Hazard | Architectural Mitigation |
| :--- | :--- | :--- |
| **Python 3.14 Compatibility** | Heavy ML libraries (`torch`, `open-clip`) lack stable wheels or have multi-GB overhead | Verified lightweight ONNX Runtime with native `cp314-win_amd64` wheels |
| **AI Misclassification** | Unreliable predictions placing photos into wrong folders | Strict confidence thresholds + Needs Review queue; AI only suggests |
| **Source Data Loss** | Accidental deletion or mutation of user photos during organizing | Source files opened read-only; organization uses `shutil.copy2` + SHA-256 verification |
| **Cloud Privacy Exposure** | Sending sensitive personal images or filenames to external APIs | Gemini disabled by default; transmits only thumbnail bytes, never paths or originals |
| **UI Performance at Scale** | Slow rendering with 1,000–10,000 images in browser | Pagination, composite SQL indices, and content-addressed immutable HTTP cache |
