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
