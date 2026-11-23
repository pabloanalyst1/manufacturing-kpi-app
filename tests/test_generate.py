"""The simulated extract is reproducible, consistent, and messy in the documented ways."""
import pandas as pd

from src.generate_data import LINE, PRODUCT, generate_all

WINDOW = {"start": "2025-06-01", "end": "2025-08-31"}  # spans the firmware update (schema v1 -> v2)


def test_same_seed_same_data():
    a_docs, a_tab = generate_all(seed=1, **WINDOW)
    b_docs, b_tab = generate_all(seed=1, **WINDOW)
    assert a_docs == b_docs
    pd.testing.assert_frame_equal(a_tab["resin_lots"], b_tab["resin_lots"])


def test_clean_extract_is_consistent():
    docs, tables = generate_all(seed=3, messy=False, **WINDOW)
    ids = [d["report_id"] for d in docs]
    assert len(ids) == len(set(ids))
    lots = set(tables["resin_lots"]["lot_id"])
    for d in docs:
        line = d.get("line") or f"L{int(d['line_name'].split()[-1]):02d}"
        process = LINE[line][2]
        assert all(PRODUCT[p["sku"]][2] == process for p in d["production"])  # SKUs run on the right process
        assert ("resin_lot" in d) == (process != "Blow molding")
        assert d.get("resin_lot", next(iter(lots))) in lots
        if d["schema_version"] == 2:
            start = pd.Timestamp(d["shift_start"])
            end = start + pd.Timedelta(minutes=d["shift_minutes"])
            for e in d["downtime_events"]:
                assert start <= pd.Timestamp(e["start"]) < pd.Timestamp(e["end"]) <= end
    assert {d["schema_version"] for d in docs} == {1, 2}


def test_messy_extract_has_the_issues_staging_fixes():
    docs, tables = generate_all(seed=5, **WINDOW)
    ids = [d["report_id"] for d in docs]
    assert len(ids) > len(set(ids))                                             # interim + final copies
    assert any(d.get("line", "L01") != d.get("line", "L01").strip().upper() or "-" in d.get("line", "")
               for d in docs)                                                   # line ids typed differently
    assert any(p["sku"] != p["sku"].strip().upper() for d in docs for p in d["production"])
    codes = [e.get("reason_code", e.get("code")) for d in docs for e in d.get("downtime_events", d.get("stops", []))]
    assert "???" in codes and "MECHANICAL" in codes                             # unclassified + legacy codes
    assert any(isinstance(p.get("good"), str) and "," in p["good"] for d in docs for p in d["production"])
    assert tables["resin_lots"]["lot_id"].duplicated().any()
    assert tables["resin_lots"]["supplier"].nunique() > 2                       # supplier spelled several ways


def _fingerprint(docs, tables) -> str:
    import hashlib
    import json
    payload = json.dumps(docs, sort_keys=True) + tables["resin_lots"].to_csv(index=False)
    return hashlib.sha256(payload.encode()).hexdigest()


def test_data_is_identical_on_every_machine():
    """Golden fingerprint of the default extract. If this fails on your machine, the simulated data (and the
    README numbers) differ there: the generator must only use platform-independent draws."""
    assert _fingerprint(*generate_all()) == "6aa720c4ccbf3ed14ef8aa2b9bdcd17b7c8103a39e342abb367d33e9a0bb191d"
