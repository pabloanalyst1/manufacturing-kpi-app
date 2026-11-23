"""Quality checks pass on good data and stop the pipeline on bad data."""
import shutil
import sqlite3

import pytest

from src.quality import CHECKS, DataQualityError, run_quality_checks


def test_all_checks_pass_on_generated_data(small_warehouse):
    results = run_quality_checks(small_warehouse)
    assert len(results) == len(CHECKS)
    assert all(bad == 0 for bad in results.values())


def test_bad_data_stops_the_pipeline(small_warehouse, tmp_path):
    broken = tmp_path / "broken.db"
    shutil.copy(small_warehouse, broken)
    with sqlite3.connect(broken) as conn:
        conn.execute("UPDATE stg_shift_reports SET line_id = 'L09' WHERE rowid = 1")
        conn.execute("UPDATE fct_shift_oee SET quality = 1.2 WHERE rowid = 1")
    with pytest.raises(DataQualityError, match="2 data quality check"):
        run_quality_checks(broken)
