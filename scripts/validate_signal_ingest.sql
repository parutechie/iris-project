-- ==========================================================
-- IRIS-SIG-42: Signal Ingest Validation Queries
--
-- Run these against the PostgreSQL database after executing
-- the ingestion pipeline to verify data quality and
-- deduplication behaviour.
--
-- All queries target iris_staging.signal_ingest.
-- ==========================================================


-- ----------------------------------------------------------
-- 1. Row count and signal type distribution
-- ----------------------------------------------------------

SELECT
    signal_type,
    COUNT(*)                          AS record_count,
    ROUND(
        COUNT(*) * 100.0
        / SUM(COUNT(*)) OVER (),
        1
    )                                 AS pct
FROM iris_staging.signal_ingest
GROUP BY signal_type
ORDER BY record_count DESC;


-- ----------------------------------------------------------
-- 2. Deduplication check
--    Returns rows where the same source_url appears more
--    than once — should return 0 rows if idempotency holds.
-- ----------------------------------------------------------

SELECT
    source_url,
    COUNT(*) AS occurrences
FROM iris_staging.signal_ingest
GROUP BY source_url
HAVING COUNT(*) > 1
ORDER BY occurrences DESC;


-- ----------------------------------------------------------
-- 3. Missing required fields
--    Identifies records with NULL title or empty source.
-- ----------------------------------------------------------

SELECT
    id,
    source_url,
    title,
    source
FROM iris_staging.signal_ingest
WHERE
    title IS NULL
    OR title = ''
    OR source IS NULL
    OR source = '';


-- ----------------------------------------------------------
-- 4. Records with parse errors
-- ----------------------------------------------------------

SELECT
    id,
    source_url,
    LEFT(title, 80) AS title_preview,
    parse_error
FROM iris_staging.signal_ingest
WHERE parse_error IS NOT NULL
ORDER BY created_at DESC;


-- ----------------------------------------------------------
-- 5. Geocoding quality
--    Shows how many records have resolved / ambiguous /
--    unresolved geometries.
-- ----------------------------------------------------------

SELECT
    location_resolved,
    location_ambiguous,
    COUNT(*)    AS record_count
FROM iris_staging.signal_ingest
GROUP BY
    location_resolved,
    location_ambiguous
ORDER BY
    location_resolved DESC,
    location_ambiguous;


-- ----------------------------------------------------------
-- 6. Invalid geometry check
--    Returns records where geometry is stored but the
--    coordinate values look invalid (e.g. outside Germany).
--    Expected UTM 32N bounding box for Germany:
--      Easting  : 280000 – 920000
--      Northing : 5200000 – 6100000
-- ----------------------------------------------------------

SELECT
    id,
    source_url,
    location_name,
    latitude,
    longitude,
    ST_AsText(geometry)               AS geometry_wkt,
    ST_X(geometry::geometry)          AS easting,
    ST_Y(geometry::geometry)          AS northing
FROM iris_staging.signal_ingest
WHERE
    geometry IS NOT NULL
    AND (
        ST_X(geometry::geometry) < 280000
        OR ST_X(geometry::geometry) > 920000
        OR ST_Y(geometry::geometry) < 5200000
        OR ST_Y(geometry::geometry) > 6100000
    );


-- ----------------------------------------------------------
-- 7. Date coverage
--    Shows the range of publication dates loaded.
-- ----------------------------------------------------------

SELECT
    MIN(published_at)   AS oldest_article,
    MAX(published_at)   AS newest_article,
    COUNT(*)            AS total_records,
    COUNT(published_at) AS records_with_date,
    COUNT(*) - COUNT(published_at)
                        AS records_missing_date
FROM iris_staging.signal_ingest;


-- ----------------------------------------------------------
-- 8. Recent signals (last 10)
-- ----------------------------------------------------------

SELECT
    id,
    source,
    LEFT(title, 80)     AS title_preview,
    signal_type,
    location_name,
    location_resolved,
    published_at,
    created_at
FROM iris_staging.signal_ingest
ORDER BY published_at DESC NULLS LAST
LIMIT 10;


-- ----------------------------------------------------------
-- 9. Geographic coverage
--    Lists all distinct location names and how many
--    records mention each one.
-- ----------------------------------------------------------

SELECT
    location_name,
    COUNT(*)            AS record_count,
    SUM(CASE WHEN location_resolved THEN 1 ELSE 0 END)
                        AS resolved_count
FROM iris_staging.signal_ingest
WHERE location_name IS NOT NULL
GROUP BY location_name
ORDER BY record_count DESC;


-- ----------------------------------------------------------
-- 10. Signals on a map (PostGIS spatial query)
--     Returns all records with resolved geometries as
--     WKT strings and their WGS84 equivalents for
--     visualisation in a GIS tool.
-- ----------------------------------------------------------

SELECT
    id,
    source,
    signal_type,
    location_name,
    LEFT(title, 80)         AS title_preview,
    published_at,
    ST_AsText(geometry)     AS geom_25832,
    ST_AsText(
        ST_Transform(
            geometry::geometry,
            4326
        )
    )                       AS geom_wgs84
FROM iris_staging.signal_ingest
WHERE location_resolved = TRUE
ORDER BY published_at DESC NULLS LAST;
