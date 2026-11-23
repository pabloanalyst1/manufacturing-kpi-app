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


def test_app_builds_the_warehouse_on_first_start(tmp_path, monkeypatch):
    """No warehouse and no KPI_DB_PATH (a fresh Streamlit Cloud deploy): the app runs the pipeline itself."""
    testing = pytest.importorskip("streamlit.testing.v1")
    import src.config as config

    monkeypatch.delenv("KPI_DB_PATH", raising=False)
    monkeypatch.setenv("MONGO_URI", "mongodb://localhost:1")  # no MongoDB, like Streamlit Cloud
    monkeypatch.setattr(config.PipelineConfig, "__init__", _tmp_config(tmp_path))
    at = testing.AppTest.from_file(str(APP), default_timeout=180).run()
    assert not at.exception, at.exception
    assert (tmp_path / "warehouse.db").exists()
    assert at.metric[0].label == "OEE"


def _tmp_config(tmp_path):
    """PipelineConfig that writes everything under tmp_path and simulates four months (fast)."""
    import dataclasses

    import src.config as config

    original = config.PipelineConfig.__init__

    def init(self, *args, **kwargs):
        original(self, *args, **kwargs)
        self.raw_dir, self.db_path, self.export_dir = tmp_path / "raw", tmp_path / "warehouse.db", tmp_path / "exports"
        self.start_date, self.end_date = "2025-11-01", "2026-02-28"

    assert dataclasses.is_dataclass(config.PipelineConfig)
    return init
