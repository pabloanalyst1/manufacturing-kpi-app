"""Synthetic MES and ERP extracts from a fictional PET packaging plant in Guatemala.

**Envases del Pacífico** (fictional) makes PET preforms, bottles and caps on five lines in Escuintla.
Each line's MES terminal sends one JSON document per shift to MongoDB: what was produced, what was
scrapped (by defect) and every stop. The ERP adds the resin lots and the reference data.

The data is simulated, but the mechanics behind it are realistic, so the analysis has real signal:

* **Availability.** Breakdowns follow a per-line failure rate. Line 1 is the oldest press and its failure
  rate keeps rising as it ages. Changeovers (mold / format changes) take 50-95 minutes. A resin supply
  disruption (port congestion, Aug-Sep 2025) causes long material shortages, and storms cause power cuts
  in the rainy season (May-October).
* **SMED program.** From January 2026 a quick-changeover program on lines L01 and L03 cuts changeover time
  by about 45% over eight weeks. L02 and L04 (same processes) are the comparison group.
* **Performance.** Every line runs below its ideal rate, and jams shorter than 5 minutes (minor stops) are
  frequent on the old press and the cap line. Lines run slower for the first hour after a changeover.
* **Quality.** Scrap depends on the process, the night shift, start-up after a changeover, humidity in the
  rainy season and the resin supplier: wetter resin from "Resinas del Golfo" causes splay / bubbles.
* **The MES documents changed format** when the terminals got a firmware update in 2025 (schema v1 -> v2),
  and the extract has the usual problems (see `make_messy`). The pipeline must clean all of it.

Same seed -> same data, so every number in the README is reproducible.
"""
from __future__ import annotations

import copy

import numpy as np
import pandas as pd

from src.config import (END_DATE, PLANT_HOLIDAYS, SHIFT_MINUTES, SHIFTS, SMED_COMPARISON_LINES, SMED_PILOT_LINES,
                        SMED_START, START_DATE, SUPPLY_DISRUPTION)

PROCESSES = ("Injection molding", "Blow molding", "Compression molding")

# line_id, line name, process, machine, install year, speed factor (share of ideal rate), failure multiplier,
# minor-stop multiplier, scrap multiplier, mean changeover minutes, v2 firmware date
LINES = [
    ("L01", "Injection 1", "Injection molding", "300 t preform injection press", 2011, 0.80, 1.8, 2.2, 1.20, 95, "2025-07-14"),
    ("L02", "Injection 2", "Injection molding", "300 t preform injection press", 2021, 0.90, 0.8, 0.8, 0.95, 90, "2025-04-07"),
    ("L03", "Blow molding 1", "Blow molding", "10-cavity rotary stretch blow molder", 2014, 0.86, 1.2, 1.0, 1.05, 60, "2025-07-14"),
    ("L04", "Blow molding 2", "Blow molding", "12-cavity rotary stretch blow molder", 2019, 0.89, 0.9, 0.9, 0.95, 55, "2025-04-07"),
    ("L05", "Caps", "Compression molding", "Continuous compression cap molder", 2017, 0.88, 1.0, 1.6, 1.00, 60, "2025-07-14"),
]
LINE = {row[0]: row for row in LINES}

