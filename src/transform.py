"""Transform step: run the SQL models in order (staging -> dimensions -> facts -> marts)."""
from __future__ import annotations

import logging
import sqlite3
from pathlib import Path

log = logging.getLogger(__name__)


def run_sql_models(db_path: Path, sql_dir: Path) -> list[str]:
    """Execute every .sql file directly in `sql_dir` in filename order. Returns the files run."""
    files = sorted(sql_dir.glob("*.sql"))
    with sqlite3.connect(db_path) as conn:
        for path in files:
            conn.executescript(path.read_text(encoding="utf-8"))
            log.info("Ran %s", path.name)
    return [p.name for p in files]
