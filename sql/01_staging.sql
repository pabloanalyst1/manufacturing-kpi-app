-- =====================================================================================
-- 01 STAGING: clean the flattened MES extract and the ERP resin lots.
-- Fixes: interim copies of a report (keep the final one), line ids typed five ways,
-- counts stored as text with thousands separators, SKUs in lower case, legacy and
-- inconsistent downtime codes, two timestamp formats, stops logged twice, stops that
-- end before they start or run past the end of the shift, 32-bit counter overflows,
-- supplier names spelled three ways and mixed date formats.
-- Nothing is silently dropped: rejected rows go to stg_rejected_* with a reason.
-- =====================================================================================

-- Which copy of each shift report to keep -------------------------------------------
-- The MES sometimes sends an interim report before the shift closes; the last one wins.
DROP TABLE IF EXISTS stg_report_copies;
CREATE TABLE stg_report_copies AS
SELECT
    TRIM(report_id)                                                     AS report_id,
    ingested_at,
    ROW_NUMBER() OVER (PARTITION BY TRIM(report_id) ORDER BY ingested_at DESC) AS copy_rank,
    COUNT(*) OVER (PARTITION BY TRIM(report_id))                        AS copies
FROM raw_shift_reports;

CREATE INDEX ix_stg_report_copies ON stg_report_copies (report_id, ingested_at);

DROP VIEW IF EXISTS v_latest_copy;
CREATE VIEW v_latest_copy AS
SELECT report_id, ingested_at, copies FROM stg_report_copies WHERE copy_rank = 1;


-- Production by SKU (final copy only) ---------------------------------------------
DROP TABLE IF EXISTS stg_production_all;
CREATE TABLE stg_production_all AS
WITH scrap AS (
    SELECT TRIM(report_id) AS report_id, ingested_at, item_seq,
           SUM(CAST(REPLACE(CAST(units_raw AS TEXT), ',', '') AS INTEGER)) AS scrap_units
    FROM raw_scrap
    GROUP BY 1, 2, 3
)
SELECT
    l.report_id,
    UPPER(TRIM(p.sku_raw))                                              AS sku,
    -- v1 sends "180,000" as text, v2 sends 180000 as a number
    CAST(REPLACE(CAST(p.good_raw AS TEXT), ',', '') AS INTEGER)         AS good_units,
    COALESCE(s.scrap_units, 0)                                          AS scrap_units
FROM raw_production p
JOIN v_latest_copy l ON l.report_id = TRIM(p.report_id) AND l.ingested_at = p.ingested_at
LEFT JOIN scrap s ON s.report_id = l.report_id AND s.ingested_at = p.ingested_at AND s.item_seq = p.item_seq;


-- Shift reports ----------------------------------------------------------------------
DROP TABLE IF EXISTS stg_shift_reports_all;
CREATE TABLE stg_shift_reports_all AS
WITH typed AS (
    SELECT
        l.report_id,
        r.ingested_at,
        l.copies,
        CAST(r.schema_version AS INTEGER)                               AS schema_version,
        -- 'Línea 1', 'LINE 1', 'L-01', 'l01 ', 'L01' -> 'L01'
        -- (SQLite's UPPER only changes ASCII letters, hence both spellings of LÍNEA)
        'L' || printf('%02d', CAST(
            REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(
                UPPER(TRIM(r.line_raw)), 'LíNEA', ''), 'LÍNEA', ''), 'LINEA', ''), 'LINE', ''), 'L', ''), '-', '')
            AS INTEGER))                                                AS line_id,
        DATE(r.shift_date)                                              AS shift_date,
        UPPER(TRIM(r.shift))                                            AS shift,
        DATETIME(REPLACE(TRIM(r.shift_start), 'T', ' '))                AS shift_start,
        CAST(r.shift_minutes AS INTEGER)                                AS shift_minutes,
        TRIM(r.supervisor)                                              AS supervisor,
        CAST(r.operators AS INTEGER)                                    AS operators,
        NULLIF(TRIM(r.resin_lot), '')                                   AS resin_lot
    FROM raw_shift_reports r
    JOIN v_latest_copy l ON l.report_id = TRIM(r.report_id) AND l.ingested_at = r.ingested_at
),
overflow AS (
    -- more units than the line could make at 120% of its ideal rate = a counter error
    SELECT DISTINCT p.report_id
    FROM stg_production_all p
    JOIN typed t ON t.report_id = p.report_id
    JOIN ref_products pr ON pr.sku = p.sku
    CROSS JOIN ref_parameters prm
    WHERE p.good_units + p.scrap_units > prm.max_rate_tolerance * t.shift_minutes * pr.ideal_rate_per_min
)
SELECT
    t.*,
    DATETIME(t.shift_start, '+' || t.shift_minutes || ' minutes')       AS shift_end,
    CASE WHEN o.report_id IS NOT NULL THEN 'Counter overflow' END       AS reject_reason
