# Smart Image Organizer & Gallery — Project Plan & Agent Instructions

> Read this file first. It is the single source of truth for what this project is,
> the rules you must follow, and what to work on next. Also read `README.md`.

---

## 1. About the owner (how to work with me)

- I am a student building this project to **learn** (Python, AI/ML, web development) and for a **university project**.
- I must be able to explain every part of the code in a viva. Explain what you do and why, in simple English.
- After each step, name **one concept** I should learn from it.
- Prefer small, reviewable steps over big rewrites.

---

## 2. What the project is

A **local-first, privacy-respecting Windows desktop tool** that organizes 1,000–10,000 mixed images.

**Problem:** Thousands of images are scattered across many folders, with duplicates and no categories.

**Solution:** Scan folders (read-only), catalog every image, find duplicates, suggest categories with AI, let the user review and approve, then **copy** approved files into categorized folders.

**Tech stack:** Python 3.14 (see risk in section 7), FastAPI, SQLite (WAL mode), Pillow, Pydantic, pytest. Windows 10/11.

---

## 3. HARD RULES (never break these)

1. **Never modify, move, rename, or delete the user's original images.** Source files are opened read-only (`"rb"`).
2. The organize step **copies original files byte-for-byte** (`shutil.copy2`). It never creates a new/re-encoded image and never overwrites an existing file.
3. After every copy, **verify the destination SHA-256 equals the source SHA-256**. If not, report an error.
4. The organize step **defaults to dry-run** (show what would be copied; copy only after the user approves).
5. **Thumbnails (300x300 WebP) are only for the gallery preview.** They are never what gets placed in category folders.
6. **AI only suggests.** Nothing is copied until the user approves.
7. **Privacy:** Gemini API is OFF by default. When enabled and the user consents, send **only the thumbnail**, never the original, never file paths or filenames.
8. No secrets in code. Use `.env` (listed in `.gitignore`); keep `.env.example` updated.
9. Do not start a new milestone until I approve it.
10. Show a plan and **wait for my approval before editing files**.
11. Every behavior change needs a **pytest test**. Run `pytest` and show the results.
12. Do not add heavy dependencies without asking. Check compatibility with my Python version first.
13. Do not "fix" a suspected bug without first writing a test that proves the bug exists.

---

## 4. Architecture / data flow

```
Source folders (read-only)
   ↓
Scanner → Hasher (SHA-256) → Metadata/EXIF → WebP thumbnail
   ↓
SQLite catalog (images, categories, operation log)
   ↓
Duplicate detection (exact: SHA-256 · similar: pHash/dHash)
   ↓
AI classification (local model → optional Gemini on thumbnails)
   ↓
Web gallery (user reviews, corrects category, approves)
   ↓
Organizer (dry-run → copy → hash verify → log)
   ↓
Categorized folders (hubohu copies of originals)
```

### Project structure

```
backend/
  api/   app.py, deps.py, schemas.py   # FastAPI app, dependencies, Pydantic models
  core/  scanner.py, hasher.py, metadata.py
  db/    schema.py, session.py, repository.py
config/  categories.yaml, settings.py
data/    catalog DB + thumbnail cache
scripts/ scan.py, generate_test_data.py
tests/
```

---

## 5. Milestones

| # | Milestone | Status |
|---|-----------|--------|
| M1 | Scanner, hasher, metadata/EXIF, thumbnails, SQLite catalog, exact duplicates, tests | **Done** |
| M1.5 | **Hardening from the audit (current)** | **In progress** |
| M2 | Web gallery UI (partly started: `/api/images`, thumbnail endpoint) | Planned |
| M3 | Local AI classification (zero-shot, text-vs-image matching) | Planned |
| M4 | Optional Gemini fallback (thumbnails only, consent required) | Planned |
| M5 | Near-duplicate detection (pHash/dHash) + "best photo in group" suggestion | Planned |
| M6 | Safe organizer: dry-run → copy → verify → log (not numbered in the README; added here) | Planned |

### M1.5 Hardening — ordered batches

Each batch: plan → write failing tests → implement → run pytest → explain → suggest a git commit message.

**Batch 1 — Transaction batching + incremental scan (CURRENT TASK)**
- Commit to SQLite every ~200 images, so a crash mid-scan keeps earlier batches.
- Skip hashing and metadata only if **path, size AND mtime** all match the existing DB row.
- Handle files deleted/moved since the last scan (report or mark them; never touch source files).
- Handle a file disappearing between the collect pass and the process pass (`FileNotFoundError`) as a transient change, not a generic error.
- Re-scanning an unchanged folder must create **zero new rows** and finish quickly.

**Batch 2 — Thumbnails and settings**
- Fix palette (`P`) / transparent GIF and PNG thumbnails turning into black boxes (convert to `RGBA` or composite on a neutral background).
- Remove folder creation at import time in `config/settings.py` (create dirs in an explicit startup step / FastAPI lifespan).
- Consider `method=4` instead of `method=6` for WebP encoding (speed), ideally configurable.
- Catch `Image.DecompressionBombError`/warning and skip the file with a clear message; set an explicit pixel ceiling.

