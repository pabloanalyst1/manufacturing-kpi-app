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
