-- =====================================================================================
-- 06 MARTS - SCRAP, PRODUCTION AND KPI SUMMARY
-- =====================================================================================

-- Scrap by defect ---------------------------------------------------------------------------
DROP TABLE IF EXISTS mart_scrap_by_defect;
CREATE TABLE mart_scrap_by_defect AS
WITH by_defect AS (
    SELECT
        l.process,
        r.line_id,
        s.defect,
        SUM(s.scrap_units)                                              AS scrap_units,
        SUM(s.scrap_units * p.unit_cost_gtq)                            AS scrap_cost_gtq
    FROM stg_scrap s
    JOIN stg_shift_reports r ON r.report_id = s.report_id
    JOIN dim_line l          ON l.line_id = r.line_id
    JOIN dim_product p       ON p.sku = s.sku
    GROUP BY 1, 2, 3
)
SELECT
    process,
    line_id,
    defect,
    scrap_units,
    ROUND(scrap_cost_gtq, 0)                                            AS scrap_cost_gtq,
    ROUND(1.0 * scrap_units / SUM(scrap_units) OVER (PARTITION BY line_id), 4) AS share_of_line_scrap
FROM by_defect
ORDER BY line_id, scrap_units DESC;


-- Resin supplier vs scrap (lines that use resin lots) -------------------------------------------
-- Is the cheaper resin really cheaper once its extra scrap is paid for?
DROP TABLE IF EXISTS mart_scrap_by_supplier;
CREATE TABLE mart_scrap_by_supplier AS
WITH splay AS (
    SELECT s.report_id, SUM(s.scrap_units) AS splay_units
    FROM stg_scrap s WHERE s.defect = 'Splay / bubbles' GROUP BY s.report_id
)
SELECT
    f.process,
    r.supplier,
    COUNT(DISTINCT f.resin_lot)                                         AS lots,
    COUNT(*)                                                            AS shifts,
    SUM(f.total_units)                                                  AS total_units,
    SUM(f.scrap_units)                                                  AS scrap_units,
    ROUND(1.0 * SUM(f.scrap_units) / SUM(f.total_units), 4)             AS scrap_rate,
    ROUND(1.0 * SUM(COALESCE(sp.splay_units, 0)) / SUM(f.total_units), 4) AS splay_rate,
    ROUND(AVG(r.moisture_ppm), 0)                                       AS avg_moisture_ppm,
    ROUND(SUM(f.resin_kg) / 1000.0, 1)                                  AS resin_tonnes,
    ROUND(SUM(f.resin_kg * r.price_gtq_per_kg) / SUM(f.resin_kg), 2)    AS avg_price_gtq_per_kg,
    ROUND(SUM(f.resin_kg * r.price_gtq_per_kg), 0)                      AS resin_cost_gtq,
    ROUND(SUM(f.scrap_cost_gtq), 0)                                     AS scrap_cost_gtq
FROM fct_shift_oee f
JOIN dim_resin_lot r ON r.lot_id = f.resin_lot
LEFT JOIN splay sp   ON sp.report_id = f.report_id
WHERE f.resin_lot IS NOT NULL
GROUP BY f.process, r.supplier;


-- What drives scrap: shift, start-up after a changeover, rainy season ---------------------------
DROP TABLE IF EXISTS mart_scrap_drivers;
CREATE TABLE mart_scrap_drivers AS
WITH prod AS (
    SELECT p.*, l.process, d.is_rainy_season
    FROM fct_production p
    JOIN dim_line l ON l.line_id = p.line_id
    JOIN dim_date d ON d.date_day = p.shift_date
)
SELECT process, 'Shift' AS driver, shift AS level, SUM(total_units) AS total_units, SUM(scrap_units) AS scrap_units,
       ROUND(1.0 * SUM(scrap_units) / SUM(total_units), 4) AS scrap_rate
FROM prod GROUP BY process, shift
UNION ALL
SELECT process, 'After a changeover', CASE WHEN started_after_changeover = 1 THEN 'Yes' ELSE 'No' END,
       SUM(total_units), SUM(scrap_units), ROUND(1.0 * SUM(scrap_units) / SUM(total_units), 4)
FROM prod GROUP BY process, started_after_changeover
UNION ALL
SELECT process, 'Rainy season', CASE WHEN is_rainy_season = 1 THEN 'Yes (May-Oct)' ELSE 'No' END,
       SUM(total_units), SUM(scrap_units), ROUND(1.0 * SUM(scrap_units) / SUM(total_units), 4)
FROM prod GROUP BY process, is_rainy_season;


-- Production by line, SKU and month --------------------------------------------------------------
DROP TABLE IF EXISTS mart_production_monthly;
CREATE TABLE mart_production_monthly AS
SELECT
    STRFTIME('%Y-%m-01', p.shift_date)                                  AS month_start,
    p.line_id,
    p.sku,
    d.description,
    COUNT(*)                                                            AS shifts_run,
    SUM(p.total_units)                                                  AS total_units,
    SUM(p.good_units)                                                   AS good_units,
    SUM(p.scrap_units)                                                  AS scrap_units,
    ROUND(SUM(p.scrap_cost_gtq), 0)                                     AS scrap_cost_gtq,
    ROUND(SUM(p.good_units * d.unit_margin_gtq), 0)                     AS contribution_margin_gtq
