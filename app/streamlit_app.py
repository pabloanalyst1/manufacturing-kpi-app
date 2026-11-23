"""Plant KPI app: OEE, losses, downtime and scrap with date and line filters.

Run the pipeline first, then:
    streamlit run app/streamlit_app.py
Set KPI_DB_PATH to point the app at another warehouse file.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src import kpi  # noqa: E402
from src.config import PipelineConfig, WORLD_CLASS_OEE  # noqa: E402

st.set_page_config(page_title="Plant KPIs · Envases del Pacífico", layout="wide")


def fmt(df, formats: dict):
    """Format columns as text for display (keeps the app free of extra styling dependencies)."""
    out = df.copy()
    for col, f in formats.items():
        out[col] = out[col].map(f.format)
    return out


@st.cache_data
def load(db_path: str):
    return kpi.load_tables(Path(db_path))


db_path = Path(os.environ.get("KPI_DB_PATH", PipelineConfig().db_path))
if not db_path.exists():
    st.error("The warehouse does not exist yet. Run `python run_pipeline.py` first, then reload this page.")
    st.stop()

data = load(str(db_path))
shifts_all = data["shifts"]

# Filters ------------------------------------------------------------------------------------------
st.sidebar.header("Filters")
min_day, max_day = shifts_all["shift_date"].min().date(), shifts_all["shift_date"].max().date()
dates = st.sidebar.date_input("Shift dates", value=(min_day, max_day), min_value=min_day, max_value=max_day)
start, end = (dates if isinstance(dates, (list, tuple)) and len(dates) == 2 else (min_day, max_day))
line_names = shifts_all.drop_duplicates("line_id").set_index("line_id")["line_name"].sort_index()
lines = st.sidebar.multiselect("Lines", options=list(line_names.index), default=list(line_names.index),
                               format_func=lambda x: f"{x} · {line_names[x]}")
if not lines:
    st.warning("Select at least one line.")
    st.stop()

shifts = kpi.filter_frame(shifts_all, lines, start, end)
events = kpi.filter_frame(data["events"], lines, start, end)
scrap = kpi.filter_frame(data["scrap"], lines, start, end)
if shifts.empty:
    st.warning("No shifts in this selection.")
    st.stop()

# Headline KPIs -----------------------------------------------------------------------------------------
st.title("Envases del Pacífico · Plant KPIs")
st.caption(f"{len(shifts):,} line-shifts from {start} to {end}. Synthetic data; see the README for definitions.")

s = kpi.summary(shifts)
c = st.columns(4)
c[0].metric("OEE", f"{s['oee']:.1%}", f"{s['oee'] - WORLD_CLASS_OEE:+.1%} vs world class", delta_color="normal")
c[1].metric("Availability", f"{s['availability']:.1%}")
c[2].metric("Performance", f"{s['performance']:.1%}")
c[3].metric("Quality", f"{s['quality']:.2%}")
c = st.columns(4)
c[0].metric("Good units", f"{s['good_units'] / 1e6:,.1f} M")
c[1].metric("Scrap cost", f"Q{s['scrap_cost_gtq']:,.0f}")
c[2].metric("Unplanned downtime", f"{s['unplanned_downtime_h']:,.0f} h")
c[3].metric("MTBF", f"{s['mtbf_h']:.1f} run h")

overview, losses, downtime, quality = st.tabs(["OEE", "Six big losses", "Downtime", "Scrap"])

with overview:
    st.subheader("Monthly OEE by line")
    st.line_chart(kpi.oee_trend(shifts))
    st.subheader("OEE components by line")
    by_line = kpi.oee_by(shifts, "line_id")
    st.dataframe(fmt(by_line, {col: "{:.1%}" for col in ["availability", "performance", "quality", "oee"]}), hide_index=True)
    st.subheader("OEE by shift")
    st.bar_chart(kpi.oee_by(shifts, "shift").set_index("shift")["oee"])

with losses:
    st.subheader("Where planned production time goes")
    big = kpi.six_big_losses(shifts)
    st.bar_chart(big.set_index("loss")["share"])
    st.dataframe(fmt(big, {"hours": "{:,.0f}", "share": "{:.1%}"}), hide_index=True)
    st.caption(f"Margin lost versus 100% OEE in this selection: Q{s['lost_margin_gtq']:,.0f}")

with downtime:
    st.subheader("Pareto of unplanned downtime (stops of 5+ minutes)")
    pareto = kpi.downtime_pareto(events)
    st.bar_chart(pareto.set_index("reason")["hours"])
    st.dataframe(fmt(pareto, {"hours": "{:,.0f}", "cumulative_share": "{:.0%}"}), hide_index=True)

with quality:
    st.subheader("Scrap by defect")
    defects = kpi.scrap_by_defect(scrap)
    st.bar_chart(defects.set_index("defect")["scrap_cost_gtq"])
    st.dataframe(fmt(defects, {"scrap_units": "{:,.0f}", "scrap_cost_gtq": "Q{:,.0f}"}), hide_index=True)
    st.metric("Scrap rate", f"{s['scrap_rate']:.2%}")
