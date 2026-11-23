"""Draw the README charts from the exported marts (run the pipeline first)."""
from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
EXPORTS = ROOT / "exports"
OUT = ROOT / "docs" / "images"
BLUE, ORANGE, AQUA, INK, MUTED, GRID, GRAY = "#2a78d6", "#eb6834", "#1baf7a", "#1f1f1f", "#6b6b6b", "#e6e6e6", "#b8b8b4"

plt.rcParams.update({
    "font.size": 11, "axes.edgecolor": GRID, "axes.labelcolor": MUTED, "xtick.color": MUTED,
    "ytick.color": MUTED, "axes.spines.top": False, "axes.spines.right": False, "axes.grid": True,
    "grid.color": GRID, "grid.linewidth": 0.8, "axes.titlesize": 13, "axes.titleweight": "bold",
    "axes.titlelocation": "left", "axes.axisbelow": True, "figure.dpi": 150, "savefig.bbox": "tight",
})


def oee_losses() -> None:
    """Where the plant's planned production time goes (the six big losses)."""
    d = pd.read_csv(EXPORTS / "mart_oee_losses.csv")
    d = d[d["line_id"] == "Plant"].sort_values("step_order").iloc[::-1]
    colors = [BLUE if f == "OEE" else ORANGE if f == "Availability" else AQUA if f == "Performance" else GRAY
              for f in d["oee_factor"]]
    fig, ax = plt.subplots(figsize=(9, 4.2))
    ax.barh(d["loss"], d["share_of_planned_time"], color=colors, height=0.62)
    for y, v in enumerate(d["share_of_planned_time"]):
        ax.text(v + 0.006, y, f"{v:.1%}", va="center", fontsize=10, color=INK)
    ax.set_xlim(0, 0.8)
    ax.xaxis.set_major_formatter(lambda v, _: f"{v:.0%}")
    oee = d.loc[d["oee_factor"] == "OEE", "share_of_planned_time"].iloc[0]
    ax.set_title(f"Where planned production time goes: plant OEE is {oee:.1%}")
    ax.set_xlabel("Share of planned production time, Jan 2025 - Oct 2026")
    ax.grid(axis="y", visible=False)
    handles = [plt.Rectangle((0, 0), 1, 1, color=c) for c in (ORANGE, AQUA, GRAY, BLUE)]
    ax.legend(handles, ["Availability loss", "Performance loss", "Quality loss", "Fully productive (OEE)"],
              loc="upper right", frameon=False, fontsize=9)
    fig.savefig(OUT / "oee_losses.png")
    plt.close(fig)


def oee_by_line() -> None:
    m = pd.read_csv(EXPORTS / "mart_oee_monthly.csv")
    g = m.groupby(["line_id", "line_name"], as_index=False)[["ideal_min_good", "planned_time_min"]].sum()
    g["oee"] = g["ideal_min_good"] / g["planned_time_min"]
    g = g.sort_values("oee")
    fig, ax = plt.subplots(figsize=(8, 3.6))
    ax.barh(g["line_id"] + "  " + g["line_name"], g["oee"], color=[ORANGE if i == 0 else BLUE for i in range(len(g))], height=0.6)
    for y, v in enumerate(g["oee"]):
        ax.text(v + 0.008, y, f"{v:.1%}", va="center", fontsize=10, color=INK)
    ax.axvline(0.85, color=INK, linewidth=1, linestyle="--")
    ax.text(0.853, len(g) - 0.45, "World class 85%", fontsize=9, color=MUTED)
    ax.set_xlim(0, 1)
    ax.xaxis.set_major_formatter(lambda v, _: f"{v:.0%}")
    ax.set_title("OEE by line: the old injection press is the outlier")
    ax.grid(axis="y", visible=False)
    fig.savefig(OUT / "oee_by_line.png")
    plt.close(fig)


def smed_changeovers() -> None:
    c = pd.read_csv(EXPORTS / "mart_changeovers_monthly.csv")
    c = c[c["smed_group"].isin(["Pilot", "Comparison"])]
    g = c.groupby(["month_start", "smed_group"], as_index=False)[["changeover_minutes", "changeovers"]].sum()
    g["avg"] = g["changeover_minutes"] / g["changeovers"]
    g["month"] = pd.to_datetime(g["month_start"])
    fig, ax = plt.subplots(figsize=(9, 4.2))
    for group, color, label in [("Pilot", BLUE, "Pilot lines (L01, L03)"), ("Comparison", ORANGE, "Comparison lines (L02, L04)")]:
        d = g[g["smed_group"] == group]
        ax.plot(d["month"], d["avg"], color=color, linewidth=2, marker="o", markersize=4)
        ax.annotate(label, (d["month"].iloc[-1], d["avg"].iloc[-1]), xytext=(8, 0), textcoords="offset points",
                    va="center", color=INK, fontsize=10)
    start = pd.Timestamp("2026-01-05")
    ax.axvline(start, color=MUTED, linestyle="--", linewidth=1)
    ax.text(start + pd.Timedelta(days=6), ax.get_ylim()[1] * 0.97, "SMED starts", color=MUTED, fontsize=9, va="top")
    ax.set_ylim(0, None)
    ax.set_title("SMED cut changeover time by ~40% on the pilot lines")
    ax.set_ylabel("Average changeover (minutes)")
    ax.grid(axis="x", visible=False)
    fig.savefig(OUT / "smed_changeovers.png")
    plt.close(fig)