FROM typed t
LEFT JOIN overflow o ON o.report_id = t.report_id;

DROP TABLE IF EXISTS stg_rejected_shift_reports;
CREATE TABLE stg_rejected_shift_reports AS
SELECT report_id, line_id, shift_date, shift, reject_reason FROM stg_shift_reports_all WHERE reject_reason IS NOT NULL;

DROP TABLE IF EXISTS stg_shift_reports;
CREATE TABLE stg_shift_reports AS
SELECT report_id, line_id, shift_date, shift, shift_start, shift_end, shift_minutes, schema_version,
       supervisor, operators, resin_lot, copies
FROM stg_shift_reports_all
WHERE reject_reason IS NULL;

CREATE UNIQUE INDEX ux_stg_shift_reports ON stg_shift_reports (report_id);

DROP TABLE IF EXISTS stg_production;
CREATE TABLE stg_production AS
SELECT p.report_id, p.sku, SUM(p.good_units) AS good_units, SUM(p.scrap_units) AS scrap_units
FROM stg_production_all p
JOIN stg_shift_reports r ON r.report_id = p.report_id
GROUP BY p.report_id, p.sku;

CREATE UNIQUE INDEX ux_stg_production ON stg_production (report_id, sku);

DROP TABLE stg_production_all;
DROP TABLE stg_shift_reports_all;


-- Scrap by defect ---------------------------------------------------------------------
DROP TABLE IF EXISTS stg_scrap;
CREATE TABLE stg_scrap AS
SELECT
    l.report_id,
    UPPER(TRIM(s.sku_raw))                                              AS sku,
    TRIM(s.defect_raw)                                                  AS defect,
    SUM(CAST(REPLACE(CAST(s.units_raw AS TEXT), ',', '') AS INTEGER))  AS scrap_units
FROM raw_scrap s
JOIN v_latest_copy l ON l.report_id = TRIM(s.report_id) AND l.ingested_at = s.ingested_at
JOIN stg_shift_reports r ON r.report_id = l.report_id
GROUP BY 1, 2, 3;


-- Downtime events -------------------------------------------------------------------
DROP TABLE IF EXISTS stg_downtime_all;
CREATE TABLE stg_downtime_all AS
WITH typed AS (
    SELECT
        l.report_id,
        d.event_seq,
        UPPER(TRIM(d.reason_raw))                                       AS reason_clean,
        -- v1 terminals send 'dd/mm/yyyy hh:mm', v2 terminals ISO 8601
        CASE WHEN TRIM(d.start_raw) LIKE '__/__/____ __:__'
             THEN SUBSTR(d.start_raw, 7, 4) || '-' || SUBSTR(d.start_raw, 4, 2) || '-' || SUBSTR(d.start_raw, 1, 2)
                  || ' ' || SUBSTR(d.start_raw, 12, 5) || ':00'
             ELSE DATETIME(REPLACE(TRIM(d.start_raw), 'T', ' '))
        END                                                             AS start_ts,
        DATETIME(REPLACE(TRIM(d.end_raw), 'T', ' '))                    AS end_raw_ts,
        CAST(d.minutes_raw AS REAL)                                     AS minutes_raw,
        UPPER(TRIM(d.from_sku))                                         AS from_sku,
        UPPER(TRIM(d.to_sku))                                           AS to_sku
    FROM raw_downtime_events d
    JOIN v_latest_copy l ON l.report_id = TRIM(d.report_id) AND l.ingested_at = d.ingested_at
),
coded AS (
    SELECT
        t.*,
        -- current code, legacy v1 code, or unclassified
        COALESCE(cur.reason_code, leg.reason_code, 'UNK')               AS reason_code,
        -- v1 sends a duration instead of an end time
        COALESCE(t.end_raw_ts, DATETIME(t.start_ts, '+' || t.minutes_raw || ' minutes')) AS end_ts
    FROM typed t
    LEFT JOIN ref_downtime_reasons cur ON cur.reason_code = t.reason_clean
    LEFT JOIN ref_downtime_reasons leg ON leg.legacy_code = t.reason_clean
)
SELECT
    c.report_id,
    c.event_seq,
    c.reason_code,
    c.reason_clean                                                      AS reason_as_received,
    c.start_ts,
    c.end_ts,
    r.shift_start,
    r.shift_end,
    c.from_sku,
    c.to_sku,
    -- the same stop logged twice by the terminal
    ROW_NUMBER() OVER (PARTITION BY c.report_id, c.reason_code, c.start_ts, c.end_ts ORDER BY c.event_seq) AS copy_number,
    CASE
        WHEN c.start_ts IS NULL OR c.end_ts IS NULL THEN 'Missing timestamp'
        WHEN c.end_ts < c.start_ts THEN 'Ends before it starts'
        WHEN c.start_ts >= r.shift_end OR c.start_ts < DATETIME(r.shift_start, '-1 minutes') THEN 'Outside the shift'
    END                                                                 AS reject_reason