FROM fct_production p
JOIN dim_product d ON d.sku = p.sku
GROUP BY 1, 2, 3, 4;


-- One row per line-shift, for the app and the BI tool ------------------------------------------------
DROP TABLE IF EXISTS mart_shift_detail;
CREATE TABLE mart_shift_detail AS
SELECT
    f.report_id, f.shift_date, f.month_start, f.shift, f.line_id, l.line_name, f.process, f.supervisor,
    f.resin_lot, r.supplier AS resin_supplier, f.smed_group, f.smed_period,
    f.planned_time_min, f.run_time_min, f.availability_loss_min, f.breakdown_min, f.changeover_min,
    f.minor_stop_min, f.breakdowns, f.changeovers,
    f.total_units, f.good_units, f.scrap_units, ROUND(f.ideal_min_total, 2) AS ideal_min_total,
    ROUND(f.ideal_min_good, 2) AS ideal_min_good, f.scrap_cost_gtq, f.lost_margin_gtq,
    f.availability, f.performance, f.quality, f.oee
FROM fct_shift_oee f
JOIN dim_line l           ON l.line_id = f.line_id
LEFT JOIN dim_resin_lot r ON r.lot_id = f.resin_lot;


-- KPI summary: year to date vs the same period last year -------------------------------------------
DROP TABLE IF EXISTS mart_kpi_summary;
CREATE TABLE mart_kpi_summary AS
WITH prm AS (
    SELECT CAST(STRFTIME('%Y', period_end) AS INTEGER) AS cy, STRFTIME('%m-%d', period_end) AS md FROM ref_parameters
),
tagged AS (
    SELECT f.*,
           CASE WHEN STRFTIME('%m-%d', f.shift_date) > prm.md THEN NULL
                WHEN CAST(STRFTIME('%Y', f.shift_date) AS INTEGER) = prm.cy THEN 'cur'
                WHEN CAST(STRFTIME('%Y', f.shift_date) AS INTEGER) = prm.cy - 1 THEN 'pri'
           END AS period
    FROM fct_shift_oee f CROSS JOIN prm
),
a AS (
    SELECT
        period,
        SUM(planned_time_min) AS planned, SUM(run_time_min) AS run, SUM(ideal_min_total) AS ideal_total,
        SUM(ideal_min_good) AS ideal_good, SUM(total_units) AS total, SUM(good_units) AS good,
        SUM(scrap_units) AS scrap, SUM(scrap_cost_gtq) AS scrap_cost, SUM(availability_loss_min) AS unplanned,
        SUM(breakdowns) AS breakdowns, SUM(breakdown_min) AS breakdown_min, SUM(changeovers) AS changeovers,
        SUM(changeover_min) AS changeover_min, SUM(lost_margin_gtq) AS lost_margin
    FROM tagged WHERE period IS NOT NULL GROUP BY period
),
kpis AS (
    SELECT period, 1 AS ord, 'OEE' AS kpi, 'ratio' AS unit, ideal_good / planned AS value FROM a
    UNION ALL SELECT period, 2, 'Availability', 'ratio', run / planned FROM a
    UNION ALL SELECT period, 3, 'Performance', 'ratio', ideal_total / run FROM a
    UNION ALL SELECT period, 4, 'Quality', 'ratio', 1.0 * good / total FROM a
    UNION ALL SELECT period, 5, 'Good units', 'millions', good / 1e6 FROM a
    UNION ALL SELECT period, 6, 'Scrap rate', 'ratio', 1.0 * scrap / total FROM a
    UNION ALL SELECT period, 7, 'Scrap cost', 'GTQ', scrap_cost FROM a
    UNION ALL SELECT period, 8, 'Unplanned downtime', 'hours', unplanned / 60 FROM a
    UNION ALL SELECT period, 9, 'MTBF', 'hours', run / 60.0 / breakdowns FROM a
    UNION ALL SELECT period, 10, 'MTTR', 'minutes', breakdown_min / breakdowns FROM a
    UNION ALL SELECT period, 11, 'Average changeover', 'minutes', changeover_min / changeovers FROM a
    UNION ALL SELECT period, 12, 'Margin lost vs 100% OEE', 'GTQ', lost_margin FROM a
)
SELECT
    ord,
    kpi,
    unit,
    (SELECT cy FROM prm) || ' YTD'                                     AS current_period,
    ROUND(MAX(CASE WHEN period = 'cur' THEN value END), 4)              AS current_value,
    ROUND(MAX(CASE WHEN period = 'pri' THEN value END), 4)              AS prior_year_value,
    ROUND(MAX(CASE WHEN period = 'cur' THEN value END) - MAX(CASE WHEN period = 'pri' THEN value END), 4) AS change
FROM kpis
GROUP BY ord, kpi, unit
ORDER BY ord;
