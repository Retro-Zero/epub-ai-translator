"""Per-chapter job progress, persisted to progress.json so it survives
server restarts. Single-user scale; a lock guards concurrent writers."""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path

PENDING = "pending"
IN_PROGRESS = "in_progress"
DONE = "done"
FAILED = "failed"
SKIPPED = "skipped"


class ProgressTracker:
    def __init__(self, path: Path):
        self.path = path
        self._lock = threading.Lock()

    def _load(self) -> dict:
        if self.path.exists():
            return json.loads(self.path.read_text(encoding="utf-8"))
        return {"chapters": {}, "running": False, "updated_at": None}

    def _save(self, data: dict) -> None:
        data["updated_at"] = time.time()
        self.path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")

    def ensure_init(self, chapter_ids: list) -> None:
        """Initialize all chapters to pending (no-op if progress exists)."""
        with self._lock:
            data = self._load()
            if not data["chapters"]:
                data["chapters"] = {cid: PENDING for cid in chapter_ids}
                data["running"] = False
                self._save(data)

    def init(self, chapter_ids: list) -> None:
        """Reset all chapters to pending (used when a full run starts)."""
        with self._lock:
            data = self._load()
            data["chapters"] = {cid: PENDING for cid in chapter_ids}
            data["running"] = False
            self._save(data)

    def set(self, chapter_id: str, status: str) -> None:
        with self._lock:
            data = self._load()
            data["chapters"][chapter_id] = status
            self._save(data)

    def set_running(self, running: bool) -> None:
        with self._lock:
            data = self._load()
            data["running"] = running
            self._save(data)

    def get(self) -> dict:
        with self._lock:
            return self._load()
