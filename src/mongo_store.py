"""MongoDB layer: land the MES shift documents and flatten them into rows with aggregation pipelines.

The MES writes one JSON document per line and shift. Documents are nested (production by SKU, scrap by
defect, a list of stops) and their layout changed with a firmware update:

    schema v1                                    schema v2
    line_name: "Línea 1"                         line: "L01"
    production[].good: "180,000" (text)          production[].good_units: 180000
    production[].defects: {"Flash": 12, ...}     production[].scrap: [{defect: "Flash", units: 12}, ...]
    stops[]: {code, started, minutes}            downtime_events[]: {reason_code, start, end}

The aggregation pipelines below only *reshape* the documents (unwind arrays, line up the v1 and v2 field
names). They keep every value exactly as received; cleaning happens in the SQL staging layer, so the raw
layer is still an honest copy of the source.

If MongoDB is not available the same flattening runs in Python (`flatten_documents`) on the local
document file. The test suite checks that both paths return identical rows.
"""
from __future__ import annotations

import logging

import pandas as pd

log = logging.getLogger(__name__)

COLLECTION = "shift_reports"

REPORT_COLUMNS = ["report_id", "ingested_at", "schema_version", "line_raw", "shift_date", "shift", "shift_start",
                  "shift_minutes", "supervisor", "operators", "resin_lot"]
PRODUCTION_COLUMNS = ["report_id", "ingested_at", "item_seq", "sku_raw", "good_raw"]
SCRAP_COLUMNS = ["report_id", "ingested_at", "item_seq", "defect_seq", "sku_raw", "defect_raw", "units_raw"]
DOWNTIME_COLUMNS = ["report_id", "ingested_at", "event_seq", "reason_raw", "start_raw", "end_raw", "minutes_raw",
                    "from_sku", "to_sku"]

_SORT = {"report_id": 1, "ingested_at": 1}

PIPELINES: dict[str, list[dict]] = {
    # One row per document (shift report)
    "shift_reports": [
        {"$project": {
            "_id": 0, "report_id": 1, "ingested_at": 1, "schema_version": 1,
            "line_raw": {"$ifNull": ["$line", "$line_name"]},
            "shift_date": 1, "shift": 1, "shift_start": 1, "shift_minutes": 1,
            "supervisor": "$crew.supervisor", "operators": "$crew.operators", "resin_lot": 1,
        }},
        {"$sort": _SORT},
    ],
    # One row per document x SKU
    "production": [
        {"$unwind": {"path": "$production", "includeArrayIndex": "item_seq"}},
        {"$project": {
            "_id": 0, "report_id": 1, "ingested_at": 1, "item_seq": 1,
            "sku_raw": "$production.sku",
            "good_raw": {"$ifNull": ["$production.good_units", "$production.good"]},
        }},
        {"$sort": {**_SORT, "item_seq": 1}},
    ],
    # One row per document x SKU x defect. v1 stores defects as an object -> $objectToArray
    "scrap": [
        {"$unwind": {"path": "$production", "includeArrayIndex": "item_seq"}},
        {"$project": {
            "_id": 0, "report_id": 1, "ingested_at": 1, "item_seq": 1,
            "sku_raw": "$production.sku",
            "defects": {"$ifNull": [
                "$production.scrap",
                {"$map": {"input": {"$objectToArray": {"$ifNull": ["$production.defects", {}]}},
                          "as": "d", "in": {"defect": "$$d.k", "units": "$$d.v"}}},
            ]},
        }},
        {"$unwind": {"path": "$defects", "includeArrayIndex": "defect_seq"}},
        {"$project": {
            "report_id": 1, "ingested_at": 1, "item_seq": 1, "defect_seq": 1, "sku_raw": 1,
            "defect_raw": "$defects.defect", "units_raw": "$defects.units",
        }},
        {"$sort": {**_SORT, "item_seq": 1, "defect_seq": 1}},
    ],
    # One row per stop. v1 calls the list `stops`, v2 `downtime_events`
    "downtime_events": [
        {"$project": {
            "_id": 0, "report_id": 1, "ingested_at": 1,
            "events": {"$concatArrays": [{"$ifNull": ["$downtime_events", []]}, {"$ifNull": ["$stops", []]}]},
        }},
        {"$unwind": {"path": "$events", "includeArrayIndex": "event_seq"}},
        {"$project": {
            "report_id": 1, "ingested_at": 1, "event_seq": 1,
            "reason_raw": {"$ifNull": ["$events.reason_code", "$events.code"]},
            "start_raw": {"$ifNull": ["$events.start", "$events.started"]},
            "end_raw": "$events.end", "minutes_raw": "$events.minutes",
            "from_sku": "$events.from_sku", "to_sku": "$events.to_sku",
        }},
        {"$sort": {**_SORT, "event_seq": 1}},
    ],
}
COLUMNS = {"shift_reports": REPORT_COLUMNS, "production": PRODUCTION_COLUMNS, "scrap": SCRAP_COLUMNS,
           "downtime_events": DOWNTIME_COLUMNS}