FROM coded c
JOIN stg_shift_reports r ON r.report_id = c.report_id;

DROP TABLE IF EXISTS stg_rejected_downtime_events;
CREATE TABLE stg_rejected_downtime_events AS
SELECT report_id, event_seq, reason_code, start_ts, end_ts, reject_reason
FROM stg_downtime_all
WHERE copy_number = 1 AND reject_reason IS NOT NULL;

DROP TABLE IF EXISTS stg_downtime_events;
CREATE TABLE stg_downtime_events AS
SELECT
    report_id,
    event_seq,
    reason_code,
    reason_as_received,
    MAX(start_ts, shift_start)                                          AS start_ts,
    -- a stop that runs past the end of the shift is clipped; the next shift reports its own part
    MIN(end_ts, shift_end)                                              AS end_ts,
    CASE WHEN end_ts > shift_end THEN 1 ELSE 0 END                      AS is_clipped,
    ROUND((JULIANDAY(MIN(end_ts, shift_end)) - JULIANDAY(MAX(start_ts, shift_start))) * 1440, 2) AS duration_min,
    from_sku,
    to_sku
FROM stg_downtime_all
WHERE copy_number = 1 AND reject_reason IS NULL;

CREATE INDEX ix_stg_downtime_report ON stg_downtime_events (report_id, start_ts);

-- duplicates removed, kept for the quality checks
DROP TABLE IF EXISTS stg_duplicate_downtime_events;
CREATE TABLE stg_duplicate_downtime_events AS
SELECT report_id, event_seq, reason_code, start_ts FROM stg_downtime_all WHERE copy_number > 1;

DROP TABLE stg_downtime_all;


-- ERP resin lots ----------------------------------------------------------------------
DROP TABLE IF EXISTS stg_resin_lots;
CREATE TABLE stg_resin_lots AS
WITH typed AS (
    SELECT
        TRIM(lot_id)                                                    AS lot_id,
        UPPER(TRIM(resin_type))                                         AS resin_type,
        CASE
            WHEN UPPER(supplier) LIKE '%GOLFO%' THEN 'Resinas del Golfo'
            WHEN UPPER(supplier) LIKE '%CENTROAMERICANOS%' THEN 'Polímeros Centroamericanos'
            ELSE TRIM(supplier)
        END                                                             AS supplier,
        CASE WHEN received_date LIKE '__/__/____'
             THEN SUBSTR(received_date, 7, 4) || '-' || SUBSTR(received_date, 4, 2) || '-' || SUBSTR(received_date, 1, 2)
             ELSE DATE(received_date)
        END                                                             AS received_date,
        CAST(price_gtq_per_kg AS REAL)                                  AS price_gtq_per_kg,
        CAST(moisture_ppm AS INTEGER)                                   AS moisture_ppm,
        ROW_NUMBER() OVER (PARTITION BY TRIM(lot_id) ORDER BY rowid)    AS copy_number
    FROM raw_resin_lots
)
SELECT lot_id, resin_type, supplier, received_date, price_gtq_per_kg, moisture_ppm
FROM typed
WHERE copy_number = 1;

CREATE UNIQUE INDEX ux_stg_resin_lots ON stg_resin_lots (lot_id);
