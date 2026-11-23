-- =====================================================================================
-- 03 FACTS: downtime events, production by SKU and one row per line-shift with OEE.
--
-- OEE definitions (standard Nakajima / oee.com convention):
--   Planned production time = shift time - planned stops (breaks, planned maintenance, no orders)
--   Availability loss       = unplanned stops of 5 minutes or more (breakdowns, changeovers, ...)
--   Run time                = planned production time - availability loss
--   Availability            = run time / planned production time
--   Performance             = ideal time of every unit made / run time
--                             (absorbs minor stops < 5 min and running below the ideal rate)
--   Quality                 = good units / total units
--   OEE                     = A x P x Q = ideal time of the GOOD units / planned production time
-- A shift can make several SKUs with different ideal rates, so "ideal time" is summed per SKU.
-- =====================================================================================

-- Downtime events ----------------------------------------------------------------------
DROP TABLE IF EXISTS fct_downtime_events;
CREATE TABLE fct_downtime_events AS
SELECT
    e.report_id,
    e.event_seq,
    r.line_id,
    r.shift_date,
    r.shift,
    e.reason_code,
    dr.description                                                      AS reason,
    dr.category,
    dr.is_planned,
    dr.is_breakdown,
    e.start_ts,
    e.end_ts,
    e.duration_min,
    e.is_clipped,
    CASE
        WHEN dr.is_planned = 1 THEN 'Planned stop'
        WHEN e.duration_min < prm.minor_stop_threshold_min THEN 'Minor stop'
        ELSE 'Availability loss'
    END                                                                 AS loss_bucket,
    e.from_sku,
    e.to_sku,
    CASE WHEN r.shift_date >= prm.smed_start THEN 'Post' ELSE 'Pre' END AS smed_period
FROM stg_downtime_events e
JOIN stg_shift_reports r     ON r.report_id = e.report_id
JOIN dim_downtime_reason dr  ON dr.reason_code = e.reason_code
CROSS JOIN ref_parameters prm;

CREATE INDEX ix_fct_downtime_report ON fct_downtime_events (report_id);
CREATE INDEX ix_fct_downtime_line ON fct_downtime_events (line_id, start_ts);


-- Production by line-shift and SKU -------------------------------------------------------
DROP TABLE IF EXISTS fct_production;
CREATE TABLE fct_production AS
SELECT
    p.report_id,
    r.line_id,
    r.shift_date,
    r.shift,
    p.sku,
    p.good_units + p.scrap_units                                        AS total_units,
    p.good_units,
    p.scrap_units,
    (p.good_units + p.scrap_units) * 1.0 / d.ideal_rate_per_min         AS ideal_min_total,
    p.good_units * 1.0 / d.ideal_rate_per_min                           AS ideal_min_good,
    ROUND(p.scrap_units * d.unit_cost_gtq, 2)                           AS scrap_cost_gtq,
    (p.good_units + p.scrap_units) * d.unit_weight_g / 1000.0           AS resin_kg,
    -- the SKU started in this shift after a changeover (start-up scrap and slow running expected)
    CASE WHEN EXISTS (SELECT 1 FROM stg_downtime_events e
                      WHERE e.report_id = p.report_id AND e.reason_code = 'CO' AND e.to_sku = p.sku)
         THEN 1 ELSE 0 END                                              AS started_after_changeover
FROM stg_production p
JOIN stg_shift_reports r ON r.report_id = p.report_id
JOIN dim_product d       ON d.sku = p.sku;

CREATE UNIQUE INDEX ux_fct_production ON fct_production (report_id, sku);


