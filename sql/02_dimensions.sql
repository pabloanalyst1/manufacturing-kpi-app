-- =====================================================================================
-- 02 DIMENSIONS: lines, products, downtime reasons, resin lots, shifts and a calendar.
-- =====================================================================================

DROP TABLE IF EXISTS dim_line;
CREATE TABLE dim_line AS
SELECT line_id, line_name, process, machine, install_year, smed_group
FROM ref_lines;

CREATE UNIQUE INDEX ux_dim_line ON dim_line (line_id);


DROP TABLE IF EXISTS dim_product;
CREATE TABLE dim_product AS
SELECT
    sku,
    description,
    process,
    ideal_rate_per_min,
    1.0 / ideal_rate_per_min                                            AS ideal_cycle_min,
    unit_weight_g,
    unit_cost_gtq,
    unit_margin_gtq
FROM ref_products;

CREATE UNIQUE INDEX ux_dim_product ON dim_product (sku);


-- Reason codes, plus a bucket for stops the operator did not classify
DROP TABLE IF EXISTS dim_downtime_reason;
CREATE TABLE dim_downtime_reason AS
SELECT reason_code, description, category, is_planned,
       CASE WHEN category = 'Breakdown' THEN 1 ELSE 0 END               AS is_breakdown
FROM ref_downtime_reasons
UNION ALL
SELECT 'UNK', 'Unclassified (no reason entered)', 'Unclassified', 0, 0;

CREATE UNIQUE INDEX ux_dim_downtime_reason ON dim_downtime_reason (reason_code);


DROP TABLE IF EXISTS dim_resin_lot;
CREATE TABLE dim_resin_lot AS
SELECT lot_id, resin_type, supplier, received_date, price_gtq_per_kg, moisture_ppm
FROM stg_resin_lots
UNION ALL
SELECT 'UNKNOWN', NULL, 'Unknown (lot not scanned)', NULL, NULL, NULL;

CREATE UNIQUE INDEX ux_dim_resin_lot ON dim_resin_lot (lot_id);


DROP TABLE IF EXISTS dim_shift;
CREATE TABLE dim_shift (shift TEXT PRIMARY KEY, shift_name TEXT, start_time TEXT, end_time TEXT);
INSERT INTO dim_shift VALUES
    ('A', 'Morning', '06:00', '14:00'),
    ('B', 'Afternoon', '14:00', '22:00'),
    ('C', 'Night', '22:00', '06:00');


-- Calendar (recursive CTE) --------------------------------------------------------------
DROP TABLE IF EXISTS dim_date;
CREATE TABLE dim_date AS
WITH RECURSIVE days(d) AS (
    SELECT DATE(period_start) FROM ref_parameters
    UNION ALL
    SELECT DATE(d, '+1 day') FROM days WHERE d < (SELECT DATE(period_end) FROM ref_parameters)
)
SELECT
    d                                                                   AS date_day,
    CAST(STRFTIME('%Y', d) AS INTEGER)                                  AS year,
    CAST(STRFTIME('%m', d) AS INTEGER)                                  AS month,
    STRFTIME('%Y-%m-01', d)                                             AS month_start,
    STRFTIME('%Y', d) || '-Q' || ((CAST(STRFTIME('%m', d) AS INTEGER) + 2) / 3) AS quarter,
    -- ISO-like week start (Monday)
    DATE(d, '-' || ((CAST(STRFTIME('%w', d) AS INTEGER) + 6) % 7) || ' days') AS week_start,
    CASE STRFTIME('%w', d) WHEN '0' THEN 'Sun' WHEN '1' THEN 'Mon' WHEN '2' THEN 'Tue' WHEN '3' THEN 'Wed'
                           WHEN '4' THEN 'Thu' WHEN '5' THEN 'Fri' ELSE 'Sat' END AS day_name,
    -- Guatemala's rainy season: May to October
    CASE WHEN CAST(STRFTIME('%m', d) AS INTEGER) BETWEEN 5 AND 10 THEN 1 ELSE 0 END AS is_rainy_season
FROM days;

CREATE UNIQUE INDEX ux_dim_date ON dim_date (date_day);