# sku, description, process, ideal rate (units per minute), unit weight (g), unit cost (GTQ),
# contribution margin per unit (GTQ), share of production time on its line
PRODUCTS = [
    ("PF-18G", "Preform 18 g (600 ml water)", "Injection molding", 480, 18.0, 0.21, 0.05, 0.40),
    ("PF-24G", "Preform 24 g (600 ml carbonated)", "Injection molding", 430, 24.0, 0.27, 0.06, 0.25),
    ("PF-38G", "Preform 38 g (1.5 L)", "Injection molding", 340, 38.0, 0.42, 0.09, 0.25),
    ("PF-48G", "Preform 48 g (2.5 L)", "Injection molding", 290, 48.0, 0.53, 0.11, 0.10),
    ("BT-600W", "Bottle 600 ml water", "Blow molding", 560, 18.0, 0.29, 0.07, 0.40),
    ("BT-600C", "Bottle 600 ml carbonated", "Blow molding", 500, 24.0, 0.36, 0.08, 0.25),
    ("BT-1500", "Bottle 1.5 L", "Blow molding", 380, 38.0, 0.55, 0.12, 0.25),
    ("BT-2500", "Bottle 2.5 L", "Blow molding", 300, 48.0, 0.69, 0.15, 0.10),
    ("CP-28", "Cap 28 mm PCO", "Compression molding", 1100, 2.1, 0.045, 0.012, 0.75),
    ("CP-38", "Cap 38 mm", "Compression molding", 850, 3.0, 0.060, 0.015, 0.25),
]
PRODUCT = {row[0]: row for row in PRODUCTS}
SKUS_BY_PROCESS = {p: [r[0] for r in PRODUCTS if r[2] == p] for p in PROCESSES}

# code, description, category, is planned (excluded from planned production time), legacy v1 code
DOWNTIME_REASONS = [
    ("BRK", "Meal break", "Planned stop", 1, "BREAK"),
    ("PM", "Planned maintenance", "Planned stop", 1, "PREV-MAINT"),
    ("NOORD", "No orders scheduled", "Planned stop", 1, "NO-PLAN"),
    ("CO", "Changeover (mold / format change)", "Changeover", 0, "SETUP"),
    ("MECH", "Mechanical failure", "Breakdown", 0, "MECHANICAL"),
    ("ELEC", "Electrical / controls failure", "Breakdown", 0, "ELECTRICAL"),
    ("MOLD", "Mold / tooling failure", "Breakdown", 0, "TOOLING"),
    ("MAT", "Material shortage (resin / preforms)", "Material", 0, "NO-MATERIAL"),
    ("QH", "Quality hold", "Quality", 0, "Q-HOLD"),
    ("JAM", "Jam / misfeed", "Jam", 0, "JAMMED"),
    ("OPR", "No operator available", "Organizational", 0, "NO-OPERATOR"),
    ("UTIL", "Utilities (power, compressed air, chiller)", "Utilities", 0, "POWER-CUT"),
]
LEGACY = {r[0]: r[4] for r in DOWNTIME_REASONS}

DEFECTS = {
    "Injection molding": {"Short shot": 0.25, "Splay / bubbles": 0.20, "Black specks": 0.15, "Flash": 0.15,
                          "Out of spec dimensions": 0.25},
    "Blow molding": {"Thin wall": 0.30, "Off-center base": 0.25, "Leaker": 0.20, "Haze": 0.25},
    "Compression molding": {"Short shot": 0.35, "Flash": 0.30, "Liner defect": 0.35},
}
BASE_SCRAP = {"Injection molding": 0.018, "Blow molding": 0.014, "Compression molding": 0.010}
CHANGEOVERS_PER_SHIFT = {"Injection molding": 3 / 18, "Blow molding": 4 / 18, "Compression molding": 1.5 / 18}

# Resin suppliers: (name, share of lots, price GTQ/kg, mean moisture ppm, scrap multiplier on injection)
PET_SUPPLIERS = [("Polímeros Centroamericanos", 0.6, 11.40, 30, 1.0), ("Resinas del Golfo", 0.4, 10.70, 58, 1.8)]
SUPERVISORS = ["S01", "S02", "S03", "S04", "S05", "S06"]


def _rainy(month: int) -> bool:
    return 5 <= month <= 10


def shift_calendar(start: str = START_DATE, end: str = END_DATE) -> pd.DatetimeIndex:
    """Working days: Monday to Saturday, excluding plant holidays."""
    days = pd.date_range(start, end, freq="D")
    return days[(days.day_of_week < 6) & ~days.strftime("%Y-%m-%d").isin(PLANT_HOLIDAYS)]


