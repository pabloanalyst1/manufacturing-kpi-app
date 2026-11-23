-- Question: Does the cheaper resin supplier cause more scrap on the injection presses, and does it still pay off?
-- Technique: join shifts to resin lots, compare scrap and splay rates, then price the extra scrap against the resin savings.
WITH by_supplier AS (
    SELECT
        r.supplier,
        SUM(f.total_units)                                              AS total_units,
        SUM(f.scrap_units)                                              AS scrap_units,
        SUM(f.scrap_cost_gtq)                                           AS scrap_cost,
        SUM(f.resin_kg)                                                 AS resin_kg,
        SUM(f.resin_kg * r.price_gtq_per_kg) / SUM(f.resin_kg)          AS price_per_kg,
        AVG(r.moisture_ppm)                                             AS moisture_ppm
    FROM fct_shift_oee f
    JOIN dim_resin_lot r ON r.lot_id = f.resin_lot
    WHERE f.process = 'Injection molding' AND r.resin_type = 'PET'
    GROUP BY r.supplier
),
base AS (SELECT * FROM by_supplier WHERE supplier = 'Polímeros Centroamericanos')
SELECT
    s.supplier,
    ROUND(s.moisture_ppm, 0)                                            AS avg_moisture_ppm,
    ROUND(100.0 * s.scrap_units / s.total_units, 2)                     AS scrap_pct,
    ROUND(s.price_per_kg, 2)                                            AS price_gtq_per_kg,
    ROUND(s.resin_kg / 1000, 0)                                         AS resin_tonnes,
    -- resin saved by buying this supplier instead of the reference supplier
    ROUND((b.price_per_kg - s.price_per_kg) * s.resin_kg, 0)            AS resin_savings_gtq,
    -- scrap cost above what the reference supplier's scrap rate would have cost
    ROUND(s.scrap_cost - s.scrap_cost * (1.0 * b.scrap_units / b.total_units) / (1.0 * s.scrap_units / s.total_units), 0) AS extra_scrap_cost_gtq
FROM by_supplier s
CROSS JOIN base b
ORDER BY scrap_pct;
