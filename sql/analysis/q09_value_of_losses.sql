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
