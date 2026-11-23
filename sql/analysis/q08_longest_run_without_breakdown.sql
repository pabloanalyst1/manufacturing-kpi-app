-- Question: What is each line's longest streak of consecutive shifts without a breakdown?
-- Technique: gaps and islands: ROW_NUMBER() minus a running count of breakdown shifts identifies each streak.
WITH ordered AS (
    SELECT
        line_id,
        shift_start_order,
        shift_date,
        CASE WHEN breakdowns > 0 THEN 1 ELSE 0 END                      AS had_breakdown,
        SUM(CASE WHEN breakdowns > 0 THEN 1 ELSE 0 END) OVER (PARTITION BY line_id ORDER BY shift_start_order) AS breakdowns_so_far
    FROM (SELECT f.*, f.shift_date || f.shift AS shift_start_order FROM fct_shift_oee f)
),
streaks AS (
    SELECT line_id, breakdowns_so_far AS streak_id, COUNT(*) AS shifts, MIN(shift_date) AS from_date, MAX(shift_date) AS to_date
    FROM ordered
    WHERE had_breakdown = 0
    GROUP BY line_id, breakdowns_so_far
),
best AS (
    SELECT *, ROW_NUMBER() OVER (PARTITION BY line_id ORDER BY shifts DESC, from_date) AS rn FROM streaks
)
SELECT
    b.line_id,
    b.shifts                                                            AS longest_streak_shifts,
    b.from_date,
    b.to_date,
    ROUND(100.0 * (SELECT AVG(CASE WHEN breakdowns > 0 THEN 1.0 ELSE 0 END) FROM fct_shift_oee f WHERE f.line_id = b.line_id), 1) AS pct_shifts_with_breakdown
FROM best b
WHERE b.rn = 1
ORDER BY b.line_id;
