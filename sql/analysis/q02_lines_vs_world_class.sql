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
