"""Data quality checks. Each check is a SQL query that returns the number of bad rows (0 = pass).

If any check fails the pipeline stops before exporting, so the dashboard never shows bad data.
"""
from __future__ import annotations

import logging
import sqlite3
from pathlib import Path

log = logging.getLogger(__name__)

CHECKS: list[tuple[str, str]] = [
    ("Every shift report is either staged or rejected (after keeping the final copy)",
     """SELECT ABS((SELECT COUNT(DISTINCT TRIM(report_id)) FROM raw_shift_reports)
                - (SELECT COUNT(*) FROM stg_shift_reports) - (SELECT COUNT(*) FROM stg_rejected_shift_reports))"""),
    ("Rejected shift reports are below 0.5% of the extract",
     """SELECT CASE WHEN 1.0 * (SELECT COUNT(*) FROM stg_rejected_shift_reports)
                       / (SELECT COUNT(*) FROM stg_shift_reports) > 0.005 THEN 1 ELSE 0 END"""),
    ("Every shift report maps to a known line after cleaning the line id",
     "SELECT COUNT(*) FROM stg_shift_reports WHERE line_id NOT IN (SELECT line_id FROM dim_line)"),
    ("One report per line, date and shift",
     "SELECT COUNT(*) - COUNT(DISTINCT line_id || shift_date || shift) FROM stg_shift_reports"),
    ("Every SKU is known and runs on a line of its process",
     """SELECT COUNT(*) FROM stg_production p
        JOIN stg_shift_reports r ON r.report_id = p.report_id
        JOIN dim_line l ON l.line_id = r.line_id
        LEFT JOIN dim_product d ON d.sku = p.sku
        WHERE d.sku IS NULL OR d.process <> l.process"""),
    ("Unclassified stops are below 1% of all stops",
     """SELECT CASE WHEN AVG(CASE WHEN reason_code = 'UNK' THEN 1.0 ELSE 0 END) > 0.01 THEN 1 ELSE 0 END
        FROM fct_downtime_events"""),
    ("Stops have a positive duration and fall inside their shift",
     """SELECT COUNT(*) FROM stg_downtime_events e JOIN stg_shift_reports r USING (report_id)
        WHERE e.duration_min <= 0 OR e.start_ts < r.shift_start OR e.end_ts > r.shift_end"""),
    ("Stops in the same shift do not overlap (1 minute tolerance for v1 timestamps)",
     """SELECT COUNT(*) FROM (
            SELECT start_ts, LAG(end_ts) OVER (PARTITION BY report_id ORDER BY start_ts, end_ts) AS prev_end
            FROM stg_downtime_events)
        WHERE (JULIANDAY(prev_end) - JULIANDAY(start_ts)) * 1440 > 1"""),
    ("Joins do not duplicate or drop shifts (fact rows = staged reports)",
     "SELECT ABS((SELECT COUNT(*) FROM fct_shift_oee) - (SELECT COUNT(*) FROM stg_shift_reports))"),
    ("Units reconcile: fact totals = staged production",
     """SELECT ABS((SELECT SUM(good_units + scrap_units) FROM stg_production) - (SELECT SUM(total_units) FROM fct_shift_oee))
             + ABS((SELECT SUM(scrap_units) FROM stg_scrap) - (SELECT SUM(scrap_units) FROM fct_shift_oee))"""),
    ("Every shift has planned time and output",
     "SELECT COUNT(*) FROM fct_shift_oee WHERE planned_time_min <= 0 OR total_units <= 0"),
    ("OEE components are valid (A and Q in 0-1, performance at most 105% of the ideal rate)",
     """SELECT COUNT(*) FROM fct_shift_oee
        WHERE availability NOT BETWEEN 0 AND 1 OR quality NOT BETWEEN 0 AND 1 OR performance NOT BETWEEN 0 AND 1.05"""),
    ("Resin lots are known for lines that use resin (unscanned lots below 1%)",
     """SELECT (SELECT COUNT(*) FROM fct_shift_oee f LEFT JOIN dim_resin_lot r ON r.lot_id = f.resin_lot
                WHERE f.process <> 'Blow molding' AND r.lot_id IS NULL)
             + (SELECT CASE WHEN AVG(CASE WHEN resin_lot = 'UNKNOWN' THEN 1.0 ELSE 0 END) > 0.01 THEN 1 ELSE 0 END
                FROM fct_shift_oee WHERE process <> 'Blow molding')"""),
    ("Plant OEE is plausible (40%-90%)",
     """SELECT CASE WHEN SUM(ideal_min_good) / SUM(planned_time_min) NOT BETWEEN 0.40 AND 0.90 THEN 1 ELSE 0 END
        FROM fct_shift_oee"""),
]


class DataQualityError(RuntimeError):
    pass


def run_quality_checks(db_path: Path) -> dict[str, int]:
    """Run every check, log the result and raise if any check fails."""
    results: dict[str, int] = {}
    with sqlite3.connect(db_path) as conn:
        for name, sql in CHECKS:
            bad = int(conn.execute(sql).fetchone()[0] or 0)
            results[name] = bad
            log.info("%s %s%s", "PASS" if bad == 0 else "FAIL", name, "" if bad == 0 else f" ({bad} bad rows)")
    failed = [n for n, b in results.items() if b]
    if failed:
        raise DataQualityError(f"{len(failed)} data quality check(s) failed: {failed}")
    return results
