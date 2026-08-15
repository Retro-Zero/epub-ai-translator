"""Root launcher: `uvicorn main:app` from the repo root.

The real app lives in backend/app; this shim puts backend/ on sys.path so the
standard uvicorn entry point works without `cd backend`.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "backend"))

from app.main import app  # noqa: E402
