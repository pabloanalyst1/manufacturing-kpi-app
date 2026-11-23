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
| 2025-01 | 86.3 | 83.1 | 98.1 | 70.2 |  |
| 2025-02 | 85.7 | 82.9 | 98.3 | 69.6 | -0.5 |
| 2025-03 | 85.3 | 82.9 | 98.2 | 69.4 | -0.3 |
| 2025-04 | 83.7 | 82.6 | 98.1 | 67.7 | -1.7 |
| 2025-05 | 84.4 | 82.9 | 98.1 | 68.5 | 0.8 |
| 2025-06 | 85.0 | 82.9 | 98.2 | 69.0 | 0.5 |
| 2025-07 | 84.8 | 82.7 | 98.2 | 68.8 | -0.3 |
| 2025-08 | 79.0 | 82.6 | 98.2 | 63.9 | -4.8 |
| 2025-09 | 78.6 | 82.2 | 98.1 | 63.2 | -0.7 |
| 2025-10 | 85.5 | 83.2 | 98.2 | 69.7 | 6.5 |
| 2025-11 | 86.3 | 82.9 | 98.2 | 70.1 | 0.3 |
| 2025-12 | 84.1 | 83.0 | 98.3 | 68.5 | -1.5 |
| 2026-01 | 84.7 | 82.9 | 98.3 | 68.9 | 0.4 |
| 2026-02 | 87.3 | 83.0 | 98.1 | 70.9 | 2.0 |
| 2026-03 | 86.0 | 83.0 | 98.3 | 70.0 | -0.9 |
| 2026-04 | 85.3 | 82.9 | 98.1 | 69.2 | -0.8 |
| 2026-05 | 84.2 | 82.9 | 97.9 | 68.2 | -1.0 |
| 2026-06 | 86.9 | 82.9 | 98.1 | 70.4 | 2.2 |
| 2026-07 | 86.5 | 82.9 | 97.9 | 70.0 | -0.4 |
| 2026-08 | 84.6 | 82.8 | 98.0 | 68.5 | -1.5 |
| 2026-09 | 85.6 | 82.9 | 98.3 | 69.6 | 1.1 |
| 2026-10 | 84.4 | 82.8 | 98.2 | 68.5 | -1.1 |

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
| 1 | L01 | Injection 1 | 75.9 | 73.7 | 96.6 | 54.0 | 31.0 | Performance |
| 2 | L03 | Blow molding 1 | 86.7 | 82.8 | 98.3 | 70.5 | 14.5 | Performance |
| 3 | L05 | Caps | 87.1 | 83.5 | 98.8 | 71.9 | 13.1 | Performance |
| 4 | L02 | Injection 2 | 86.6 | 87.2 | 97.3 | 73.4 | 11.6 | Availability |
| 5 | L04 | Blow molding 2 | 87.4 | 85.9 | 98.4 | 73.9 | 11.1 | Performance |

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
| Mechanical failure | Breakdown | 3486 | 3,461 | 59.6 | 36.9 | Vital few |
| Changeover (mold / format change) | Changeover | 1463 | 1,742 | 71.4 | 55.5 | Vital few |
| Electrical / controls failure | Breakdown | 2195 | 1,283 | 35.1 | 69.2 | Vital few |
| Mold / tooling failure | Breakdown | 858 | 1,101 | 77.0 | 80.9 | Vital few |
| Jam / misfeed | Jam | 7311 | 814.0 | 6.7 | 89.6 | Useful many |
| Material shortage (resin / preforms) | Material | 226 | 424.0 | 112.5 | 94.1 | Useful many |
| Quality hold | Quality | 224 | 280.0 | 74.9 | 97.1 | Useful many |
| No operator available | Organizational | 191 | 125.0 | 39.4 | 98.5 | Useful many |
| Utilities (power, compressed air, chiller) | Utilities | 135 | 114.0 | 50.7 | 99.7 | Useful many |
| Unclassified (no reason entered) | Unclassified | 59 | 30.0 | 30.6 | 100.0 | Useful many |

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
| Average changeover (minutes) | 82.5 | 48.4 | 78.4 | 77.7 | -33.4 |  |
| Changeover share of planned time (%) | 3.63 | 2.03 | 3.5 | 3.61 | -1.7 | 189.0 |

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
| L01 | 2025-H1 | 549 | 4.6 | 54.7 |  |
| L01 | 2025-H2 | 593 | 4.2 | 55.5 | -0.4 |
| L01 | 2026-H1 | 674 | 3.8 | 53.7 | -0.5 |
| L01 | 2026-H2 | 468 | 3.7 | 55.4 | -0.1 |
| L02 | 2025-H1 | 264 | 10.9 | 54.6 |  |
| L02 | 2025-H2 | 251 | 11.4 | 56.7 | 0.5 |
| L02 | 2026-H1 | 219 | 13.3 | 56.1 | 1.9 |
| L02 | 2026-H2 | 149 | 13.4 | 59.5 | 0.1 |
| L03 | 2025-H1 | 364 | 7.9 | 45.8 |  |
| L03 | 2025-H2 | 340 | 8.3 | 50.5 | 0.4 |
| L03 | 2026-H1 | 358 | 8.1 | 49.1 | -0.3 |
| L03 | 2026-H2 | 200 | 10.1 | 48.0 | 2.0 |
| L04 | 2025-H1 | 262 | 11.1 | 52.9 |  |
| L04 | 2025-H2 | 280 | 10.4 | 52.0 | -0.7 |
| L04 | 2026-H1 | 259 | 11.3 | 49.9 | 1.0 |
| L04 | 2026-H2 | 211 | 9.4 | 51.5 | -1.9 |
| L05 | 2025-H1 | 307 | 9.4 | 59.2 |  |
| L05 | 2025-H2 | 311 | 9.2 | 55.7 | -0.2 |
| L05 | 2026-H1 | 288 | 10.2 | 55.8 | 1.0 |
| L05 | 2026-H2 | 192 | 10.4 | 57.6 | 0.2 |

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
| Polímeros Centroamericanos | 29.0 | 2.36 | 11.41 | 6,665 | 0.0 | 0.0 |
| Resinas del Golfo | 58.0 | 4.22 | 10.68 | 3,939 | 2,860,689 | 822,029 |

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
| L01 | Injection 1 | 55.4 | 54.7 | 52.1 | 3.12 | 4.11 |
| L02 | Injection 2 | 74.2 | 74.4 | 71.8 | 2.49 | 3.25 |
| L03 | Blow molding 1 | 71.2 | 71.5 | 68.9 | 1.61 | 2.03 |
| L04 | Blow molding 2 | 74.7 | 74.2 | 72.9 | 1.45 | 1.85 |
| L05 | Caps | 72.0 | 73.2 | 70.5 | 1.06 | 1.35 |

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
| L01 | 7 | 2025-03-19 | 2025-03-21 | 73.9 |
| L02 | 12 | 2025-01-06 | 2025-01-09 | 40.6 |
| L03 | 10 | 2025-03-27 | 2025-03-31 | 53.5 |
| L04 | 10 | 2025-02-10 | 2025-02-13 | 44.5 |
| L05 | 10 | 2025-07-09 | 2025-07-12 | 48.2 |

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
| L01 | Injection 1 | 54.0 | 5.08 | 0.96 | 110,514 | 2,196,905 |
| L03 | Blow molding 1 | 70.5 | 4.93 | 0.93 | 167,433 | 564,145 |
| L05 | Caps | 71.9 | 1.47 | 0.17 | 52,344 | 106,047 |
| L02 | Injection 2 | 73.4 | 2.95 | 1.04 | 110,712 | 53,831 |
| L04 | Blow molding 2 | 73.9 | 4.42 | 0.89 | 169,408 | 0.0 |

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
| PF-38G | PF-48G | 10.0 | 20 | 112.7 | 75.6 |
| PF-24G | PF-48G | 24.0 | 23 | 106.2 | 77.0 |
| PF-24G | PF-38G | 14.0 | 46 | 105.2 | 45.4 |
| PF-38G | PF-18G | 20.0 | 91 | 103.5 | 59.6 |
| PF-18G | PF-38G | 20.0 | 81 | 102.6 | 65.3 |
| PF-24G | PF-18G | 6.0 | 80 | 102.1 | 58.7 |
| PF-18G | PF-24G | 6.0 | 92 | 101.6 | 48.7 |
| PF-18G | PF-48G | 30.0 | 31 | 98.0 | 79.7 |
| PF-48G | PF-18G | 30.0 | 31 | 97.7 | 75.2 |
| PF-38G | PF-24G | 14.0 | 39 | 93.0 | 46.7 |
| PF-48G | PF-24G | 24.0 | 19 | 90.7 | 55.5 |
| PF-48G | PF-38G | 10.0 | 25 | 90.6 | 66.1 |
