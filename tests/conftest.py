"""Shared fixtures: a small warehouse built once per test session (four months around the SMED start)."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.config import PipelineConfig  # noqa: E402
from src.generate_data import generate_all  # noqa: E402
from src.load import load_raw  # noqa: E402
from src.mongo_store import flatten_documents  # noqa: E402
from src.transform import run_sql_models  # noqa: E402

SMALL = {"seed": 7, "start": "2025-11-01", "end": "2026-02-28"}


@pytest.fixture(scope="session")
def small_extract():
    return generate_all(**SMALL)


@pytest.fixture(scope="session")
def small_warehouse(tmp_path_factory, small_extract) -> Path:
    """Full pipeline (without MongoDB and export) on four months of simulated shifts."""
    docs, erp = small_extract
    db = tmp_path_factory.mktemp("wh") / "warehouse.db"
    load_raw(flatten_documents(docs), erp, db, SMALL["start"], SMALL["end"])
    run_sql_models(db, PipelineConfig().sql_dir)
    return db
