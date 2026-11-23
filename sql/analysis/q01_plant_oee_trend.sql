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
