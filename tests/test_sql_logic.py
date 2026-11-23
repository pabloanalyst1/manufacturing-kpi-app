"""Staging rules and OEE math tested on hand-made MES documents where the right answer is known."""
import sqlite3

import pandas as pd
import pytest

from src.config import PipelineConfig
from src.generate_data import generate_reference_tables
from src.load import load_raw
from src.mongo_store import flatten_documents


def v2(report_id, line, day, shift, start, production, events, ingested, resin_lot=None):
    doc = {"report_id": report_id, "schema_version": 2, "line": line, "shift_date": day, "shift": shift,
           "shift_start": start, "shift_minutes": 480, "crew": {"supervisor": "S01", "operators": 4},
           "production": production, "downtime_events": events, "ingested_at": ingested}
    if resin_lot:
        doc["resin_lot"] = resin_lot
    return doc


def ev(code, start, end, **extra):
    return {"reason_code": code, "start": f"2026-02-02T{start}", "end": end if "T" in end else f"2026-02-02T{end}", **extra}


# L01 morning shift, firmware v2, with every problem staging has to handle
FINAL = v2("L01-20260202-A", "L-01", "2026-02-02", "A", "2026-02-02T06:00:00",
           [{"sku": "pf-18g ", "good_units": 48000, "scrap": [{"defect": "Short shot", "units": 700}, {"defect": "Flash", "units": 500}]},
            {"sku": "PF-24G", "good_units": 42600, "scrap": [{"defect": "Splay / bubbles", "units": 400}]}],
           [ev("BRK", "06:00:00", "06:30:00"),                                 # planned: 30 min
            ev("MECH", "07:00:00", "07:40:00"),                                # breakdown: 40 min
            ev("JAM", "08:00:00", "08:03:00"),                                 # minor stop: 3 min
            ev("JAM", "08:00:00", "08:03:00"),                                 # logged twice
            ev(" co", "09:00:00", "10:00:00", from_sku="PF-18G", to_sku="PF-24G"),  # changeover: 60 min
            ev("ELEC", "12:10:00", "12:00:00"),                                # ends before it starts
            ev("QH", "13:30:00", "2026-02-02T14:45:00")],                      # clipped to 14:00: 30 min
           "2026-02-02T14:07:00", resin_lot="PET-1")
INTERIM = {**FINAL, "ingested_at": "2026-02-02T12:52:00",
           "production": [{"sku": "PF-18G", "good_units": 30000, "scrap": []}]}

# L03 afternoon shift, firmware v1 (old layout, legacy codes, dd/mm/yyyy timestamps)
V1 = {"report_id": "L03-20250707-B", "schema_version": 1, "line_name": "Línea 3", "shift_date": "2025-07-07",
      "shift": "B", "shift_start": "2025-07-07T14:00:00", "shift_minutes": 480,
      "crew": {"supervisor": "S02", "operators": 4},
      "production": [{"sku": "BT-600W", "good": "100,000", "defects": {"Thin wall": 800, "Leaker": 200}}],
      "stops": [{"code": "BREAK", "started": "07/07/2025 18:00", "minutes": 30.0},
                {"code": "SETUP", "started": "07/07/2025 15:00", "minutes": 45.5, "from_sku": "BT-1500", "to_sku": "BT-600W"},
                {"code": "???", "started": "07/07/2025 20:00", "minutes": 10.0},
                {"code": "jammed ", "started": "07/07/2025 21:00", "minutes": 4.0}],
      "ingested_at": "2025-07-07T22:07:00"}

OVERFLOW = v2("L02-20260202-A", "L02", "2026-02-02", "A", "2026-02-02T06:00:00",
              [{"sku": "PF-38G", "good_units": 4_294_967_000, "scrap": []}], [ev("BRK", "10:00:00", "10:30:00")],
              "2026-02-02T14:07:00", resin_lot="PET-1")
CAPS = v2("L05-20260202-B", "LINE 5", "2026-02-02", "B", "2026-02-02T14:00:00",
          [{"sku": "CP-28", "good_units": 300000, "scrap": []}],
          [{"reason_code": "BRK", "start": "2026-02-02T18:00:00", "end": "2026-02-02T18:30:00"}], "2026-02-02T22:07:00")

RESIN = pd.DataFrame([
    ("PET-1", "PET", "RESINAS DEL GOLFO", "28/01/2026", 10.70, 60),
    ("PET-1", "PET", "RESINAS DEL GOLFO", "28/01/2026", 10.70, 60),   # duplicated row in the ERP extract
], columns=["lot_id", "resin_type", "supplier", "received_date", "price_gtq_per_kg", "moisture_ppm"])


@pytest.fixture(scope="module")
def db(tmp_path_factory):
    erp = generate_reference_tables()
    erp["resin_lots"] = RESIN
    path = tmp_path_factory.mktemp("logic") / "test.db"
    load_raw(flatten_documents([FINAL, INTERIM, V1, OVERFLOW, CAPS]), erp, path, "2025-07-01", "2026-02-28")
    from src.transform import run_sql_models
    run_sql_models(path, PipelineConfig().sql_dir)
    conn = sqlite3.connect(path)
    yield conn
    conn.close()


def table(conn, name, index):
    return pd.read_sql(f"SELECT * FROM {name}", conn).set_index(index)