class MongoUnavailable(RuntimeError):
    pass


def connect(uri: str, timeout_ms: int = 2_000):
    """Return a connected MongoClient, or raise MongoUnavailable (driver missing or server unreachable)."""
    try:
        from pymongo import MongoClient
        from pymongo.errors import PyMongoError
    except ImportError as exc:  # pragma: no cover - depends on the environment
        raise MongoUnavailable("pymongo is not installed") from exc
    client = MongoClient(uri, serverSelectionTimeoutMS=timeout_ms)
    try:
        client.admin.command("ping")
    except PyMongoError as exc:
        client.close()
        raise MongoUnavailable(f"cannot reach MongoDB at {uri}: {exc.__class__.__name__}") from exc
    return client


def land_documents(client, db_name: str, docs: list[dict]) -> int:
    """Replace the shift_reports collection with the new extract (insert copies: pymongo adds _id in place)."""
    coll = client[db_name][COLLECTION]
    coll.drop()
    coll.insert_many([dict(d) for d in docs], ordered=False)
    coll.create_index([("report_id", 1), ("ingested_at", 1)])
    return coll.count_documents({})


def _frame(rows: list[dict], name: str) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=COLUMNS[name])


def flatten_with_mongo(client, db_name: str) -> dict[str, pd.DataFrame]:
    coll = client[db_name][COLLECTION]
    return {name: _frame(list(coll.aggregate(pipeline, allowDiskUse=True)), name)
            for name, pipeline in PIPELINES.items()}


def _ifnull(*values):
    """Same rule as MongoDB's $ifNull: the first value that is neither missing nor null."""
    for v in values:
        if v is not None:
            return v
    return None


def flatten_documents(docs: list[dict]) -> dict[str, pd.DataFrame]:
    """Python twin of PIPELINES, used when MongoDB is not available."""
    reports, production, scrap, downtime = [], [], [], []
    for d in docs:
        key = {"report_id": d.get("report_id"), "ingested_at": d.get("ingested_at")}
        crew = d.get("crew") or {}
        reports.append({**key, "schema_version": d.get("schema_version"), "line_raw": _ifnull(d.get("line"), d.get("line_name")),
                        "shift_date": d.get("shift_date"), "shift": d.get("shift"), "shift_start": d.get("shift_start"),
                        "shift_minutes": d.get("shift_minutes"), "supervisor": crew.get("supervisor"),
                        "operators": crew.get("operators"), "resin_lot": d.get("resin_lot")})
        for i, p in enumerate(d.get("production") or []):
            production.append({**key, "item_seq": i, "sku_raw": p.get("sku"),
                               "good_raw": _ifnull(p.get("good_units"), p.get("good"))})
            defects = p.get("scrap")
            if defects is None:
                defects = [{"defect": k, "units": v} for k, v in (p.get("defects") or {}).items()]
            for j, s in enumerate(defects):
                scrap.append({**key, "item_seq": i, "defect_seq": j, "sku_raw": p.get("sku"),
                              "defect_raw": s.get("defect"), "units_raw": s.get("units")})
        for k, e in enumerate((d.get("downtime_events") or []) + (d.get("stops") or [])):
            downtime.append({**key, "event_seq": k, "reason_raw": _ifnull(e.get("reason_code"), e.get("code")),
                             "start_raw": _ifnull(e.get("start"), e.get("started")), "end_raw": e.get("end"),
                             "minutes_raw": e.get("minutes"), "from_sku": e.get("from_sku"), "to_sku": e.get("to_sku")})
    out = {"shift_reports": reports, "production": production, "scrap": scrap, "downtime_events": downtime}
    sort_keys = {"shift_reports": ["report_id", "ingested_at"], "production": ["report_id", "ingested_at", "item_seq"],
                 "scrap": ["report_id", "ingested_at", "item_seq", "defect_seq"],
                 "downtime_events": ["report_id", "ingested_at", "event_seq"]}
    return {name: _frame(rows, name).sort_values(sort_keys[name], kind="stable").reset_index(drop=True)
            for name, rows in out.items()}


def extract_raw_tables(docs: list[dict], uri: str, db_name: str, require_mongo: bool = False) -> tuple[dict[str, pd.DataFrame], str]:
    """Land the documents in MongoDB and flatten them there; fall back to Python if MongoDB is unavailable.

    Returns (raw tables, source) where source is "mongodb" or "local".
    """
    try:
        client = connect(uri)
    except MongoUnavailable as exc:
        if require_mongo:
            raise
        log.warning("MongoDB not available (%s): flattening the local document file in Python instead", exc)
        return flatten_documents(docs), "local"
    with client:
        n = land_documents(client, db_name, docs)
        log.info("Landed %s documents in MongoDB %s.%s", f"{n:,}", db_name, COLLECTION)
        tables = flatten_with_mongo(client, db_name)
    return tables, "mongodb"