-- One row per line and shift, with the OEE components ---------------------------------------
DROP TABLE IF EXISTS fct_shift_oee;
CREATE TABLE fct_shift_oee AS
WITH stops AS (
    SELECT
        report_id,
        SUM(CASE WHEN loss_bucket = 'Planned stop' THEN duration_min ELSE 0 END)      AS planned_stop_min,
        SUM(CASE WHEN loss_bucket = 'Availability loss' THEN duration_min ELSE 0 END) AS availability_loss_min,
        SUM(CASE WHEN loss_bucket = 'Minor stop' THEN duration_min ELSE 0 END)        AS minor_stop_min,
        SUM(CASE WHEN loss_bucket = 'Availability loss' AND category = 'Changeover' THEN duration_min ELSE 0 END) AS changeover_min,
        SUM(CASE WHEN loss_bucket = 'Availability loss' AND is_breakdown = 1 THEN duration_min ELSE 0 END)     AS breakdown_min,
        SUM(CASE WHEN category = 'Changeover' THEN 1 ELSE 0 END)                       AS changeovers,
        SUM(CASE WHEN is_breakdown = 1 AND loss_bucket = 'Availability loss' THEN 1 ELSE 0 END) AS breakdowns,
        SUM(CASE WHEN loss_bucket = 'Minor stop' THEN 1 ELSE 0 END)                    AS minor_stops
    FROM fct_downtime_events
    GROUP BY report_id
),
output AS (
    SELECT
        p.report_id,
        SUM(p.total_units)                                              AS total_units,
        SUM(p.good_units)                                               AS good_units,
        SUM(p.scrap_units)                                              AS scrap_units,
        SUM(p.ideal_min_total)                                          AS ideal_min_total,
        SUM(p.ideal_min_good)                                           AS ideal_min_good,
        SUM(p.scrap_cost_gtq)                                           AS scrap_cost_gtq,
        SUM(p.resin_kg)                                                 AS resin_kg,
        -- contribution margin per minute of ideal running time, to value the lost time
        SUM(p.total_units * d.unit_margin_gtq) / NULLIF(SUM(p.ideal_min_total), 0) AS margin_per_ideal_min
    FROM fct_production p
    JOIN dim_product d ON d.sku = p.sku
    GROUP BY p.report_id
),
base AS (
    SELECT
        r.report_id,
        r.line_id,
        l.process,
        r.shift_date,
        STRFTIME('%Y-%m-01', r.shift_date)                              AS month_start,
        r.shift,
        r.supervisor,
        COALESCE(r.resin_lot, CASE WHEN l.process <> 'Blow molding' THEN 'UNKNOWN' END) AS resin_lot,
        r.shift_minutes,
        COALESCE(s.planned_stop_min, 0)                                 AS planned_stop_min,
        r.shift_minutes - COALESCE(s.planned_stop_min, 0)               AS planned_time_min,
        COALESCE(s.availability_loss_min, 0)                            AS availability_loss_min,
        COALESCE(s.minor_stop_min, 0)                                   AS minor_stop_min,
        COALESCE(s.changeover_min, 0)                                   AS changeover_min,
        COALESCE(s.breakdown_min, 0)                                    AS breakdown_min,
        COALESCE(s.changeovers, 0)                                      AS changeovers,
        COALESCE(s.breakdowns, 0)                                       AS breakdowns,
        COALESCE(s.minor_stops, 0)                                      AS minor_stops,
        COALESCE(o.total_units, 0)                                      AS total_units,
        COALESCE(o.good_units, 0)                                       AS good_units,
        COALESCE(o.scrap_units, 0)                                      AS scrap_units,
        COALESCE(o.ideal_min_total, 0)                                  AS ideal_min_total,
        COALESCE(o.ideal_min_good, 0)                                   AS ideal_min_good,
        COALESCE(o.scrap_cost_gtq, 0)                                   AS scrap_cost_gtq,
        COALESCE(o.resin_kg, 0)                                         AS resin_kg,
        o.margin_per_ideal_min,
        l.smed_group,
        CASE WHEN r.shift_date >= prm.smed_start THEN 'Post' ELSE 'Pre' END AS smed_period
    FROM stg_shift_reports r
    JOIN dim_line l ON l.line_id = r.line_id
    LEFT JOIN stops s  ON s.report_id = r.report_id
    LEFT JOIN output o ON o.report_id = r.report_id
    CROSS JOIN ref_parameters prm
)
SELECT
    b.*,
    b.planned_time_min - b.availability_loss_min                        AS run_time_min,
    ROUND((b.planned_time_min - b.availability_loss_min) / NULLIF(b.planned_time_min, 0), 4) AS availability,
    ROUND(b.ideal_min_total / NULLIF(b.planned_time_min - b.availability_loss_min, 0), 4)    AS performance,
    ROUND(1.0 * b.good_units / NULLIF(b.total_units, 0), 4)             AS quality,
    ROUND(b.ideal_min_good / NULLIF(b.planned_time_min, 0), 4)          AS oee,
    -- margin the shift would have earned at 100% OEE minus what it earned
    ROUND((b.planned_time_min - b.ideal_min_good) * COALESCE(b.margin_per_ideal_min, 0), 2) AS lost_margin_gtq
FROM base b;

CREATE UNIQUE INDEX ux_fct_shift_oee ON fct_shift_oee (report_id);
CREATE INDEX ix_fct_shift_oee_line ON fct_shift_oee (line_id, shift_date);