def test_final_copy_wins_and_overflow_is_rejected(db):
    reports = table(db, "stg_shift_reports", "report_id")
    assert sorted(reports.index) == ["L01-20260202-A", "L03-20250707-B", "L05-20260202-B"]
    assert reports.loc["L01-20260202-A", "copies"] == 2
    rejected = pd.read_sql("SELECT report_id, reject_reason FROM stg_rejected_shift_reports", db)
    assert rejected.to_dict("records") == [{"report_id": "L02-20260202-A", "reject_reason": "Counter overflow"}]
    prod = table(db, "stg_production", ["report_id", "sku"])
    assert prod.loc[("L01-20260202-A", "PF-18G"), "good_units"] == 48000    # not the interim 30,000


def test_line_ids_skus_and_v1_values_are_cleaned(db):
    reports = table(db, "stg_shift_reports", "report_id")
    assert reports["line_id"].to_dict() == {"L01-20260202-A": "L01", "L03-20250707-B": "L03", "L05-20260202-B": "L05"}
    prod = table(db, "stg_production", ["report_id", "sku"])
    assert ("L01-20260202-A", "PF-18G") in prod.index                       # 'pf-18g ' -> 'PF-18G'
    assert prod.loc[("L03-20250707-B", "BT-600W"), "good_units"] == 100000  # '100,000' -> 100000
    assert prod.loc[("L03-20250707-B", "BT-600W"), "scrap_units"] == 1000   # v1 defects object summed


def test_downtime_codes_timestamps_duplicates_and_clipping(db):
    e = pd.read_sql("SELECT * FROM stg_downtime_events ORDER BY report_id, start_ts", db)
    l1 = e[e["report_id"] == "L01-20260202-A"]
    assert l1["reason_code"].tolist() == ["BRK", "MECH", "JAM", "CO", "QH"]  # duplicate JAM and bad ELEC gone
    qh = l1[l1["reason_code"] == "QH"].iloc[0]
    assert qh["end_ts"] == "2026-02-02 14:00:00" and qh["is_clipped"] == 1 and qh["duration_min"] == 30
    rej = pd.read_sql("SELECT reason_code, reject_reason FROM stg_rejected_downtime_events", db)
    assert rej.to_dict("records") == [{"reason_code": "ELEC", "reject_reason": "Ends before it starts"}]
    assert pd.read_sql("SELECT COUNT(*) AS n FROM stg_duplicate_downtime_events", db)["n"][0] == 1
    v1 = e[e["report_id"] == "L03-20250707-B"].set_index("reason_code")
    assert v1.loc["CO", "start_ts"] == "2025-07-07 15:00:00"               # dd/mm/yyyy parsed
    assert v1.loc["CO", "duration_min"] == pytest.approx(45.5)             # end = start + minutes
    assert set(v1.index) == {"BRK", "CO", "UNK", "JAM"}                     # legacy + unclassified codes


def test_oee_math_on_a_known_shift(db):
    f = table(db, "fct_shift_oee", "report_id").loc["L01-20260202-A"]
    assert f["planned_time_min"] == pytest.approx(450)                     # 480 - 30 min break
    assert f["availability_loss_min"] == pytest.approx(130)                # 40 MECH + 60 CO + 30 QH (clipped)
    assert f["minor_stop_min"] == pytest.approx(3) and f["minor_stops"] == 1
    assert f["breakdowns"] == 1 and f["changeovers"] == 1
    assert f["availability"] == pytest.approx(320 / 450, abs=1e-4)
    ideal_total = 49200 / 480 + 43000 / 430                                # ideal minutes of every unit made
    ideal_good = 48000 / 480 + 42600 / 430
    assert f["performance"] == pytest.approx(ideal_total / 320, abs=1e-4)
    assert f["quality"] == pytest.approx(90600 / 92200, abs=1e-4)
    assert f["oee"] == pytest.approx(ideal_good / 450, abs=1e-4)
    assert f["oee"] == pytest.approx(f["availability"] * f["performance"] * f["quality"], abs=1e-3)
    assert f["smed_group"] == "Pilot" and f["smed_period"] == "Post"


def test_resin_lots_and_changeover_flags(db):
    f = table(db, "fct_shift_oee", "report_id")
    assert f.loc["L05-20260202-B", "resin_lot"] == "UNKNOWN"               # cap line, lot not scanned
    assert pd.isna(f.loc["L03-20250707-B", "resin_lot"])                    # blow molding uses no resin lot
    lots = table(db, "dim_resin_lot", "lot_id")
    assert lots.loc["PET-1", "supplier"] == "Resinas del Golfo" and lots.loc["PET-1", "received_date"] == "2026-01-28"
    assert len(lots) == 2                                                    # deduplicated + UNKNOWN
    p = table(db, "fct_production", ["report_id", "sku"])
    assert p.loc[("L01-20260202-A", "PF-24G"), "started_after_changeover"] == 1
    assert p.loc[("L01-20260202-A", "PF-18G"), "started_after_changeover"] == 0


def test_unclassified_stop_is_an_availability_loss(db):
    e = pd.read_sql("SELECT reason_code, loss_bucket FROM fct_downtime_events WHERE report_id = 'L03-20250707-B'", db)
    assert dict(zip(e["reason_code"], e["loss_bucket"])) == {
        "BRK": "Planned stop", "CO": "Availability loss", "UNK": "Availability loss", "JAM": "Minor stop"}
