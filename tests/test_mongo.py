"""MongoDB layer: the Python fallback flattens both schema versions, matches the aggregation pipelines
row for row (when a MongoDB server is available), and the pipeline falls back cleanly without one."""
import copy
import os

import pandas as pd
import pytest

from src.mongo_store import (MongoUnavailable, connect, extract_raw_tables, flatten_documents, flatten_with_mongo,
                             land_documents)

V1 = {"report_id": "L03-20250707-B", "schema_version": 1, "line_name": "Línea 3", "shift_date": "2025-07-07",
      "shift": "B", "shift_start": "2025-07-07T14:00:00", "shift_minutes": 480,
      "crew": {"supervisor": "S01", "operators": 4},
      "production": [{"sku": "BT-600W", "good": "100,000", "defects": {"Thin wall": 800, "Leaker": 200}}],
      "stops": [{"code": "SETUP", "started": "07/07/2025 15:00", "minutes": 45.5, "from_sku": "BT-1500", "to_sku": "BT-600W"}],
      "ingested_at": "2025-07-07T22:07:00"}
V2 = {"report_id": "L01-20260202-A", "schema_version": 2, "line": "L01", "shift_date": "2026-02-02", "shift": "A",
      "shift_start": "2026-02-02T06:00:00", "shift_minutes": 480, "crew": {"supervisor": "S02", "operators": 5},
      "resin_lot": "PET-1",
      "production": [{"sku": "PF-18G", "good_units": 48000, "scrap": [{"defect": "Flash", "units": 500}]}],
      "downtime_events": [{"reason_code": "MECH", "start": "2026-02-02T07:00:00", "end": "2026-02-02T07:40:00"}],
      "ingested_at": "2026-02-02T14:07:00"}


def test_python_flattening_lines_up_v1_and_v2():
    t = flatten_documents([V2, V1])
    r = t["shift_reports"].set_index("report_id")
    assert r.loc["L03-20250707-B", "line_raw"] == "Línea 3" and r.loc["L01-20260202-A", "line_raw"] == "L01"
    assert pd.isna(r.loc["L03-20250707-B", "resin_lot"])
    p = t["production"].set_index("report_id")["good_raw"]
    assert p["L03-20250707-B"] == "100,000" and p["L01-20260202-A"] == 48000      # raw values kept as received
    s = t["scrap"]
    assert s[s["report_id"] == "L03-20250707-B"]["defect_raw"].tolist() == ["Thin wall", "Leaker"]
    d = t["downtime_events"].set_index("report_id")
    assert d.loc["L03-20250707-B", "reason_raw"] == "SETUP" and d.loc["L03-20250707-B", "minutes_raw"] == 45.5
    assert d.loc["L01-20260202-A", "end_raw"] == "2026-02-02T07:40:00"


def test_falls_back_to_python_when_mongo_is_unreachable():
    tables, source = extract_raw_tables([V1, V2], "mongodb://localhost:1", "test_db")
    assert source == "local" and len(tables["shift_reports"]) == 2
    with pytest.raises(MongoUnavailable):
        extract_raw_tables([V1, V2], "mongodb://localhost:1", "test_db", require_mongo=True)


@pytest.fixture(scope="module")
def mongo_client():
    uri = os.environ.get("MONGO_URI")
    if not uri:
        pytest.skip("MONGO_URI not set (runs in CI against a MongoDB service container)")
    try:
        client = connect(uri)
    except MongoUnavailable as exc:
        pytest.skip(str(exc))
    yield client
    client.drop_database("plant_mes_test")
    client.close()


def test_mongo_aggregation_matches_python(mongo_client, small_extract):
    docs = small_extract[0]
    land_documents(mongo_client, "plant_mes_test", copy.deepcopy(docs))
    from_mongo = flatten_with_mongo(mongo_client, "plant_mes_test")
    from_python = flatten_documents(docs)
    for name in from_python:
        a = from_mongo[name].astype(object).where(from_mongo[name].notna(), None).reset_index(drop=True)
        b = from_python[name].astype(object).where(from_python[name].notna(), None).reset_index(drop=True)
        assert len(a) == len(b), name
        pd.testing.assert_frame_equal(a, b, check_dtype=False, obj=name)


def test_pipeline_lands_and_flattens_in_mongo(mongo_client):
    tables, source = extract_raw_tables([V1, V2], os.environ["MONGO_URI"], "plant_mes_test", require_mongo=True)
    assert source == "mongodb"
    assert sorted(tables["scrap"]["defect_raw"]) == ["Flash", "Leaker", "Thin wall"]
