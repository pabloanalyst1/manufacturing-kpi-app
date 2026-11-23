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