def generate_reference_tables() -> dict[str, pd.DataFrame]:
    lines = pd.DataFrame([r[:5] for r in LINES], columns=["line_id", "line_name", "process", "machine", "install_year"])
    lines["smed_group"] = np.select([lines["line_id"].isin(SMED_PILOT_LINES), lines["line_id"].isin(SMED_COMPARISON_LINES)],
                                    ["Pilot", "Comparison"], "Not in study")
    products = pd.DataFrame([r[:7] for r in PRODUCTS], columns=[
        "sku", "description", "process", "ideal_rate_per_min", "unit_weight_g", "unit_cost_gtq", "unit_margin_gtq"])
    reasons = pd.DataFrame(DOWNTIME_REASONS, columns=["reason_code", "description", "category", "is_planned", "legacy_code"])
    return {"lines": lines, "products": products, "downtime_reasons": reasons}


def generate_resin_lots(days: pd.DatetimeIndex, rng: np.random.Generator) -> pd.DataFrame:
    """A new PET lot every 4 working days (shared by both injection presses) and an HDPE lot every 7 for caps."""
    rows = []
    for i, d in enumerate(days[::4]):
        name, _, price, moisture, _ = PET_SUPPLIERS[rng.choice(2, p=[s[1] for s in PET_SUPPLIERS])]
        rows.append((f"PET-{d:%y%m%d}-{i:03d}", "PET", name, d - pd.Timedelta(days=int(rng.integers(3, 12))),
                     round(price * rng.uniform(0.98, 1.02), 2), round(rng.normal(moisture, 6))))
    for i, d in enumerate(days[::7]):
        rows.append((f"HDPE-{d:%y%m%d}-{i:03d}", "HDPE", "Polímeros Centroamericanos",
                     d - pd.Timedelta(days=int(rng.integers(3, 12))), round(12.10 * rng.uniform(0.98, 1.02), 2),
                     round(rng.normal(20, 4))))
    lots = pd.DataFrame(rows, columns=["lot_id", "resin_type", "supplier", "received_date", "price_gtq_per_kg", "moisture_ppm"])
    lots["first_use"] = [d for d in days[::4]] + [d for d in days[::7]]
    return lots


def _lot_lookup(lots: pd.DataFrame, days: pd.DatetimeIndex) -> dict[tuple[str, pd.Timestamp], dict]:
    """(resin type, day) -> the lot in use that day (the most recent lot put into use)."""
    lookup = {}
    for resin, sub in lots.sort_values("first_use").groupby("resin_type"):
        records = sub.to_dict("records")
        idx = np.searchsorted(sub["first_use"].to_numpy(), days.to_numpy(), side="right") - 1
        for d, i in zip(days, idx):
            lookup[(resin, d)] = records[max(i, 0)]
    return lookup


def _lognormal(rng: np.random.Generator, mean: float, sigma: float = 0.5) -> float:
    return float(rng.lognormal(np.log(mean) - sigma ** 2 / 2, sigma))


def _smed_factor(line_id: str, day: pd.Timestamp) -> float:
    """Changeover time multiplier: ramps from 1.0 to 0.55 over 8 weeks after the SMED start on pilot lines."""
    if line_id not in SMED_PILOT_LINES:
        return 1.0
    weeks = (day - pd.Timestamp(SMED_START)).days / 7
    return 1.0 if weeks < 0 else 1.0 - 0.45 * min(weeks / 8, 1.0)


