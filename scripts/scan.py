"""
CLI Runner for the Image Scanner.

Allows running and testing the scanner directly from the terminal.
Usage:
    python scripts/scan.py [path_to_folder]
If no path is provided, it defaults to 'test_sample_images/'.
"""

import sys
import time
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from config.settings import settings
from backend.db.session import init_db, db_session
from backend.db import repository
from backend.core.scanner import scan_directory, ScanProgress


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    if len(sys.argv) > 1:
        target_dir = Path(sys.argv[1]).resolve()
    else:
        target_dir = PROJECT_ROOT / "test_sample_images"

    print("=" * 60)
    print(" Smart Image Organizer & Gallery — Catalog Scanner")
    print("=" * 60)
    print(f"Target Directory: {target_dir}")

    if not target_dir.exists():
        print(f"[!] Error: Target directory does not exist: {target_dir}")
        print("Tip: Run 'python scripts/generate_test_data.py' first to create synthetic test images.")
        return

    # Ensure data and thumbnail storage directories exist
    settings.ensure_directories()

    # Ensure database tables and categories exist
    print("[*] Initializing SQLite database (WAL mode)...")
    init_db()

    start_time = time.time()

    def progress_callback(p: ScanProgress):
        if p.current_file:
            sys.stdout.write(f"\rScanning [{p.processed_count}/{p.total_found}]: {p.current_file[:35]:<35}")
            sys.stdout.flush()

    print("[*] Starting recursive read-only scan...")
    progress = scan_directory(str(target_dir), progress_callback=progress_callback)
    duration = time.time() - start_time

    print(f"\n[+] Scan finished in {duration:.2f} seconds!")
    print(f"    - Total Candidates Found: {progress.total_found}")
    print(f"    - Successfully Indexed:   {progress.processed_count}")
    print(f"    - Skipped / Errors:       {progress.error_count}")

    if progress.errors:
        print("[!] Encountered errors during scan:")
        for err in progress.errors[:5]:
            print(f"    - {err}")

    # Inspect database catalog
    with db_session() as conn:
        total_in_db = repository.count_images(conn)
        dup_groups = repository.find_exact_duplicates(conn)
        print(f"\nDatabase Catalog State:")
        print(f"    - Total Images in Catalog: {total_in_db}")
        print(f"    - Exact Duplicate Groups:  {len(dup_groups)}")

        for idx, grp in enumerate(dup_groups, 1):
            print(f"\n      Duplicate Group #{idx} (Hash: {grp['file_hash_sha256'][:12]}...):")
            for img in grp["images"]:
                print(f"        -> {img['file_path']} ({img['width']}x{img['height']}, {img['file_size']} bytes)")

    print("=" * 60)


if __name__ == "__main__":
    main()