def downtime_pareto() -> None:
    p = pd.read_csv(EXPORTS / "mart_downtime_pareto.csv").sort_values("hours")
    fig, ax = plt.subplots(figsize=(8.5, 4.4))
    vital = p["cumulative_share"] - p["share"] < 0.80
    ax.barh(p["reason"], p["hours"], color=[BLUE if v else GRAY for v in vital], height=0.65)
    for y, (h, cum) in enumerate(zip(p["hours"], p["cumulative_share"])):
        ax.text(h + 30, y, f"{h:,.0f} h  (cumulative {cum:.0%})", va="center", fontsize=9, color=INK)
    ax.set_xlim(0, p["hours"].max() * 1.5)
    words = {2: "Two", 3: "Three", 4: "Four", 5: "Five", 6: "Six"}
    ax.set_title(f"{words.get(int(vital.sum()), int(vital.sum()))} causes make {p.loc[vital, 'share'].sum():.0%} of unplanned downtime")
    ax.set_xlabel("Hours of unplanned downtime (stops of 5+ minutes), Jan 2025 - Oct 2026")
    ax.grid(axis="y", visible=False)
    fig.savefig(OUT / "downtime_pareto.png")
    plt.close(fig)


def reliability() -> None:
    r = pd.read_csv(EXPORTS / "mart_reliability.csv").sort_values("quarter")
    r = r[r["quarter"] != r["quarter"].max()]  # last quarter is incomplete
    fig, ax = plt.subplots(figsize=(9, 4.2))
    for line, d in r.groupby("line_id"):
        old = line == "L01"
        ax.plot(d["quarter"], d["mtbf_hours"], color=ORANGE if old else GRAY, linewidth=2.4 if old else 1.4,
                marker="o", markersize=4)
        ax.annotate(f"{line} {d['line_name'].iloc[0]}", (d["quarter"].iloc[-1], d["mtbf_hours"].iloc[-1]),
                    xytext=(8, 0), textcoords="offset points", va="center", fontsize=9, color=INK if old else MUTED)
    ax.set_ylim(0, None)
    ax.set_title("Line 1 breaks down every ~4 run hours, and it is getting worse")
    ax.set_ylabel("Mean time between failures (run hours)")
    ax.grid(axis="x", visible=False)
    fig.savefig(OUT / "reliability_mtbf.png")
    plt.close(fig)


def supplier_scrap() -> None:
    s = pd.read_csv(EXPORTS / "mart_scrap_by_supplier.csv")
    s = s[(s["process"] == "Injection molding") & ~s["supplier"].str.startswith("Unknown")].sort_values("scrap_rate")
    fig, ax = plt.subplots(figsize=(8, 2.8))
    ax.barh(s["supplier"], s["scrap_rate"] - s["splay_rate"], color=BLUE, height=0.55, label="Other defects")
    ax.barh(s["supplier"], s["splay_rate"], left=s["scrap_rate"] - s["splay_rate"], color=ORANGE, height=0.55,
            label="Splay / bubbles (moisture)", edgecolor="white", linewidth=2)
    for y, (v, price, ppm) in enumerate(zip(s["scrap_rate"], s["avg_price_gtq_per_kg"], s["avg_moisture_ppm"])):
        ax.text(v + 0.001, y, f"{v:.1%} scrap  |  Q{price:.2f}/kg  |  {ppm:.0f} ppm moisture", va="center", fontsize=9, color=INK)
    ax.set_xlim(0, s["scrap_rate"].max() * 2.1)
    ax.xaxis.set_major_formatter(lambda v, _: f"{v:.0%}")
    ax.set_title("Wetter resin from the cheaper supplier nearly doubles injection scrap")
    ax.legend(loc="upper left", bbox_to_anchor=(0, -0.12), ncol=2, frameon=False, fontsize=9)
    ax.grid(axis="y", visible=False)
    fig.savefig(OUT / "supplier_scrap.png")
    plt.close(fig)


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    oee_losses()
    oee_by_line()
    smed_changeovers()
    downtime_pareto()
    reliability()
    supplier_scrap()
    print(f"Charts written to {OUT.relative_to(ROOT)}")
