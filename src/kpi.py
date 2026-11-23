"""KPI calculations for the app: read the warehouse, filter by date and line, and aggregate correctly.

Ratios are always recomputed from summed numerators and denominators (never averaged), so any filter
combination gives the same answer as the SQL marts.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pandas as pd

SHIFT_COLUMNS = """report_id, shift_date, month_start, shift, line_id, line_name, process, planned_time_min,
    run_time_min, availability_loss_min, breakdown_min, changeover_min, minor_stop_min, breakdowns, changeovers,
    total_units, good_units, scrap_units, ideal_min_total, ideal_min_good, scrap_cost_gtq, lost_margin_gtq"""


def load_tables(db_path: Path) -> dict[str, pd.DataFrame]:
    """Shift-level OEE, downtime events and scrap by defect, with dates parsed."""
    with sqlite3.connect(db_path) as conn:
        shifts = pd.read_sql_query(f"SELECT {SHIFT_COLUMNS} FROM mart_shift_detail", conn)
        events = pd.read_sql_query(
            """SELECT line_id, shift_date, reason, category, loss_bucket, duration_min
               FROM fct_downtime_events WHERE loss_bucket <> 'Planned stop'""", conn)
        scrap = pd.read_sql_query(
            """SELECT r.line_id, r.shift_date, s.defect, s.scrap_units, s.scrap_units * p.unit_cost_gtq AS scrap_cost_gtq
               FROM stg_scrap s JOIN stg_shift_reports r USING (report_id) JOIN dim_product p USING (sku)""", conn)
    for df in (shifts, events, scrap):
        df["shift_date"] = pd.to_datetime(df["shift_date"])
    return {"shifts": shifts, "events": events, "scrap": scrap}


def filter_frame(df: pd.DataFrame, lines: list[str], start, end) -> pd.DataFrame:
    mask = df["line_id"].isin(lines) & df["shift_date"].between(pd.Timestamp(start), pd.Timestamp(end))
    return df[mask]


def oee_components(df: pd.DataFrame) -> dict[str, float]:
    """Availability, performance, quality and OEE from summed minutes and units."""
    planned, run = df["planned_time_min"].sum(), df["run_time_min"].sum()
    ideal_total, ideal_good = df["ideal_min_total"].sum(), df["ideal_min_good"].sum()
    total, good = df["total_units"].sum(), df["good_units"].sum()

    def ratio(a, b):
        return float(a / b) if b else float("nan")

    return {"availability": ratio(run, planned), "performance": ratio(ideal_total, run),
            "quality": ratio(good, total), "oee": ratio(ideal_good, planned)}


def summary(df: pd.DataFrame) -> dict[str, float]:
    out = oee_components(df)
    out.update({
        "good_units": float(df["good_units"].sum()),
        "scrap_rate": float(df["scrap_units"].sum() / df["total_units"].sum()) if df["total_units"].sum() else float("nan"),
        "scrap_cost_gtq": float(df["scrap_cost_gtq"].sum()),
        "unplanned_downtime_h": float(df["availability_loss_min"].sum() / 60),
        "lost_margin_gtq": float(df["lost_margin_gtq"].sum()),
        "mtbf_h": float(df["run_time_min"].sum() / 60 / df["breakdowns"].sum()) if df["breakdowns"].sum() else float("nan"),
    })
    return out


def oee_by(df: pd.DataFrame, key: str) -> pd.DataFrame:
    """OEE components grouped by any column (line, month, shift...)."""
    rows = [{key: k, **oee_components(g)} for k, g in df.groupby(key)]
    return pd.DataFrame(rows, columns=[key, "availability", "performance", "quality", "oee"])


def oee_trend(df: pd.DataFrame) -> pd.DataFrame:
    """Monthly OEE, one column per line (wide format for a line chart)."""
    rows = [{"month": pd.Timestamp(m), "line_id": line, "oee": oee_components(g)["oee"]}
            for (m, line), g in df.groupby(["month_start", "line_id"])]
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows).pivot(index="month", columns="line_id", values="oee")


def six_big_losses(df: pd.DataFrame) -> pd.DataFrame:
    """Planned production time split into the six losses plus fully productive time (hours and share)."""
    planned = df["planned_time_min"].sum()
    parts = {
        "Breakdowns": df["breakdown_min"].sum(),
        "Changeovers": df["changeover_min"].sum(),
        "Other stops": (df["availability_loss_min"] - df["breakdown_min"] - df["changeover_min"]).sum(),
        "Minor stops (< 5 min)": df["minor_stop_min"].sum(),
        "Reduced speed": (df["run_time_min"] - df["minor_stop_min"] - df["ideal_min_total"]).sum(),
        "Scrap": (df["ideal_min_total"] - df["ideal_min_good"]).sum(),
        "Fully productive (OEE)": df["ideal_min_good"].sum(),
    }
    out = pd.DataFrame({"loss": list(parts), "hours": [v / 60 for v in parts.values()]})
    out["share"] = [v / planned if planned else float("nan") for v in parts.values()]
    return out


def downtime_pareto(events: pd.DataFrame) -> pd.DataFrame:
    """Unplanned stops of 5+ minutes by reason, largest first, with the cumulative share."""
    d = events[events["loss_bucket"] == "Availability loss"]
    p = (d.groupby(["reason", "category"], as_index=False)
          .agg(stops=("duration_min", "size"), hours=("duration_min", "sum")))
    p["hours"] = p["hours"] / 60
    p = p.sort_values("hours", ascending=False).reset_index(drop=True)
    p["cumulative_share"] = p["hours"].cumsum() / p["hours"].sum()
    return p


def scrap_by_defect(scrap: pd.DataFrame) -> pd.DataFrame:
    return (scrap.groupby("defect", as_index=False)[["scrap_units", "scrap_cost_gtq"]].sum()
                 .sort_values("scrap_cost_gtq", ascending=False).reset_index(drop=True))