**Batch 3 — Unicode and edge-case tests**
- Non-ASCII filenames, including Bangla (e.g. `গ্যালারি.png`), Japanese, accented names, emojis.
- Re-scan idempotency, repository lookup functions (`get_image_by_hash`, `get_image_by_path`, category lookups, `log_operation`).
- Long Windows paths (>260 chars), via extended-length path handling if needed.

**Batch 4 — API polish**
- `Cache-Control: public, max-age=31536000, immutable` on thumbnails (they are content-addressed by hash).
- Typed Pydantic response models (e.g. health check).
- CORS **only if** the frontend runs on a separate dev server (e.g. Vite on port 5173). If FastAPI serves the UI itself, CORS is not needed. Decide this first.
- Update README: document `GET /api/images` (pagination, filters) and `GET /api/images/{id}/thumbnail`; fix the project-structure section.

**Batch 5 — Database**
- Add schema versioning (`PRAGMA user_version` + incremental migrations) before M2 adds columns.
- Composite index for gallery ordering; replace the N+1 queries in exact-duplicate lookup with a single query.
- Replace `print()` with the standard `logging` module.

### Audit findings that need verification before fixing

The automated audit made some claims that are likely wrong or overstated. **Do not change code for these until a test proves the problem:**

1. **"SQLite `ORDER BY ... DESC` puts NULLs first."** Likely incorrect: SQLite treats NULL as the smallest value, so NULLs come **last** on DESC. Write a test with a row that has no `date_taken` and check the real order. `NULLS LAST` is harmless but is not a bug fix.
2. **"`busy_timeout` PRAGMA is needed."** Python's `sqlite3.connect(timeout=...)` already sets the busy timeout. Likely redundant.
3. **Decompression bomb threshold.** Pillow warns at ~89M pixels and raises an error at about double that. Verify actual behavior before writing the test.
4. **Windows device names (`CON`, `NUL`)** on thumbnail paths: thumbnails are named by SHA-256 hash, so this is very low risk.
5. **Severity labels.** "Critical" for import-time folder creation is overstated (code-quality issue). Incremental scanning is a High performance issue, not Critical.
6. The audit cited line numbers in files it did not list as analyzed (`metadata.py`, `repository.py`, `app.py`, `deps.py`, `schema.py`). **Open those files and verify each line reference yourself.**

---

## 6. Feature design details

### AI decision flow (hybrid)

```
Image → local model → high confidence?   → suggest category → user approves
                      ↓ low
        Gemini enabled AND user consented? → send thumbnail only → suggest
                      ↓ no
        "Needs Review" bucket (no category assigned)
```

- Every suggestion carries a **confidence score**.
- Low-confidence images go to a **Needs Review** bucket, never into a wrong category.
- M3 model choice: a CLIP/SigLIP-style zero-shot model that matches image embeddings with the anchor prompts in `config/categories.yaml` is the assumed approach. **Confirm with me before choosing a model or installing libraries.**
- Evaluate on a small labeled set (50–100 images) and report accuracy.

### Duplicates

- **Exact:** same SHA-256 → byte-identical files. Hashing never changes or deletes anything.
- **Similar (M5):** pHash/dHash for resized/cropped/re-compressed copies; suggest the best photo in a group (resolution, sharpness). The user chooses.
- Do not copy both files of an exact duplicate pair into the category folder; copy one (the user picks which).

### Organizer (M6)

1. User approves selected images.
2. **Dry-run** shows `source → destination` for every file.
3. Name collisions get a new name (`IMG_001 (2).jpg`); **never overwrite**.
4. Copy with `shutil.copy2`.
5. Verify destination SHA-256 == source SHA-256.
6. Write an operation log row (source, destination, hash, timestamp) via `log_operation()`. This enables undo/reporting.
7. Optional idea: "virtual categories" (store category in the DB, export only on request) to avoid doubling disk usage.

---

## 7. Known risks

| Risk | Mitigation |
|------|------------|
| ML libraries (`torch`, `onnxruntime`, etc.) may lack wheels for Python 3.14 on Windows | Test install **before** writing M3 code; otherwise use a Python 3.11/3.12 venv |
| AI assigns wrong categories | Confidence threshold, Needs Review bucket, user approval |
| Data loss during copy | Dry-run, never overwrite, hash verify, operation log |
| Privacy leak to cloud AI | Off by default, thumbnails only, explicit consent, no paths/filenames |
| Slow UI at 10,000 images | Pagination/lazy loading, cached thumbnails with immutable headers, DB indexes |
| Scope creep | One milestone at a time, approval before starting the next |

---

## 8. Definition of done (every batch/milestone)

- [ ] Failing tests written first, now passing; full `pytest` run is green.
- [ ] Hard rules in section 3 still hold (add a test where relevant).
- [ ] Plain-English explanation given, plus one concept to learn.
- [ ] README updated if behavior or endpoints changed.
- [ ] Suggested git commit message provided.

---

## 9. What to do right now

**Task: M1.5 Batch 1 only.**
1. Re-read `README.md` and this file.
2. Write a short plan for Batch 1 and **wait for my approval**.
3. After approval: write failing tests first, then implement, then run `pytest` and explain the changes.
4. Do not touch Batch 2+ or any later milestone.
