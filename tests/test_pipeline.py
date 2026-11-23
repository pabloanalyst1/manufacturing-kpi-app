"""End-to-end: marts reconcile with the facts, exports are written, the case-study queries run and the
app's KPI module gives the same answers as the SQL marts."""
import sqlite3
import sys
from pathlib import Path

import pandas as pd
import pytest

from src import kpi
from src.export import export_marts

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from run_case_study import run_queries  # noqa: E402

EXPECTED_MARTS = {
    "mart_oee_daily", "mart_oee_monthly", "mart_oee_by_shift", "mart_oee_losses", "mart_loss_value",
    "mart_downtime_pareto", "mart_downtime_monthly", "mart_reliability", "mart_changeovers_monthly",
    "mart_smed_evaluation", "mart_changeover_matrix", "mart_scrap_by_defect", "mart_scrap_by_supplier",
    "mart_scrap_drivers", "mart_production_monthly", "mart_shift_detail", "mart_kpi_summary",
}


def test_marts_reconcile_with_facts(small_warehouse):
    with sqlite3.connect(small_warehouse) as conn:
        q = lambda sql: conn.execute(sql).fetchone()[0]  # noqa: E731
        assert q("SELECT SUM(good_units) FROM mart_oee_daily") == q("SELECT SUM(good_units) FROM fct_shift_oee")
        assert q("SELECT SUM(good_units) FROM mart_production_monthly") == q("SELECT SUM(good_units) FROM fct_production")
        assert q("SELECT SUM(scrap_units) FROM mart_scrap_by_defect") == q("SELECT SUM(scrap_units) FROM fct_shift_oee")
        assert q("SELECT SUM(stops) FROM mart_downtime_monthly") == q("SELECT COUNT(*) FROM fct_downtime_events")
        # the six big losses add up to planned production time, for every line and the plant
        for line, total in conn.execute("SELECT line_id, SUM(share_of_planned_time) FROM mart_oee_losses GROUP BY 1"):
            assert total == pytest.approx(1, abs=0.002), line
        assert q("SELECT MAX(cumulative_share) FROM mart_downtime_pareto") == pytest.approx(1)


def test_export_writes_every_mart(small_warehouse, tmp_path):
    written = export_marts(small_warehouse, tmp_path)
    assert {p.stem for p in written} == EXPECTED_MARTS
    kpis = pd.read_csv(tmp_path / "mart_kpi_summary.csv").set_index("kpi")
    assert 0.4 < kpis.loc["OEE", "current_value"] < 0.9


def test_every_case_study_query_runs(small_warehouse):
    results = run_queries(small_warehouse)
    assert len(results) == 10
    for name, question, _, df in results:
        assert question, name
        assert len(df) > 0, name


def test_app_kpis_match_the_sql_marts(small_warehouse):
    t = kpi.load_tables(small_warehouse)
    by_line = kpi.oee_by(t["shifts"], "line_id").set_index("line_id")
    with sqlite3.connect(small_warehouse) as conn:
        mart = pd.read_sql("""SELECT line_id, SUM(ideal_min_good) / SUM(planned_time_min) AS oee
                              FROM mart_oee_daily GROUP BY line_id""", conn).set_index("line_id")
        losses = pd.read_sql("SELECT step_order, share_of_planned_time FROM mart_oee_losses WHERE line_id = 'Plant'", conn)
    pd.testing.assert_series_equal(by_line["oee"], mart["oee"], atol=1e-4, check_names=False)
    assert kpi.six_big_losses(t["shifts"])["share"].tolist() == pytest.approx(losses["share_of_planned_time"].tolist(), abs=1e-4)
    one_line = kpi.filter_frame(t["shifts"], ["L01"], "2025-12-01", "2025-12-31")
    assert set(one_line["line_id"]) == {"L01"} and one_line["shift_date"].dt.month.unique().tolist() == [12]