def _simulate_shift(line_id: str, day: pd.Timestamp, shift: str, state: dict, plant: dict,
                    lots: dict, rng: np.random.Generator) -> dict:
    """One line-shift: stops placed on a timeline, production by SKU and scrap by defect."""
    _, _, process, _, install_year, speed, fail_mult, minor_mult, scrap_mult, co_mean, _ = LINE[line_id]
    month = day.month
    events: list[dict] = []

    # Planned stops
    events.append({"code": "BRK", "minutes": float(rng.uniform(28, 32))})
    is_pm = shift == "A" and (day - state["pm_anchor"]).days % 14 == 0
    if is_pm:
        events.append({"code": "PM", "minutes": float(rng.uniform(220, 260)), "first": True})
    elif rng.random() < (0.05 if month in (12, 1) else 0.01):
        events.append({"code": "NOORD", "minutes": 240.0})

    planned = sum(e["minutes"] for e in events)
    hours = (SHIFT_MINUTES - planned) / 60

    # Changeovers
    if rng.random() < CHANGEOVERS_PER_SHIFT[process]:
        options = [s for s in SKUS_BY_PROCESS[process] if s != state["sku"]]
        weights = np.array([PRODUCT[s][7] for s in options])
        to_sku = options[rng.choice(len(options), p=weights / weights.sum())]
        weight_gap = abs(PRODUCT[to_sku][4] - PRODUCT[state["sku"]][4])
        mean = co_mean * _smed_factor(line_id, day) * (1 + 0.006 * weight_gap)
        events.append({"code": "CO", "minutes": _lognormal(rng, mean, 0.35), "from_sku": state["sku"], "to_sku": to_sku})

    # Breakdowns: the old press (L01) gets worse as it ages
    aging = 1 + 0.015 * max(0, (day.year - 2025) * 12 + month - 1) if install_year < 2013 else 1.0
    for _ in range(rng.poisson(hours * 0.09 * fail_mult * aging)):
        kinds = ["MECH", "ELEC", "MOLD"] if process != "Blow molding" else ["MECH", "ELEC"]
        probs = [0.5, 0.3, 0.2] if process != "Blow molding" else [0.6, 0.4]
        code = kinds[rng.choice(len(kinds), p=probs)]
        events.append({"code": code, "minutes": _lognormal(rng, {"MECH": 60, "ELEC": 35, "MOLD": 80}[code], 0.6)})

    # Jams: mostly minor stops (< 5 minutes)
    for _ in range(rng.poisson(hours * 0.6 * minor_mult)):
        events.append({"code": "JAM", "minutes": _lognormal(rng, 3.4, 0.5)})

    # Material shortages: rare, except during the supply disruption
    in_disruption = SUPPLY_DISRUPTION[0] <= day.strftime("%Y-%m-%d") <= SUPPLY_DISRUPTION[1]
    p_mat = (0.30 if process != "Blow molding" else 0.22) if in_disruption else 0.01
    if rng.random() < p_mat:
        events.append({"code": "MAT", "minutes": float(rng.uniform(60, 220) if in_disruption else rng.uniform(20, 80))})
    if rng.random() < 0.03:
        events.append({"code": "QH", "minutes": float(rng.uniform(30, 120))})
    if rng.random() < (0.05 if shift == "C" else 0.01):
        events.append({"code": "OPR", "minutes": float(rng.uniform(20, 60))})
    if plant.get((day, shift)):
        events.append({"code": "UTIL", "minutes": plant[(day, shift)]})

    # Keep the stops inside the shift (leave at least 20 running minutes)
    total = sum(e["minutes"] for e in events)
    if total > SHIFT_MINUTES - 20:
        scale = (SHIFT_MINUTES - 20 - planned) / (total - planned)
        for e in events:
            if e["code"] not in ("BRK", "PM", "NOORD"):
                e["minutes"] *= scale

    # Place stops on the timeline: PM first, the rest in random order with random running gaps
    first = [e for e in events if e.get("first")]
    rest = [e for e in events if not e.get("first")]
    rest = [rest[i] for i in rng.permutation(len(rest))]
    ordered = first + rest
    free = SHIFT_MINUTES - sum(e["minutes"] for e in ordered)
    gaps = rng.dirichlet(np.ones(len(ordered) + 1)) * free
    if first:
        gaps[0] = 0.0
    if rng.random() < 0.03:
        gaps[-1] = 0.0  # the last stop was still open when the shift ended
    gaps = gaps / gaps.sum() * free

    speed_now = speed * rng.normal(1, 0.02) * (0.98 if shift == "C" else 1.0)
    t, sku = 0.0, state["sku"]
    produced: dict[str, float] = {}
    after_co = None
    co_skus = set()
    for gap, e in zip(gaps, ordered):
        produced[sku] = produced.get(sku, 0) + _run_units(sku, gap, speed_now, t, after_co)
        t += gap
        e["start"] = t
        t += e["minutes"]
        if e["code"] == "CO":
            sku, after_co = e["to_sku"], t
            co_skus.add(sku)
    produced[sku] = produced.get(sku, 0) + _run_units(sku, gaps[-1], speed_now, t, after_co)
    state["sku"] = sku

    # Scrap by SKU
    lot = None
    if process == "Injection molding":
        lot = lots[("PET", day)]
    elif process == "Compression molding":
        lot = lots[("HDPE", day)]
    supplier_mult = 1.0
    if lot is not None and lot["resin_type"] == "PET":
        supplier_mult = {s[0]: s[4] for s in PET_SUPPLIERS}[lot["supplier"]]
    production = []
    for s, units in produced.items():
        total_units = int(round(units))
        if total_units <= 0:
            continue
        rate = BASE_SCRAP[process] * scrap_mult * supplier_mult
        rate *= 1.3 if shift == "C" else 1.0
        rate *= 1.12 if (_rainy(month) and process == "Injection molding") else 1.0
        rate += 0.008 if s in co_skus else 0.0  # start-up scrap after a changeover
        scrap = int(min(total_units, round(total_units * rate * rng.lognormal(0, 0.25))))
        weights = dict(DEFECTS[process])
        if supplier_mult > 1:
            weights["Splay / bubbles"] *= 4
        names = list(weights)
        p = np.array([weights[n] for n in names])
        split = rng.multinomial(scrap, p / p.sum())
        production.append({"sku": s, "good": total_units - scrap,
                           "defects": {n: int(k) for n, k in zip(names, split) if k > 0}})

    return {"line_id": line_id, "day": day, "shift": shift, "events": ordered, "production": production,
            "resin_lot": None if lot is None else lot["lot_id"], "supervisor": SUPERVISORS[rng.integers(len(SUPERVISORS))],
            "operators": int(rng.choice([3, 4, 4, 5]))}


