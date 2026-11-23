-- =====================================================================================
-- 04 MARTS - OEE
-- Numerators and denominators are stored, not only ratios, so the BI tool can re-aggregate
-- correctly: OEE = SUM(ideal_min_good) / SUM(planned_time_min), never an average of OEEs.
-- =====================================================================================

-- Daily OEE by line ---------------------------------------------------------------------
DROP TABLE IF EXISTS mart_oee_daily;
CREATE TABLE mart_oee_daily AS
SELECT
    f.shift_date,
    f.line_id,
    l.line_name,
    l.process,
    COUNT(*)                                                            AS shifts,
    ROUND(SUM(f.planned_time_min), 1)                                   AS planned_time_min,
    ROUND(SUM(f.run_time_min), 1)                                       AS run_time_min,
    ROUND(SUM(f.ideal_min_total), 1)                                    AS ideal_min_total,
    ROUND(SUM(f.ideal_min_good), 1)                                     AS ideal_min_good,
    SUM(f.total_units)                                                  AS total_units,
    SUM(f.good_units)                                                   AS good_units,
    SUM(f.scrap_units)                                                  AS scrap_units,
    ROUND(SUM(f.run_time_min) / SUM(f.planned_time_min), 4)             AS availability,
    ROUND(SUM(f.ideal_min_total) / SUM(f.run_time_min), 4)              AS performance,
    ROUND(1.0 * SUM(f.good_units) / SUM(f.total_units), 4)              AS quality,
    ROUND(SUM(f.ideal_min_good) / SUM(f.planned_time_min), 4)           AS oee
FROM fct_shift_oee f
JOIN dim_line l ON l.line_id = f.line_id
GROUP BY f.shift_date, f.line_id, l.line_name, l.process;


-- Monthly OEE by line ---------------------------------------------------------------------
DROP TABLE IF EXISTS mart_oee_monthly;
CREATE TABLE mart_oee_monthly AS
SELECT
    f.month_start,
    f.line_id,
    l.line_name,
    l.process,
    COUNT(*)                                                            AS shifts,
    ROUND(SUM(f.planned_time_min), 1)                                   AS planned_time_min,
    ROUND(SUM(f.run_time_min), 1)                                       AS run_time_min,
    ROUND(SUM(f.ideal_min_total), 1)                                    AS ideal_min_total,
    ROUND(SUM(f.ideal_min_good), 1)                                     AS ideal_min_good,
    SUM(f.good_units)                                                   AS good_units,
    SUM(f.scrap_units)                                                  AS scrap_units,
    ROUND(SUM(f.run_time_min) / SUM(f.planned_time_min), 4)             AS availability,
    ROUND(SUM(f.ideal_min_total) / SUM(f.run_time_min), 4)              AS performance,
    ROUND(1.0 * SUM(f.good_units) / SUM(f.total_units), 4)              AS quality,
    ROUND(SUM(f.ideal_min_good) / SUM(f.planned_time_min), 4)           AS oee,
    ROUND(prm.world_class_oee - SUM(f.ideal_min_good) / SUM(f.planned_time_min), 4) AS gap_to_world_class
FROM fct_shift_oee f
JOIN dim_line l ON l.line_id = f.line_id
CROSS JOIN ref_parameters prm
GROUP BY f.month_start, f.line_id, l.line_name, l.process, prm.world_class_oee;


-- OEE by line and shift --------------------------------------------------------------------
DROP TABLE IF EXISTS mart_oee_by_shift;
CREATE TABLE mart_oee_by_shift AS
SELECT
    f.line_id,
    l.line_name,
    f.shift,
    s.shift_name,
    COUNT(*)                                                            AS shifts,
    ROUND(SUM(f.planned_time_min), 1)                                   AS planned_time_min,
    ROUND(SUM(f.ideal_min_good), 1)                                     AS ideal_min_good,
    SUM(f.total_units)                                                  AS total_units,
    SUM(f.scrap_units)                                                  AS scrap_units,
    ROUND(SUM(f.run_time_min) / SUM(f.planned_time_min), 4)             AS availability,
    ROUND(SUM(f.ideal_min_total) / SUM(f.run_time_min), 4)              AS performance,
    ROUND(1.0 * SUM(f.good_units) / SUM(f.total_units), 4)              AS quality,
    ROUND(SUM(f.ideal_min_good) / SUM(f.planned_time_min), 4)           AS oee
