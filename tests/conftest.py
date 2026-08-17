"""Prevent test pollution of the real data/jobs/ directory.

Every test that creates a job (upload, translate, QA, finalize...) writes
into jobs.DATA_DIR. Without isolation, a single pytest run creates dozens of
job dirs in the working copy — that's how ~1,100 leftover dirs accumulated.
This module remaps DATA_DIR to a per-run temp dir so the real working data
stays clean. It also asserts the remap actually took effect.
"""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest


@pytest.fixture(scope="session", autouse=True)
def isolated_jobs_dir():
    """Point jobs.DATA_DIR at a temp dir for the whole test session."""
    from app import jobs

    tmp = Path(tempfile.mkdtemp(prefix="epub-jobs-test-"))
    original = jobs.DATA_DIR
    jobs.DATA_DIR = tmp
    yield tmp
    jobs.DATA_DIR = original
    import shutil

    shutil.rmtree(tmp, ignore_errors=True)


def test_jobs_data_dir_is_isolated(tmp_path):
    """The session fixture must have redirected jobs away from the repo."""
    from app import jobs

    repo_data = Path(__file__).resolve().parent.parent / "data" / "jobs"
    assert jobs.DATA_DIR != repo_data
    assert str(jobs.DATA_DIR).startswith("/var/folders") or str(
        jobs.DATA_DIR
    ).startswith("/tmp") or "temp" in str(jobs.DATA_DIR).lower()
