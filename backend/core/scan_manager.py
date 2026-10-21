"""
Scan and Classification Background Task Manager.

Coordinates asynchronous scanning and classification runs without blocking
FastAPI request handling, exposing thread-safe progress queries.
"""

import threading
import logging
from pathlib import Path
from typing import Optional, Dict, Any

from backend.core.scanner import scan_directory, ScanProgress
from backend.core.classifier import LocalVisionClassifier

logger = logging.getLogger("backend.core.scan_manager")


class BackgroundTaskCoordinator:
    """Thread-safe background scan and classification coordinator."""

    def __init__(self):
        self._lock = threading.Lock()
        self._scan_thread: Optional[threading.Thread] = None
        self._classify_thread: Optional[threading.Thread] = None

        self._scan_state: Dict[str, Any] = {
            "is_running": False,
            "source_path": None,
            "total_found": 0,
            "processed_count": 0,
            "skipped_count": 0,
            "error_count": 0,
            "is_complete": False,
            "errors": [],
        }

        self._classify_state: Dict[str, Any] = {
            "is_running": False,
            "processed": 0,
            "total": 0,
            "classified_count": 0,
            "needs_review_count": 0,
            "is_complete": False,
        }

    # --- Scanning Methods ---

    def start_scan(self, source_path: str, exclude_path: Optional[str] = None, db_path: Optional[Path] = None) -> bool:
        with self._lock:
            if self._scan_state["is_running"]:
                return False

            self._scan_state = {
                "is_running": True,
                "source_path": source_path,
                "total_found": 0,
                "processed_count": 0,
                "skipped_count": 0,
                "error_count": 0,
                "is_complete": False,
                "errors": [],
            }

        def _worker():
            try:
                def _progress_cb(p: ScanProgress):
                    with self._lock:
                        self._scan_state["total_found"] = p.total_found
                        self._scan_state["processed_count"] = p.processed_count
                        self._scan_state["skipped_count"] = p.skipped_count
                        self._scan_state["error_count"] = p.error_count
                        self._scan_state["errors"] = list(p.errors)

                excludes = [exclude_path] if exclude_path else None
                progress = scan_directory(
                    directory_path=source_path,
                    progress_callback=_progress_cb,
                    db_path=db_path,
                    exclude_dirs=excludes,
                )
                with self._lock:
                    self._scan_state["total_found"] = progress.total_found
                    self._scan_state["processed_count"] = progress.processed_count
                    self._scan_state["skipped_count"] = progress.skipped_count
                    self._scan_state["error_count"] = progress.error_count
                    self._scan_state["errors"] = list(progress.errors)
                    self._scan_state["is_complete"] = True
            except Exception as e:
                logger.error(f"Scan background worker error: {e}")
                with self._lock:
                    self._scan_state["errors"].append(str(e))
                    self._scan_state["is_complete"] = True
            finally:
                with self._lock:
                    self._scan_state["is_running"] = False

        self._scan_thread = threading.Thread(target=_worker, daemon=True)
        self._scan_thread.start()
        return True

    def get_scan_status(self) -> Dict[str, Any]:
        with self._lock:
            return dict(self._scan_state)

    # --- Classification Methods ---

    def start_classification(self, db_path: Optional[Path] = None) -> bool:
        with self._lock:
            if self._classify_state["is_running"]:
                return False

            self._classify_state = {
                "is_running": True,
                "processed": 0,
                "total": 0,
                "classified_count": 0,
                "needs_review_count": 0,
                "is_complete": False,
            }

        def _worker():
            try:
                classifier = LocalVisionClassifier()

                def _progress_cb(info: Dict[str, Any]):
                    with self._lock:
                        self._classify_state["processed"] = info["processed"]
                        self._classify_state["total"] = info["total"]

                summary = classifier.classify_catalog(db_path=db_path, progress_callback=_progress_cb)
                with self._lock:
                    self._classify_state["classified_count"] = summary["classified_count"]
                    self._classify_state["needs_review_count"] = summary["needs_review_count"]
                    self._classify_state["is_complete"] = True
            except Exception as e:
                logger.error(f"Classification background worker error: {e}")
                with self._lock:
                    self._classify_state["is_complete"] = True
            finally:
                with self._lock:
                    self._classify_state["is_running"] = False

        self._classify_thread = threading.Thread(target=_worker, daemon=True)
        self._classify_thread.start()
        return True

    def get_classification_status(self) -> Dict[str, Any]:
        with self._lock:
            return dict(self._classify_state)


coordinator = BackgroundTaskCoordinator()
