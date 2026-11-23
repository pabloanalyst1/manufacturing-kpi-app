-- =====================================================================================
-- 05 MARTS - DOWNTIME, RELIABILITY AND CHANGEOVERS
-- =====================================================================================

-- Pareto of unplanned downtime (stops of 5+ minutes) ---------------------------------------
DROP TABLE IF EXISTS mart_downtime_pareto;
CREATE TABLE mart_downtime_pareto AS
WITH by_reason AS (
    SELECT reason_code, reason, category, COUNT(*) AS stops, SUM(duration_min) AS minutes
    FROM fct_downtime_events
    WHERE loss_bucket = 'Availability loss'
    GROUP BY reason_code, reason, category
)
SELECT
    RANK() OVER (ORDER BY minutes DESC)                                 AS rank,
    reason_code,
    reason,
    category,
    stops,
    ROUND(minutes / 60.0, 1)                                            AS hours,
    ROUND(minutes / stops, 1)                                           AS avg_minutes,
    ROUND(minutes / SUM(minutes) OVER (), 4)                            AS share,
    ROUND(SUM(minutes) OVER (ORDER BY minutes DESC ROWS UNBOUNDED PRECEDING) / SUM(minutes) OVER (), 4) AS cumulative_share
FROM by_reason
ORDER BY minutes DESC;


-- Downtime by line, month and category (stacked charts in the BI tool) -----------------------
DROP TABLE IF EXISTS mart_downtime_monthly;
CREATE TABLE mart_downtime_monthly AS
SELECT
    STRFTIME('%Y-%m-01', shift_date)                                    AS month_start,
    line_id,
    category,
    loss_bucket,
    COUNT(*)                                                            AS stops,
    ROUND(SUM(duration_min), 1)                                         AS minutes
FROM fct_downtime_events
GROUP BY 1, 2, 3, 4;


-- Reliability: MTBF and MTTR by line and quarter ---------------------------------------------
-- MTBF = run hours / breakdowns. MTTR = breakdown minutes / breakdowns.
DROP TABLE IF EXISTS mart_reliability;
CREATE TABLE mart_reliability AS
SELECT
    f.line_id,
    l.line_name,
    d.quarter,
    ROUND(SUM(f.run_time_min) / 60.0, 1)                                AS run_hours,
    SUM(f.breakdowns)                                                   AS breakdowns,
    ROUND(SUM(f.breakdown_min) / 60.0, 1)                               AS breakdown_hours,
    ROUND(SUM(f.run_time_min) / 60.0 / NULLIF(SUM(f.breakdowns), 0), 2) AS mtbf_hours,
    ROUND(SUM(f.breakdown_min) / NULLIF(SUM(f.breakdowns), 0), 1)       AS mttr_minutes,
    ROUND(SUM(f.breakdown_min) / SUM(f.planned_time_min), 4)            AS breakdown_share_of_planned
FROM fct_shift_oee f
JOIN dim_line l ON l.line_id = f.line_id
JOIN dim_date d ON d.date_day = f.shift_date
GROUP BY f.line_id, l.line_name, d.quarter;


-- Changeovers by line and month ----------------------------------------------------------------
DROP TABLE IF EXISTS mart_changeovers_monthly;
CREATE TABLE mart_changeovers_monthly AS
SELECT
    STRFTIME('%Y-%m-01', e.shift_date)                                  AS month_start,
    e.line_id,
    l.smed_group,
    e.smed_period,
    COUNT(*)                                                            AS changeovers,
    ROUND(SUM(e.duration_min), 1)                                       AS changeover_minutes,
    ROUND(AVG(e.duration_min), 1)                                       AS avg_changeover_minutes
FROM fct_downtime_events e
JOIN dim_line l ON l.line_id = e.line_id
WHERE e.category = 'Changeover'
GROUP BY 1, 2, 3, 4;


-- SMED program: pilot vs comparison lines, before vs after ---------------------------------------
DROP TABLE IF EXISTS mart_smed_evaluation;
CREATE TABLE mart_smed_evaluation AS
SELECT
    f.smed_group,
    f.smed_period,
    COUNT(DISTINCT f.line_id)                                           AS lines,
    COUNT(*)                                                            AS shifts,
    SUM(f.changeovers)                                                  AS changeovers,
    ROUND(SUM(f.changeover_min) / NULLIF(SUM(f.changeovers), 0), 1)     AS avg_changeover_minutes,
    ROUND(SUM(f.changeover_min) / SUM(f.planned_time_min), 4)           AS changeover_share_of_planned,
    ROUND(SUM(f.run_time_min) / SUM(f.planned_time_min), 4)             AS availability,
    ROUND(SUM(f.ideal_min_good) / SUM(f.planned_time_min), 4)           AS oee
FROM fct_shift_oee f
WHERE f.smed_group IN ('Pilot', 'Comparison')
GROUP BY f.smed_group, f.smed_period;


-- Changeover matrix: average minutes from one SKU to another ------------------------------------
DROP TABLE IF EXISTS mart_changeover_matrix;
CREATE TABLE mart_changeover_matrix AS
SELECT
    l.process,
    e.smed_period,
    e.from_sku,
    e.to_sku,
    COUNT(*)                                                            AS changeovers,
    ROUND(AVG(e.duration_min), 1)                                       AS avg_minutes
FROM fct_downtime_events e
JOIN dim_line l ON l.line_id = e.line_id
WHERE e.category = 'Changeover' AND e.from_sku IS NOT NULL
GROUP BY 1, 2, 3, 4;
