"""Smoke test: the Streamlit app renders without errors on a real warehouse (runs where streamlit is installed)."""
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[1] / "app" / "streamlit_app.py"


def test_app_renders(small_warehouse, monkeypatch):
    testing = pytest.importorskip("streamlit.testing.v1")
    monkeypatch.setenv("KPI_DB_PATH", str(small_warehouse))
    at = testing.AppTest.from_file(str(APP), default_timeout=60).run()
    assert not at.exception, at.exception
    assert len(at.metric) >= 8
    assert at.metric[0].label == "OEE"


def test_app_explains_a_missing_warehouse(tmp_path, monkeypatch):
    testing = pytest.importorskip("streamlit.testing.v1")
    monkeypatch.setenv("KPI_DB_PATH", str(tmp_path / "missing.db"))
    at = testing.AppTest.from_file(str(APP), default_timeout=60).run()
    assert not at.exception
    assert "run_pipeline.py" in at.error[0].value