FROM fct_shift_oee f
JOIN dim_line l  ON l.line_id = f.line_id
JOIN dim_shift s ON s.shift = f.shift
GROUP BY f.line_id, l.line_name, f.shift, s.shift_name;


-- The six big losses: from planned production time down to fully productive time -------------
-- Each line (and the whole plant) as a waterfall in minutes. Steps add up exactly:
-- planned = breakdowns + changeovers + other stops + minor stops + reduced speed + quality loss + fully productive
DROP TABLE IF EXISTS mart_oee_losses;
CREATE TABLE mart_oee_losses AS
WITH per_line AS (
    SELECT
        line_id,
        SUM(planned_time_min)                                           AS planned,
        SUM(breakdown_min)                                              AS breakdowns,
        SUM(changeover_min)                                             AS changeovers,
        SUM(availability_loss_min - breakdown_min - changeover_min)     AS other_stops,
        SUM(minor_stop_min)                                             AS minor_stops,
        SUM(run_time_min - minor_stop_min - ideal_min_total)            AS reduced_speed,
        SUM(ideal_min_total - ideal_min_good)                           AS quality_loss,
        SUM(ideal_min_good)                                             AS fully_productive
    FROM fct_shift_oee
    GROUP BY line_id
),
with_plant AS (
    SELECT * FROM per_line
    UNION ALL
    SELECT 'Plant', SUM(planned), SUM(breakdowns), SUM(changeovers), SUM(other_stops), SUM(minor_stops),
           SUM(reduced_speed), SUM(quality_loss), SUM(fully_productive)
    FROM per_line
),
steps AS (
    SELECT line_id, 1 AS step_order, 'Breakdowns' AS loss, 'Availability' AS oee_factor, breakdowns AS minutes, planned FROM with_plant
    UNION ALL SELECT line_id, 2, 'Changeovers', 'Availability', changeovers, planned FROM with_plant
    UNION ALL SELECT line_id, 3, 'Other stops (material, quality hold, staff, utilities)', 'Availability', other_stops, planned FROM with_plant
    UNION ALL SELECT line_id, 4, 'Minor stops (< 5 min)', 'Performance', minor_stops, planned FROM with_plant
    UNION ALL SELECT line_id, 5, 'Reduced speed', 'Performance', reduced_speed, planned FROM with_plant
    UNION ALL SELECT line_id, 6, 'Scrap', 'Quality', quality_loss, planned FROM with_plant
    UNION ALL SELECT line_id, 7, 'Fully productive time (OEE)', 'OEE', fully_productive, planned FROM with_plant
)
SELECT
    line_id,
    step_order,
    loss,
    oee_factor,
    ROUND(minutes / 60.0, 1)                                            AS hours,
    ROUND(minutes / planned, 4)                                         AS share_of_planned_time
FROM steps
ORDER BY line_id, step_order;


-- What the losses are worth -----------------------------------------------------------------
DROP TABLE IF EXISTS mart_loss_value;
CREATE TABLE mart_loss_value AS
WITH span AS (
    SELECT (JULIANDAY(MAX(shift_date)) - JULIANDAY(MIN(shift_date)) + 1) / 365.25 AS years FROM fct_shift_oee
)
SELECT
    f.line_id,
    l.line_name,
    ROUND(SUM(f.ideal_min_good) / SUM(f.planned_time_min), 4)           AS oee,
    ROUND(SUM(f.planned_time_min) / 60.0, 0)                            AS planned_hours,
    ROUND(SUM(f.lost_margin_gtq), 0)                                    AS lost_margin_gtq,
    ROUND(SUM(f.lost_margin_gtq) / s.years, 0)                          AS lost_margin_gtq_per_year,
    ROUND(SUM(f.scrap_cost_gtq), 0)                                     AS scrap_cost_gtq,
    ROUND(SUM(f.scrap_cost_gtq) / s.years, 0)                           AS scrap_cost_gtq_per_year,
    -- contribution margin of one extra OEE point (1% of planned time turned into good output), per year
    ROUND(0.01 * SUM(f.planned_time_min * COALESCE(f.margin_per_ideal_min, 0)) / s.years, 0) AS margin_per_oee_point_per_year
FROM fct_shift_oee f
JOIN dim_line l ON l.line_id = f.line_id
CROSS JOIN span s
GROUP BY f.line_id, l.line_name, s.years;