def _run_units(sku: str, minutes: float, speed: float, t0: float, after_co: float | None) -> float:
    """Units made in a running stretch; the line runs at 85% speed for the first hour after a changeover."""
    rate = PRODUCT[sku][3] * speed
    units = minutes * rate
    if after_co is not None:
        slow = max(0.0, min(t0 + minutes, after_co + 60) - max(t0, after_co))
        units -= slow * rate * 0.15
    return max(units, 0.0)


def _fmt(ts: pd.Timestamp) -> str:
    return ts.strftime("%Y-%m-%dT%H:%M:%S")


def to_document(sim: dict) -> dict:
    """Render a simulated shift as the MES terminal sends it. Firmware v1 and v2 use different layouts."""
    line_id, day, shift = sim["line_id"], sim["day"], sim["shift"]
    start = day + pd.Timedelta(hours=SHIFTS[shift])
    v2 = day >= pd.Timestamp(LINE[line_id][10])
    doc = {"report_id": f"{line_id}-{day:%Y%m%d}-{shift}", "schema_version": 2 if v2 else 1}
    if v2:
        doc["line"] = line_id
    else:
        doc["line_name"] = f"Línea {int(line_id[1:])}"
    doc.update({"shift_date": f"{day:%Y-%m-%d}", "shift": shift, "shift_start": _fmt(start),
                "shift_minutes": SHIFT_MINUTES, "crew": {"supervisor": sim["supervisor"], "operators": sim["operators"]}})
    if sim["resin_lot"] is not None:
        doc["resin_lot"] = sim["resin_lot"]

    if v2:
        doc["production"] = [{"sku": p["sku"], "good_units": p["good"],
                              "scrap": [{"defect": d, "units": u} for d, u in p["defects"].items()]}
                             for p in sim["production"]]
        events = []
        for e in sim["events"]:
            ev = {"reason_code": e["code"], "start": _fmt(start + pd.Timedelta(minutes=e["start"])),
                  "end": _fmt(start + pd.Timedelta(minutes=e["start"] + e["minutes"]))}
            if e["code"] == "CO":
                ev.update({"from_sku": e["from_sku"], "to_sku": e["to_sku"]})
            events.append(ev)
        doc["downtime_events"] = events
    else:
        # v1: counts as text with thousands separators, defects as an object, stops with a duration
        doc["production"] = [{"sku": p["sku"], "good": f"{p['good']:,}", "defects": p["defects"]}
                             for p in sim["production"]]
        stops = []
        for e in sim["events"]:
            ev = {"code": LEGACY[e["code"]], "started": (start + pd.Timedelta(minutes=e["start"])).strftime("%d/%m/%Y %H:%M"),
                  "minutes": round(e["minutes"], 1)}
            if e["code"] == "CO":
                ev.update({"from_sku": e["from_sku"], "to_sku": e["to_sku"]})
            stops.append(ev)
        doc["stops"] = stops
    doc["ingested_at"] = _fmt(start + pd.Timedelta(minutes=SHIFT_MINUTES + 7))
    return doc


