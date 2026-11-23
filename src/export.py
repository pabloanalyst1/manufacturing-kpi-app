"""Export step: write every mart_* table to CSV for the dashboard (Tableau / Looker Studio) and the app."""
from __future__ import annotations

import logging
import sqlite3
from pathlib import Path

import pandas as pd

log = logging.getLogger(__name__)


def export_marts(db_path: Path, export_dir: Path) -> list[Path]:
    export_dir.mkdir(parents=True, exist_ok=True)
    written = []
    with sqlite3.connect(db_path) as conn:
        marts = [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name LIKE 'mart_%' ORDER BY name")]
        for name in marts:
            path = export_dir / f"{name}.csv"
            df = pd.read_sql_query(f"SELECT * FROM {name}", conn)
            df.to_csv(path, index=False)
            written.append(path)
            log.info("Exported %s (%d rows)", path.name, len(df))
    return written
