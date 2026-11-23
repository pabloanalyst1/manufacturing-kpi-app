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
