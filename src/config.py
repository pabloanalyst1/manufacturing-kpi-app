"""Project settings: study period, OEE business rules, improvement program and paths.

Business rules the SQL models need (minor-stop threshold, SMED start, world-class target) are also loaded
into reference tables (`ref_parameters`, `ref_downtime_reasons`), so the SQL never hard-codes them.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Period covered by the MES extract (shift dates)
START_DATE = "2025-01-01"
END_DATE = "2026-10-31"

# Three 8-hour shifts, Monday to Saturday. Sundays and plant holidays are not scheduled.
SHIFTS = {"A": 6, "B": 14, "C": 22}  # shift letter -> start hour
SHIFT_MINUTES = 480
PLANT_HOLIDAYS = (
    "2025-01-01", "2025-04-17", "2025-04-18", "2025-05-01", "2025-09-15", "2025-10-20", "2025-12-24",
    "2025-12-25", "2025-12-31", "2026-01-01", "2026-04-02", "2026-04-03", "2026-05-01", "2026-09-15",
    "2026-10-20",
)

# OEE rules
# Unplanned stops shorter than this are "minor stops": a performance loss, not an availability loss
# (the usual OEE convention, because they are too short to be logged and fixed as a breakdown).
MINOR_STOP_THRESHOLD_MIN = 5
WORLD_CLASS_OEE = 0.85

# SMED (quick changeover) program: piloted on one injection and one blow-molding line.
# The other line of each process is the comparison group.
SMED_START = "2026-01-05"
SMED_PILOT_LINES = ("L01", "L03")
SMED_COMPARISON_LINES = ("L02", "L04")

# Resin supply disruption (port congestion): material shortages in this window
SUPPLY_DISRUPTION = ("2025-08-11", "2025-09-20")


@dataclass
class PipelineConfig:
    seed: int = 42
    start_date: str = START_DATE
    end_date: str = END_DATE
    raw_dir: Path = ROOT / "data" / "raw"
    db_path: Path = ROOT / "data" / "warehouse.db"
    sql_dir: Path = ROOT / "sql"
    export_dir: Path = ROOT / "exports"
    mongo_uri: str = field(default_factory=lambda: os.environ.get("MONGO_URI", "mongodb://localhost:27017"))
    mongo_db: str = "plant_mes"
    require_mongo: bool = False
