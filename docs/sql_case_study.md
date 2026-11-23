# SQL case study: business questions and answers

Each question is answered by one query in [`sql/analysis/`](../sql/analysis). Results come from the default run (`python run_pipeline.py`, seed 42). Regenerate this file with `python scripts/run_case_study.py`.

1. [How has plant OEE moved month by month, and what changed versus the month before?](#q1)
2. [Which lines are furthest from world-class OEE (85%), and is it availability, performance or quality?](#q2)
3. [Which causes make up 80% of unplanned downtime (Pareto)?](#q3)
4. [Did the SMED (quick changeover) program work? Difference-in-differences against the comparison lines.](#q4)
5. [How reliable is each machine (MTBF / MTTR), and is the old press getting worse?](#q5)
6. [Does the cheaper resin supplier cause more scrap on the injection presses, and does it still pay off?](#q6)
7. [Is the night shift less effective, and on which lines?](#q7)
8. [What is each line's longest streak of consecutive shifts without a breakdown?](#q8)
9. [What are the losses worth, and where would one OEE point pay the most?](#q9)
10. [Which product changes take longest on the injection presses, before and after SMED?](#q10)

## <a id="q1"></a>1. How has plant OEE moved month by month, and what changed versus the month before?

[`q01_plant_oee_trend.sql`](../sql/analysis/q01_plant_oee_trend.sql)

<details><summary>Show SQL</summary>

```sql
-- Question: How has plant OEE moved month by month, and what changed versus the month before?
-- Technique: aggregate numerators and denominators per month, then LAG() for the month-over-month change.
WITH monthly AS (
    SELECT
        month_start,
        SUM(run_time_min) / SUM(planned_time_min)                       AS availability,
        SUM(ideal_min_total) / SUM(run_time_min)                        AS performance,
        1.0 * SUM(good_units) / SUM(total_units)                        AS quality,
        SUM(ideal_min_good) / SUM(planned_time_min)                     AS oee
    FROM fct_shift_oee
    GROUP BY month_start
)
SELECT
    SUBSTR(month_start, 1, 7)                                           AS month,
    ROUND(100 * availability, 1)                                        AS availability_pct,
    ROUND(100 * performance, 1)                                         AS performance_pct,
    ROUND(100 * quality, 1)                                             AS quality_pct,
    ROUND(100 * oee, 1)                                                 AS oee_pct,
    ROUND(100 * (oee - LAG(oee) OVER (ORDER BY month_start)), 1)        AS change_vs_prev_month_pts
FROM monthly
ORDER BY month_start;
```

</details>

| month | availability_pct | performance_pct | quality_pct | oee_pct | change_vs_prev_month_pts |
| --- | --- | --- | --- | --- | --- |
| 2025-01 | 85.6 | 83.1 | 98.1 | 69.6 |  |
| 2025-02 | 85.4 | 82.8 | 98.2 | 69.3 | -0.3 |
| 2025-03 | 85.2 | 82.9 | 98.2 | 69.2 | -0.1 |
| 2025-04 | 85.5 | 82.9 | 98.0 | 69.3 | 0.1 |
| 2025-05 | 83.6 | 82.6 | 98.2 | 67.6 | -1.7 |
| 2025-06 | 85.2 | 82.8 | 98.2 | 69.1 | 1.4 |
| 2025-07 | 84.1 | 82.6 | 98.1 | 68.0 | -1.1 |
| 2025-08 | 79.3 | 82.7 | 98.2 | 64.3 | -3.7 |
| 2025-09 | 79.1 | 82.7 | 98.3 | 64.1 | -0.1 |
| 2025-10 | 85.0 | 83.0 | 98.1 | 69.1 | 4.9 |
| 2025-11 | 84.6 | 82.7 | 98.3 | 68.7 | -0.4 |
| 2025-12 | 86.7 | 83.1 | 98.1 | 70.6 | 1.8 |
| 2026-01 | 85.3 | 82.7 | 98.1 | 69.1 | -1.5 |
| 2026-02 | 85.6 | 82.9 | 98.1 | 69.6 | 0.5 |
| 2026-03 | 85.1 | 82.7 | 98.0 | 68.9 | -0.7 |
| 2026-04 | 85.8 | 82.8 | 98.2 | 69.6 | 0.7 |
| 2026-05 | 85.0 | 82.7 | 98.1 | 68.9 | -0.7 |
| 2026-06 | 84.8 | 83.1 | 98.2 | 68.9 | 0.1 |
| 2026-07 | 85.2 | 82.8 | 98.2 | 69.0 | 0.1 |
| 2026-08 | 84.0 | 82.9 | 98.2 | 68.3 | -0.8 |
| 2026-09 | 85.1 | 82.8 | 98.0 | 68.9 | 0.7 |
| 2026-10 | 85.3 | 82.8 | 98.0 | 69.0 | 0.1 |

## <a id="q2"></a>2. Which lines are furthest from world-class OEE (85%), and is it availability, performance or quality?

[`q02_lines_vs_world_class.sql`](../sql/analysis/q02_lines_vs_world_class.sql)

<details><summary>Show SQL</summary>

```sql
-- Question: Which lines are furthest from world-class OEE (85%), and is it availability, performance or quality?
-- Technique: OEE decomposition per line, RANK() and the weakest factor picked with a CASE over the three components.
WITH lines AS (
    SELECT
        f.line_id,
        l.line_name,
        SUM(f.run_time_min) / SUM(f.planned_time_min)                   AS availability,
        SUM(f.ideal_min_total) / SUM(f.run_time_min)                    AS performance,
        1.0 * SUM(f.good_units) / SUM(f.total_units)                    AS quality,
        SUM(f.ideal_min_good) / SUM(f.planned_time_min)                 AS oee
    FROM fct_shift_oee f
    JOIN dim_line l ON l.line_id = f.line_id
    GROUP BY f.line_id, l.line_name
)
SELECT
    RANK() OVER (ORDER BY oee)                                          AS worst_rank,
    line_id,
    line_name,
    ROUND(100 * availability, 1)                                        AS availability_pct,
    ROUND(100 * performance, 1)                                         AS performance_pct,
    ROUND(100 * quality, 1)                                             AS quality_pct,
    ROUND(100 * oee, 1)                                                 AS oee_pct,
    ROUND(100 * ((SELECT world_class_oee FROM ref_parameters) - oee), 1) AS gap_to_world_class_pts,
    CASE
        WHEN availability <= performance AND availability <= quality THEN 'Availability'
        WHEN performance <= quality THEN 'Performance'
        ELSE 'Quality'
    END                                                                 AS weakest_factor
FROM lines
ORDER BY oee;
```

</details>

| worst_rank | line_id | line_name | availability_pct | performance_pct | quality_pct | oee_pct | gap_to_world_class_pts | weakest_factor |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | L01 | Injection 1 | 74.4 | 73.6 | 96.5 | 52.9 | 32.1 | Performance |
| 2 | L03 | Blow molding 1 | 86.1 | 82.8 | 98.3 | 70.0 | 15.0 | Performance |
| 3 | L05 | Caps | 86.7 | 83.4 | 98.8 | 71.5 | 13.5 | Performance |
| 4 | L02 | Injection 2 | 86.9 | 87.1 | 97.2 | 73.6 | 11.4 | Availability |
| 5 | L04 | Blow molding 2 | 88.6 | 85.9 | 98.4 | 74.9 | 10.1 | Performance |

## <a id="q3"></a>3. Which causes make up 80% of unplanned downtime (Pareto)?

[`q03_downtime_pareto.sql`](../sql/analysis/q03_downtime_pareto.sql)

<details><summary>Show SQL</summary>

```sql
-- Question: Which causes make up 80% of unplanned downtime (Pareto)?
-- Technique: running total with SUM() OVER (ORDER BY ...) and a flag for the "vital few".
WITH by_reason AS (
    SELECT reason, category, COUNT(*) AS stops, SUM(duration_min) AS minutes
    FROM fct_downtime_events
    WHERE loss_bucket = 'Availability loss'
    GROUP BY reason, category
),
ranked AS (
    SELECT *,
           SUM(minutes) OVER (ORDER BY minutes DESC ROWS UNBOUNDED PRECEDING) / SUM(minutes) OVER () AS cumulative_share,
           (SUM(minutes) OVER (ORDER BY minutes DESC ROWS UNBOUNDED PRECEDING) - minutes) / SUM(minutes) OVER () AS share_before
    FROM by_reason
)
SELECT
    reason,
    category,
    stops,
    ROUND(minutes / 60.0, 0)                                            AS hours,
    ROUND(minutes / stops, 1)                                           AS avg_minutes,
    ROUND(100 * cumulative_share, 1)                                    AS cumulative_pct,
    CASE WHEN share_before < 0.80 THEN 'Vital few' ELSE 'Useful many' END AS pareto_group
FROM ranked
ORDER BY minutes DESC;
```

</details>

| reason | category | stops | hours | avg_minutes | cumulative_pct | pareto_group |
| --- | --- | --- | --- | --- | --- | --- |
| Mechanical failure | Breakdown | 3475 | 3,495 | 60.3 | 36.8 | Vital few |
| Changeover (mold / format change) | Changeover | 1429 | 1,714 | 72.0 | 54.9 | Vital few |
| Electrical / controls failure | Breakdown | 2214 | 1,288 | 34.9 | 68.4 | Vital few |
| Mold / tooling failure | Breakdown | 877 | 1,195 | 81.7 | 81.0 | Vital few |
| Jam / misfeed | Jam | 7421 | 824.0 | 6.7 | 89.7 | Useful many |
| Material shortage (resin / preforms) | Material | 221 | 400.0 | 108.7 | 93.9 | Useful many |
| Quality hold | Quality | 252 | 314.0 | 74.7 | 97.2 | Useful many |
| No operator available | Organizational | 182 | 119.0 | 39.2 | 98.5 | Useful many |
| Utilities (power, compressed air, chiller) | Utilities | 134 | 112.0 | 50.3 | 99.7 | Useful many |
| Unclassified (no reason entered) | Unclassified | 53 | 31.0 | 35.5 | 100.0 | Useful many |

## <a id="q4"></a>4. Did the SMED (quick changeover) program work? Difference-in-differences against the comparison lines.

[`q04_smed_difference_in_differences.sql`](../sql/analysis/q04_smed_difference_in_differences.sql)

<details><summary>Show SQL</summary>

```sql
-- Question: Did the SMED (quick changeover) program work? Difference-in-differences against the comparison lines.
-- Technique: conditional aggregation into a 2x2 table (pilot/comparison x before/after), then the DiD in one SELECT.
WITH cells AS (
    SELECT
        smed_group,
        SUM(CASE WHEN smed_period = 'Pre' THEN changeover_min END)
            / SUM(CASE WHEN smed_period = 'Pre' THEN changeovers END)  AS co_min_pre,
        SUM(CASE WHEN smed_period = 'Post' THEN changeover_min END)
            / SUM(CASE WHEN smed_period = 'Post' THEN changeovers END) AS co_min_post,
        SUM(CASE WHEN smed_period = 'Pre' THEN changeover_min END)
            / SUM(CASE WHEN smed_period = 'Pre' THEN planned_time_min END)  AS co_share_pre,
        SUM(CASE WHEN smed_period = 'Post' THEN changeover_min END)
            / SUM(CASE WHEN smed_period = 'Post' THEN planned_time_min END) AS co_share_post,
        SUM(CASE WHEN smed_period = 'Post' THEN planned_time_min END) / 60.0 AS planned_hours_post
    FROM fct_shift_oee
    WHERE smed_group IN ('Pilot', 'Comparison')
    GROUP BY smed_group
)
SELECT
    'Average changeover (minutes)'                                      AS metric,
    ROUND(p.co_min_pre, 1)                                              AS pilot_before,
    ROUND(p.co_min_post, 1)                                             AS pilot_after,
    ROUND(c.co_min_pre, 1)                                              AS comparison_before,
    ROUND(c.co_min_post, 1)                                             AS comparison_after,
    ROUND((p.co_min_post - p.co_min_pre) - (c.co_min_post - c.co_min_pre), 1) AS diff_in_diff,
    NULL                                                                AS planned_hours_freed_post
FROM cells p, cells c
WHERE p.smed_group = 'Pilot' AND c.smed_group = 'Comparison'
UNION ALL
SELECT
    'Changeover share of planned time (%)',
    ROUND(100 * p.co_share_pre, 2), ROUND(100 * p.co_share_post, 2),
    ROUND(100 * c.co_share_pre, 2), ROUND(100 * c.co_share_post, 2),
    ROUND(100 * ((p.co_share_post - p.co_share_pre) - (c.co_share_post - c.co_share_pre)), 2),
    -- hours of planned time given back to production on the pilot lines since the start
    ROUND(-((p.co_share_post - p.co_share_pre) - (c.co_share_post - c.co_share_pre)) * p.planned_hours_post, 0)
FROM cells p, cells c
WHERE p.smed_group = 'Pilot' AND c.smed_group = 'Comparison';
```

</details>

| metric | pilot_before | pilot_after | comparison_before | comparison_after | diff_in_diff | planned_hours_freed_post |
| --- | --- | --- | --- | --- | --- | --- |
| Average changeover (minutes) | 82.4 | 48.8 | 80.0 | 76.4 | -30.0 |  |
| Changeover share of planned time (%) | 3.62 | 2.04 | 3.58 | 3.29 | -1.3 | 144.0 |

## <a id="q5"></a>5. How reliable is each machine (MTBF / MTTR), and is the old press getting worse?

[`q05_reliability_mtbf_mttr.sql`](../sql/analysis/q05_reliability_mtbf_mttr.sql)

<details><summary>Show SQL</summary>

```sql
-- Question: How reliable is each machine (MTBF / MTTR), and is the old press getting worse?
-- Technique: MTBF per line and half-year, then LAG() to compare each half-year with the previous one.
WITH halves AS (
    SELECT
        line_id,
        STRFTIME('%Y', shift_date) || CASE WHEN CAST(STRFTIME('%m', shift_date) AS INTEGER) <= 6 THEN '-H1' ELSE '-H2' END AS half_year,
        SUM(run_time_min) / 60.0                                        AS run_hours,
        SUM(breakdowns)                                                 AS breakdowns,
        SUM(breakdown_min)                                              AS breakdown_min
    FROM fct_shift_oee
    GROUP BY 1, 2
)
SELECT
    line_id,
    half_year,
    breakdowns,
    ROUND(run_hours / breakdowns, 1)                                    AS mtbf_hours,
    ROUND(breakdown_min / breakdowns, 1)                                AS mttr_minutes,
    ROUND(run_hours / breakdowns - LAG(run_hours / breakdowns) OVER (PARTITION BY line_id ORDER BY half_year), 1) AS mtbf_change_hours
FROM halves
ORDER BY line_id, half_year;
```

</details>

| line_id | half_year | breakdowns | mtbf_hours | mttr_minutes | mtbf_change_hours |
| --- | --- | --- | --- | --- | --- |
| L01 | 2025-H1 | 590 | 4.2 | 56.1 |  |
| L01 | 2025-H2 | 633 | 3.9 | 57.4 | -0.4 |
| L01 | 2026-H1 | 633 | 4.0 | 57.4 | 0.1 |
| L01 | 2026-H2 | 497 | 3.4 | 59.8 | -0.6 |
| L02 | 2025-H1 | 232 | 12.5 | 55.4 |  |
| L02 | 2025-H2 | 243 | 11.7 | 58.2 | -0.7 |
| L02 | 2026-H1 | 210 | 14.0 | 58.9 | 2.2 |
| L02 | 2026-H2 | 173 | 11.6 | 57.5 | -2.4 |
| L03 | 2025-H1 | 335 | 8.6 | 48.7 |  |
| L03 | 2025-H2 | 350 | 8.1 | 46.1 | -0.4 |
| L03 | 2026-H1 | 369 | 7.8 | 52.2 | -0.4 |
| L03 | 2026-H2 | 235 | 8.5 | 47.5 | 0.7 |
| L04 | 2025-H1 | 278 | 10.6 | 47.9 |  |
| L04 | 2025-H2 | 244 | 12.2 | 48.1 | 1.6 |
| L04 | 2026-H1 | 262 | 11.2 | 48.8 | -1.0 |
| L04 | 2026-H2 | 176 | 11.7 | 50.8 | 0.5 |
| L05 | 2025-H1 | 287 | 10.1 | 57.5 |  |
| L05 | 2025-H2 | 304 | 9.4 | 55.5 | -0.7 |
| L05 | 2026-H1 | 307 | 9.4 | 59.6 | 0.1 |
| L05 | 2026-H2 | 208 | 9.6 | 60.0 | 0.2 |

## <a id="q6"></a>6. Does the cheaper resin supplier cause more scrap on the injection presses, and does it still pay off?

[`q06_resin_supplier_scrap.sql`](../sql/analysis/q06_resin_supplier_scrap.sql)

<details><summary>Show SQL</summary>

```sql
-- Question: Does the cheaper resin supplier cause more scrap on the injection presses, and does it still pay off?
-- Technique: join shifts to resin lots, compare scrap and splay rates, then price the extra scrap against the resin savings.
WITH by_supplier AS (
    SELECT
        r.supplier,
        SUM(f.total_units)                                              AS total_units,
        SUM(f.scrap_units)                                              AS scrap_units,
        SUM(f.scrap_cost_gtq)                                           AS scrap_cost,
        SUM(f.resin_kg)                                                 AS resin_kg,
        SUM(f.resin_kg * r.price_gtq_per_kg) / SUM(f.resin_kg)          AS price_per_kg,
        AVG(r.moisture_ppm)                                             AS moisture_ppm
    FROM fct_shift_oee f
    JOIN dim_resin_lot r ON r.lot_id = f.resin_lot
    WHERE f.process = 'Injection molding' AND r.resin_type = 'PET'
    GROUP BY r.supplier
),
base AS (SELECT * FROM by_supplier WHERE supplier = 'Polímeros Centroamericanos')
SELECT
    s.supplier,
    ROUND(s.moisture_ppm, 0)                                            AS avg_moisture_ppm,
    ROUND(100.0 * s.scrap_units / s.total_units, 2)                     AS scrap_pct,
    ROUND(s.price_per_kg, 2)                                            AS price_gtq_per_kg,
    ROUND(s.resin_kg / 1000, 0)                                         AS resin_tonnes,
    -- resin saved by buying this supplier instead of the reference supplier
    ROUND((b.price_per_kg - s.price_per_kg) * s.resin_kg, 0)            AS resin_savings_gtq,
    -- scrap cost above what the reference supplier's scrap rate would have cost
    ROUND(s.scrap_cost - s.scrap_cost * (1.0 * b.scrap_units / b.total_units) / (1.0 * s.scrap_units / s.total_units), 0) AS extra_scrap_cost_gtq
FROM by_supplier s
CROSS JOIN base b
ORDER BY scrap_pct;
```

</details>

| supplier | avg_moisture_ppm | scrap_pct | price_gtq_per_kg | resin_tonnes | resin_savings_gtq | extra_scrap_cost_gtq |
| --- | --- | --- | --- | --- | --- | --- |
| Polímeros Centroamericanos | 30.0 | 2.36 | 11.39 | 6,205 | 0.0 | 0.0 |
| Resinas del Golfo | 59.0 | 4.13 | 10.72 | 4,211 | 2,807,526 | 838,861 |

## <a id="q7"></a>7. Is the night shift less effective, and on which lines?

[`q07_oee_by_shift_pivot.sql`](../sql/analysis/q07_oee_by_shift_pivot.sql)

<details><summary>Show SQL</summary>

```sql
-- Question: Is the night shift less effective, and on which lines?
-- Technique: pivot with conditional aggregation (one column per shift).
SELECT
    f.line_id,
    l.line_name,
    ROUND(100 * SUM(CASE WHEN f.shift = 'A' THEN f.ideal_min_good END) / SUM(CASE WHEN f.shift = 'A' THEN f.planned_time_min END), 1) AS oee_morning,
    ROUND(100 * SUM(CASE WHEN f.shift = 'B' THEN f.ideal_min_good END) / SUM(CASE WHEN f.shift = 'B' THEN f.planned_time_min END), 1) AS oee_afternoon,
    ROUND(100 * SUM(CASE WHEN f.shift = 'C' THEN f.ideal_min_good END) / SUM(CASE WHEN f.shift = 'C' THEN f.planned_time_min END), 1) AS oee_night,
    ROUND(100.0 * SUM(CASE WHEN f.shift <> 'C' THEN f.scrap_units END) / SUM(CASE WHEN f.shift <> 'C' THEN f.total_units END), 2)   AS scrap_pct_day,
    ROUND(100.0 * SUM(CASE WHEN f.shift = 'C' THEN f.scrap_units END) / SUM(CASE WHEN f.shift = 'C' THEN f.total_units END), 2)    AS scrap_pct_night
FROM fct_shift_oee f
JOIN dim_line l ON l.line_id = f.line_id
GROUP BY f.line_id, l.line_name
ORDER BY f.line_id;
```

</details>

| line_id | line_name | oee_morning | oee_afternoon | oee_night | scrap_pct_day | scrap_pct_night |
| --- | --- | --- | --- | --- | --- | --- |
| L01 | Injection 1 | 54.0 | 52.5 | 52.1 | 3.17 | 4.22 |
| L02 | Injection 2 | 74.9 | 74.3 | 71.6 | 2.51 | 3.27 |
| L03 | Blow molding 1 | 70.2 | 71.4 | 68.5 | 1.6 | 2.04 |
| L04 | Blow molding 2 | 75.8 | 75.8 | 73.1 | 1.45 | 1.85 |
| L05 | Caps | 72.4 | 72.2 | 69.8 | 1.06 | 1.35 |

## <a id="q8"></a>8. What is each line's longest streak of consecutive shifts without a breakdown?

[`q08_longest_run_without_breakdown.sql`](../sql/analysis/q08_longest_run_without_breakdown.sql)

<details><summary>Show SQL</summary>

```sql
-- Question: What is each line's longest streak of consecutive shifts without a breakdown?
-- Technique: gaps and islands: ROW_NUMBER() minus a running count of breakdown shifts identifies each streak.
WITH ordered AS (
    SELECT
        line_id,
        shift_start_order,
        shift_date,
        CASE WHEN breakdowns > 0 THEN 1 ELSE 0 END                      AS had_breakdown,
        SUM(CASE WHEN breakdowns > 0 THEN 1 ELSE 0 END) OVER (PARTITION BY line_id ORDER BY shift_start_order) AS breakdowns_so_far
    FROM (SELECT f.*, f.shift_date || f.shift AS shift_start_order FROM fct_shift_oee f)
),
streaks AS (
    SELECT line_id, breakdowns_so_far AS streak_id, COUNT(*) AS shifts, MIN(shift_date) AS from_date, MAX(shift_date) AS to_date
    FROM ordered
    WHERE had_breakdown = 0
    GROUP BY line_id, breakdowns_so_far
),
best AS (
    SELECT *, ROW_NUMBER() OVER (PARTITION BY line_id ORDER BY shifts DESC, from_date) AS rn FROM streaks
)
SELECT
    b.line_id,
    b.shifts                                                            AS longest_streak_shifts,
    b.from_date,
    b.to_date,
    ROUND(100.0 * (SELECT AVG(CASE WHEN breakdowns > 0 THEN 1.0 ELSE 0 END) FROM fct_shift_oee f WHERE f.line_id = b.line_id), 1) AS pct_shifts_with_breakdown
FROM best b
WHERE b.rn = 1
ORDER BY b.line_id;
```

</details>

| line_id | longest_streak_shifts | from_date | to_date | pct_shifts_with_breakdown |
| --- | --- | --- | --- | --- |
| L01 | 4 | 2025-08-28 | 2025-08-29 | 75.2 |
| L02 | 10 | 2026-09-02 | 2026-09-05 | 40.6 |
| L03 | 10 | 2026-05-09 | 2026-05-13 | 52.5 |
| L04 | 10 | 2026-10-01 | 2026-10-05 | 43.9 |
| L05 | 10 | 2025-01-10 | 2025-01-14 | 48.3 |

## <a id="q9"></a>9. What are the losses worth, and where would one OEE point pay the most?

[`q09_value_of_losses.sql`](../sql/analysis/q09_value_of_losses.sql)

<details><summary>Show SQL</summary>

```sql
-- Question: What are the losses worth, and where would one OEE point pay the most?
-- Technique: value the gap between planned time and fully productive time at each SKU's contribution margin.
WITH span AS (
    SELECT (JULIANDAY(MAX(shift_date)) - JULIANDAY(MIN(shift_date)) + 1) / 365.25 AS years FROM fct_shift_oee
)
SELECT
    f.line_id,
    l.line_name,
    ROUND(100 * SUM(f.ideal_min_good) / SUM(f.planned_time_min), 1)    AS oee_pct,
    ROUND(SUM(f.lost_margin_gtq) / s.years / 1e6, 2)                    AS margin_lost_vs_100pct_oee_m_gtq_per_year,
    ROUND(SUM(f.scrap_cost_gtq) / s.years / 1e6, 2)                     AS scrap_cost_m_gtq_per_year,
    ROUND(0.01 * SUM(f.planned_time_min * f.margin_per_ideal_min) / s.years, 0) AS gtq_per_oee_point_per_year,
    -- margin gained per year if the line reached the plant's best line OEE
    ROUND(MAX(0, (SELECT MAX(o) FROM (SELECT SUM(ideal_min_good) / SUM(planned_time_min) AS o FROM fct_shift_oee GROUP BY line_id))
                 - SUM(f.ideal_min_good) / SUM(f.planned_time_min))
          * SUM(f.planned_time_min * f.margin_per_ideal_min) / s.years, 0) AS gtq_per_year_at_best_line_oee
FROM fct_shift_oee f
JOIN dim_line l ON l.line_id = f.line_id
CROSS JOIN span s
GROUP BY f.line_id, l.line_name, s.years
ORDER BY gtq_per_year_at_best_line_oee DESC;
```

</details>

| line_id | line_name | oee_pct | margin_lost_vs_100pct_oee_m_gtq_per_year | scrap_cost_m_gtq_per_year | gtq_per_oee_point_per_year | gtq_per_year_at_best_line_oee |
| --- | --- | --- | --- | --- | --- | --- |
| L01 | Injection 1 | 52.9 | 5.2 | 0.95 | 110,319 | 2,428,886 |
| L03 | Blow molding 1 | 70.0 | 5.06 | 0.93 | 168,926 | 819,080 |
| L05 | Caps | 71.5 | 1.49 | 0.17 | 52,274 | 178,591 |
| L02 | Injection 2 | 73.6 | 2.9 | 1.03 | 109,437 | 140,630 |
| L04 | Blow molding 2 | 74.9 | 4.25 | 0.9 | 168,917 | 0.0 |

## <a id="q10"></a>10. Which product changes take longest on the injection presses, before and after SMED?

[`q10_changeover_matrix.sql`](../sql/analysis/q10_changeover_matrix.sql)

<details><summary>Show SQL</summary>

```sql
-- Question: Which product changes take longest on the injection presses, before and after SMED?
-- Technique: self-describing changeover pairs (from_sku -> to_sku) with conditional aggregation by period.
SELECT
    e.from_sku,
    e.to_sku,
    ABS(pf.unit_weight_g - pt.unit_weight_g)                            AS weight_gap_g,
    COUNT(*)                                                            AS changeovers,
    ROUND(AVG(CASE WHEN e.smed_period = 'Pre' THEN e.duration_min END), 1)  AS avg_minutes_before_smed,
    ROUND(AVG(CASE WHEN e.smed_period = 'Post' AND l.smed_group = 'Pilot' THEN e.duration_min END), 1) AS avg_minutes_pilot_after_smed
FROM fct_downtime_events e
JOIN dim_line l     ON l.line_id = e.line_id
JOIN dim_product pf ON pf.sku = e.from_sku
JOIN dim_product pt ON pt.sku = e.to_sku
WHERE e.category = 'Changeover' AND l.process = 'Injection molding'
GROUP BY e.from_sku, e.to_sku, pf.unit_weight_g, pt.unit_weight_g
HAVING COUNT(*) >= 10
ORDER BY avg_minutes_before_smed DESC;
```

</details>

| from_sku | to_sku | weight_gap_g | changeovers | avg_minutes_before_smed | avg_minutes_pilot_after_smed |
| --- | --- | --- | --- | --- | --- |
| PF-48G | PF-18G | 30.0 | 33 | 120.5 | 77.7 |
| PF-48G | PF-24G | 24.0 | 21 | 115.2 | 44.7 |
| PF-24G | PF-38G | 14.0 | 49 | 110.0 | 57.5 |
| PF-24G | PF-48G | 24.0 | 14 | 106.4 | 52.5 |
| PF-38G | PF-18G | 20.0 | 83 | 105.9 | 64.2 |
| PF-38G | PF-24G | 14.0 | 56 | 105.8 | 56.7 |
| PF-18G | PF-38G | 20.0 | 93 | 103.8 | 65.0 |
| PF-38G | PF-48G | 10.0 | 26 | 103.6 | 39.7 |
| PF-24G | PF-18G | 6.0 | 74 | 99.9 | 59.3 |
| PF-18G | PF-48G | 30.0 | 39 | 98.6 | 56.9 |
| PF-18G | PF-24G | 6.0 | 61 | 98.4 | 56.6 |
| PF-48G | PF-38G | 10.0 | 24 | 95.0 | 53.6 |