def generate_shift_documents(days: pd.DatetimeIndex, lots: pd.DataFrame, rng: np.random.Generator) -> list[dict]:
    # Plant-wide power cuts: more frequent in the rainy season
    plant = {}
    for d in days:
        for s in SHIFTS:
            if rng.random() < (0.025 if _rainy(d.month) else 0.006):
                plant[(d, s)] = float(rng.uniform(15, 90))
    lookup = _lot_lookup(lots, days)
    docs = []
    for i, (line_id, *_rest) in enumerate(LINES):
        state = {"sku": SKUS_BY_PROCESS[LINE[line_id][2]][0], "pm_anchor": days[0] + pd.Timedelta(days=2 * i)}
        for d in days:
            for s in SHIFTS:
                docs.append(to_document(_simulate_shift(line_id, d, s, state, plant, lookup, rng)))
    return docs


def make_messy(docs: list[dict], lots: pd.DataFrame, rng: np.random.Generator) -> tuple[list[dict], pd.DataFrame]:
    """Add the problems a real MES / ERP extract has. The SQL staging layer fixes each one."""
    docs = copy.deepcopy(docs)
    out = []
    for doc in docs:
        r = rng.random(8)
        v2 = doc["schema_version"] == 2
        # Line ids typed differently on some terminals
        if v2 and r[0] < 0.10:
            n = int(doc["line"][1:])
            doc["line"] = [f"L-{n:02d}", f"l{n:02d} ", f"LINE {n}"][rng.integers(3)]
        # SKU codes in lower case or with trailing spaces
        for p in doc["production"]:
            if rng.random() < 0.05:
                p["sku"] = p["sku"].lower() + " "
        events = doc.get("downtime_events") or doc.get("stops")
        key = "reason_code" if v2 else "code"
        for ev in events:
            u = rng.random()
            if u < 0.06:
                ev[key] = " " + ev[key].lower()          # inconsistent case / spaces
            elif u < 0.062:
                ev[key] = "???"                           # operator skipped the reason screen
        # Clock errors: a stop that ends before it starts (v2 only, start/end timestamps)
        if v2 and events and r[2] < 0.01:
            ev = events[rng.integers(len(events))]
            ev["start"], ev["end"] = ev["end"], ev["start"]
        # A stop that runs past the end of the shift (the next shift logs its own part)
        # A stop still open at the end of the shift is closed by the next shift, so its end time falls
        # outside this shift (the next shift reports its own part)
        if events and r[3] < 0.7:
            ev = events[-1]
            shift_end = pd.Timestamp(doc["shift_start"]) + pd.Timedelta(minutes=SHIFT_MINUTES)
            extra = pd.Timedelta(minutes=int(rng.integers(20, 90)))
            if v2 and abs((pd.Timestamp(ev["end"]) - shift_end).total_seconds()) < 2:
                ev["end"] = _fmt(shift_end + extra)
            elif not v2:
                started = pd.to_datetime(ev["started"], format="%d/%m/%Y %H:%M")
                if abs((started + pd.Timedelta(minutes=ev["minutes"]) - shift_end).total_seconds()) < 90:
                    ev["minutes"] = round((shift_end + extra - started).total_seconds() / 60, 1)
        # The same stop logged twice
        if events and r[1] < 0.03:
            events.append(dict(events[rng.integers(len(events))]))
        # Counter overflow: a 32-bit counter wrapped
        if v2 and r[4] < 0.001 and doc["production"]:
            doc["production"][0]["good_units"] = 4_294_967_295 - int(rng.integers(0, 50_000))
        # Resin lot not scanned
        if "resin_lot" in doc and r[5] < 0.005:
            del doc["resin_lot"]
        # Interim report sent before the shift closed; the final report arrives later and must win
        if r[6] < 0.006:
            interim = copy.deepcopy(doc)
            interim["ingested_at"] = _fmt(pd.Timestamp(doc["ingested_at"]) - pd.Timedelta(minutes=75))
            for p in interim["production"]:
                if v2:
                    p["good_units"] = int(p["good_units"] * 0.8) if p["good_units"] < 4e9 else p["good_units"]
                else:
                    p["good"] = f"{int(int(p['good'].replace(',', '')) * 0.8):,}"
            out.append(interim)
        out.append(doc)
    # Documents arrive in no particular order
    out = [out[i] for i in rng.permutation(len(out))]

    # ERP resin lots: supplier spelled several ways, mixed date formats, a duplicated row
    lots = lots.copy()
    variants = {"Resinas del Golfo": ["Resinas del Golfo", "RESINAS DEL GOLFO", "Resinas del Golfo, S.A."],
                "Polímeros Centroamericanos": ["Polímeros Centroamericanos", "POLIMEROS CENTROAMERICANOS",
                                               "Polimeros Centroamericanos S.A."]}
    lots["supplier"] = [variants[s][rng.choice(3, p=[0.7, 0.15, 0.15])] for s in lots["supplier"]]
    dates = pd.to_datetime(lots["received_date"])
    lots["received_date"] = np.where(rng.random(len(lots)) < 0.3, dates.dt.strftime("%d/%m/%Y"),
                                     dates.dt.strftime("%Y-%m-%d"))
    lots = pd.concat([lots, lots.sample(2, random_state=int(rng.integers(1e9)))], ignore_index=True)
    return out, lots


def generate_all(seed: int = 42, start: str = START_DATE, end: str = END_DATE,
                 messy: bool = True) -> tuple[list[dict], dict[str, pd.DataFrame]]:
    """Return (MES shift documents, ERP / reference tables). Same seed -> same data."""
    rng = np.random.default_rng(seed)
    days = shift_calendar(start, end)
    lots = generate_resin_lots(days, rng)
    docs = generate_shift_documents(days, lots, rng)
    lots = lots.drop(columns="first_use")
    lots["received_date"] = pd.to_datetime(lots["received_date"]).dt.strftime("%Y-%m-%d")
    if messy:
        docs, lots = make_messy(docs, lots, rng)
    tables = generate_reference_tables()
    tables["resin_lots"] = lots
    return docs, tables
