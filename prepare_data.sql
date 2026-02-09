-- SolarScout - Prepare Analysis Ready Data (ARD)
-- Run this AFTER importing a .osm.pbf via osm2pgsql into the same database.

-- Safety: required extensions (PostGIS image has them installed, but enable per-DB)
CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS hstore;

-- Safety: verify expected osm2pgsql tables/columns exist
DO $$
DECLARE
  missing_polygon_cols text[];
  missing_line_cols text[];
BEGIN
  IF to_regclass('public.planet_osm_polygon') IS NULL THEN
    RAISE EXCEPTION 'Missing table public.planet_osm_polygon. Did osm2pgsql import run successfully (pgsql output)?';
  END IF;
  IF to_regclass('public.planet_osm_line') IS NULL THEN
    RAISE EXCEPTION 'Missing table public.planet_osm_line. Did osm2pgsql import run successfully (pgsql output)?';
  END IF;

  SELECT array_agg(col) INTO missing_polygon_cols
  FROM (
    SELECT unnest(ARRAY['way', 'landuse', 'natural', 'leisure']) AS col
    EXCEPT
    SELECT column_name
    FROM information_schema.columns
    WHERE table_schema = 'public' AND table_name = 'planet_osm_polygon'
  ) s;
  IF missing_polygon_cols IS NOT NULL THEN
    RAISE EXCEPTION 'planet_osm_polygon is missing expected columns: % (check your osm2pgsql style/output)', missing_polygon_cols;
  END IF;

  SELECT array_agg(col) INTO missing_line_cols
  FROM (
    SELECT unnest(ARRAY['way', 'power']) AS col
    EXCEPT
    SELECT column_name
    FROM information_schema.columns
    WHERE table_schema = 'public' AND table_name = 'planet_osm_line'
  ) s;
  IF missing_line_cols IS NOT NULL THEN
    RAISE EXCEPTION 'planet_osm_line is missing expected columns: % (check your osm2pgsql style/output)', missing_line_cols;
  END IF;
END $$;

-- Helper cleaners
-- Note: osm2pgsql pgsql output is usually EPSG:3857 (Web Mercator). If SRID is 0,
-- we assume 3857 so the transform works. Bremen (Germany) analysis uses EPSG:25832.
CREATE OR REPLACE FUNCTION solarscout_clean_multipolygon(g geometry)
RETURNS geometry(MultiPolygon, 25832)
LANGUAGE SQL
STABLE
AS $$
  SELECT
    ST_Multi(
      ST_CollectionExtract(
        ST_MakeValid(
          ST_Transform(
            CASE WHEN ST_SRID(g) = 0 THEN ST_SetSRID(g, 3857) ELSE g END,
            25832
          )
        ),
        3
      )
    )::geometry(MultiPolygon, 25832);
$$;

CREATE OR REPLACE FUNCTION solarscout_clean_multiline(g geometry)
RETURNS geometry(MultiLineString, 25832)
LANGUAGE SQL
STABLE
AS $$
  SELECT
    ST_Multi(
      ST_CollectionExtract(
        ST_MakeValid(
          ST_Transform(
            CASE WHEN ST_SRID(g) = 0 THEN ST_SetSRID(g, 3857) ELSE g END,
            25832
          )
        ),
        2
      )
    )::geometry(MultiLineString, 25832);
$$;

-- 1) candidate_parcels
DROP TABLE IF EXISTS candidate_parcels;
CREATE TABLE candidate_parcels AS
WITH src AS (
  SELECT
    osm_id,
    landuse,
    name,
    solarscout_clean_multipolygon(way) AS geom
  FROM planet_osm_polygon
  WHERE landuse IN ('farmland', 'farm', 'meadow')
    AND way IS NOT NULL
)
SELECT
  osm_id,
  landuse,
  name,
  geom,
  ST_Area(geom) AS area_m2,
  (ST_Area(geom) / 10000.0) AS area_ha
FROM src
WHERE geom IS NOT NULL AND NOT ST_IsEmpty(geom);

CREATE INDEX candidate_parcels_geom_gix ON candidate_parcels USING GIST (geom);
CREATE INDEX candidate_parcels_area_ha_idx ON candidate_parcels (area_ha);

-- 2) exclusion_zones (categorized + merged/dissolved by category)
DROP TABLE IF EXISTS exclusion_zones;
CREATE TABLE exclusion_zones AS
WITH raw AS (
  SELECT 
    CASE
      WHEN landuse = 'residential' THEN 'residential'
      WHEN landuse IN ('forest') OR "natural" = 'wood' THEN 'woodland'
      WHEN landuse = 'cemetery' THEN 'cemetery'
      WHEN "natural" = 'water' THEN 'water'
      WHEN leisure = 'park' THEN 'park'
      WHEN boundary = 'protected_area' OR leisure = 'nature_reserve' THEN 'nature_reserve'
    END AS category,
    solarscout_clean_multipolygon(way) AS geom
  FROM planet_osm_polygon
  WHERE landuse IN ('residential', 'forest', 'cemetery')
     OR "natural" IN ('water', 'wood')
     OR leisure IN ('park')
     OR boundary = 'protected_area'
     OR leisure = 'nature_reserve'
),
cleaned AS (
  SELECT category, geom
  FROM raw
  WHERE category IS NOT NULL
    AND geom IS NOT NULL
    AND NOT ST_IsEmpty(geom)
)
SELECT
  category,
  ST_Multi(
    ST_CollectionExtract(
      ST_UnaryUnion(ST_Collect(geom)),
      3
    )
  )::geometry(MultiPolygon, 25832) AS geom
FROM cleaned
GROUP BY category;

CREATE INDEX exclusion_zones_geom_gix ON exclusion_zones USING GIST (geom);

-- 3) grid_infrastructure
DROP TABLE IF EXISTS grid_infrastructure;
CREATE TABLE grid_infrastructure AS
WITH src AS (
  SELECT
    osm_id,
    power,
    name,
    solarscout_clean_multiline(way) AS geom
  FROM planet_osm_line
  WHERE power IN ('line', 'cable')
    AND way IS NOT NULL
)
SELECT
  osm_id,
  power,
  name,
  geom
FROM src
WHERE geom IS NOT NULL AND NOT ST_IsEmpty(geom);

CREATE INDEX grid_infrastructure_geom_gix ON grid_infrastructure USING GIST (geom);

ANALYZE candidate_parcels;
ANALYZE exclusion_zones;
ANALYZE grid_infrastructure;
