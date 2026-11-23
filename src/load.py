"""Load step: save the raw extract as received (JSON lines + CSV) and load it into raw_* / ref_* tables."""
from __future__ import annotations

import json
import logging
import sqlite3
from pathlib import Path

import pandas as pd

from src.config import MINOR_STOP_THRESHOLD_MIN, SMED_START, WORLD_CLASS_OEE

log = logging.getLogger(__name__)

REFERENCE_TABLES = {"lines", "products", "downtime_reasons"}
DOCUMENT_FILE = "mes_shift_reports.jsonl"


def parameters_table(start_date: str, end_date: str) -> pd.DataFrame:
    """Business rules as a one-row table, so the SQL models read them instead of hard-coding them."""
    return pd.DataFrame([{
        "period_start": start_date,
        "period_end": end_date,
        "minor_stop_threshold_min": MINOR_STOP_THRESHOLD_MIN,
        "world_class_oee": WORLD_CLASS_OEE,
        "smed_start": SMED_START,
        # a counter above this share of the theoretical maximum is a counter error, not production
        "max_rate_tolerance": 1.2,
    }])


def save_raw_files(docs: list[dict], tables: dict[str, pd.DataFrame], raw_dir: Path) -> None:
    raw_dir.mkdir(parents=True, exist_ok=True)
    with open(raw_dir / DOCUMENT_FILE, "w", encoding="utf-8") as fh:
        for d in docs:
            fh.write(json.dumps(d, ensure_ascii=False) + "\n")
    for name, df in tables.items():
        df.to_csv(raw_dir / f"erp_{name}.csv", index=False)


def read_documents(raw_dir: Path) -> list[dict]:
    with open(raw_dir / DOCUMENT_FILE, encoding="utf-8") as fh:
        return [json.loads(line) for line in fh]


def load_raw(mes_tables: dict[str, pd.DataFrame], erp_tables: dict[str, pd.DataFrame], db_path: Path,
             start_date: str, end_date: str) -> None:
    """Replace the database with a fresh copy of the flattened MES extract, the ERP extract and the rules."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    db_path.unlink(missing_ok=True)
    with sqlite3.connect(db_path) as conn:
        for name, df in mes_tables.items():
            df.to_sql(f"raw_{name}", conn, index=False)
            log.info("Loaded raw_%s (%d rows)", name, len(df))
        for name, df in erp_tables.items():
            prefix = "ref" if name in REFERENCE_TABLES else "raw"
            df.to_sql(f"{prefix}_{name}", conn, index=False)
            log.info("Loaded %s_%s (%d rows)", prefix, name, len(df))
        parameters_table(start_date, end_date).to_sql("ref_parameters", conn, index=False)
