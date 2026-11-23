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
