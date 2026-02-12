from __future__ import annotations

import ssl
import json
import logging
import asyncpg
from typing import Any

# Configure logger
logger = logging.getLogger(__name__)

class DatabaseConnectionError(Exception):
    pass

class DatabaseQueryError(Exception):
    pass

class Database:
    def __init__(self, database_url: str) -> None:
        self._database_url = database_url

    async def connect(self) -> None:
        """Not used anymore (connection on demand)."""
        pass

    async def disconnect(self) -> None:
        """Not used anymore."""
        pass

    async def ensure_connected(self) -> None:
        """Not used anymore."""
        pass

    def _get_ssl_context(self):
        """Creates a permissive SSL context for Render internal connections."""
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        return ctx

    async def analyze_sites(
        self,
        *,
        buffer_distance: int,
        exclude_nature: bool,
        min_area: float,
        max_grid_distance: int,
    ) -> dict[str, Any]:
        """
        Runs the spatial analysis using a fresh connection for each request.
        This avoids connection pool issues (error 08003) on Render free tier.
        """
        conn = None
        try:
            # Create a fresh connection
            conn = await asyncpg.connect(
                self._database_url, 
                ssl=self._get_ssl_context()
            )

            # Check if tables exist
            await self._ensure_analysis_tables(conn)

            sql = """
                WITH parcels AS (
                    SELECT
                        ROW_NUMBER() OVER (ORDER BY area_ha DESC, landuse) AS id,
                        area_ha,
                        landuse,
                        geom
                    FROM candidate_parcels
                    WHERE area_ha >= $1
                      AND geom IS NOT NULL
                      AND NOT ST_IsEmpty(geom)
                ),
                exclusions AS (
                    SELECT
                        ST_UnaryUnion(
                            ST_Collect(
                                CASE
                                    WHEN category = 'residential' THEN ST_Buffer(geom, $2)
                                    WHEN $3 AND category IN ('woodland', 'park', 'water', 'nature_reserve') THEN geom
                                    ELSE NULL
                                END
                            )
                        ) AS geom
                    FROM exclusion_zones
                    WHERE category = 'residential'
                       OR ($3 AND category IN ('woodland', 'park', 'water', 'nature_reserve'))
                ),
                parcels_cut AS (
                    SELECT
                        p.id,
                        p.area_ha,
                        p.landuse,
                        CASE
                            WHEN e.geom IS NULL THEN p.geom
                            WHEN NOT ST_Intersects(p.geom, e.geom) THEN p.geom
                            ELSE ST_Difference(p.geom, e.geom)
                        END AS geom
                    FROM parcels p
                    CROSS JOIN exclusions e
                ),
                cleaned AS (
                    SELECT
                        id,
                        area_ha,
                        landuse,
                        ST_Multi(
                            ST_CollectionExtract(
                                ST_MakeValid(geom),
                                3
                            )
                        )::geometry(MultiPolygon, 25832) AS geom
                    FROM parcels_cut
                    WHERE geom IS NOT NULL AND NOT ST_IsEmpty(geom)
                ),
                near_grid AS (
                    SELECT
                        c.id,
                        c.area_ha,
                        c.landuse,
                        c.geom
                    FROM cleaned c
                    WHERE EXISTS (
                        SELECT 1
                        FROM grid_infrastructure g
                        WHERE ST_DWithin(c.geom, g.geom, $4)
                    )
                )
                SELECT
                    id,
                    area_ha,
                    landuse,
                    ST_AsGeoJSON(ST_Transform(geom, 4326)) AS geometry
                FROM near_grid
                WHERE NOT ST_IsEmpty(geom);
            """

            rows = await conn.fetch(
                sql, 
                min_area, 
                buffer_distance, 
                exclude_nature, 
                max_grid_distance
            )

            features: list[dict[str, Any]] = []
            for row in rows:
                features.append({
                    "type": "Feature",
                    "geometry": json.loads(row["geometry"]),
                    "properties": {
                        "id": row["id"],
                        "area_ha": float(row["area_ha"]),
                        "landuse": row["landuse"],
                    },
                })

            return {"type": "FeatureCollection", "features": features}

        except Exception as exc:
            logger.exception("Analysis failed")
            # Map common errors to custom exceptions
            msg = str(exc)
            if "42P01" in msg: # undefined_table
                 raise DatabaseQueryError("Required tables missing. Run prepare_data.sql.") from exc
            if "0800" in msg or "connection" in msg.lower():
                 raise DatabaseConnectionError("Database connection failed.") from exc
            raise DatabaseQueryError(f"Analysis query failed: {msg}") from exc

        finally:
            if conn:
                await conn.close()

    async def _ensure_analysis_tables(self, conn) -> None:
        """Checks if required tables exist using the provided connection."""
        missing_tables = await conn.fetch(
            """
            WITH required(table_name) AS (
                VALUES ('candidate_parcels'), ('exclusion_zones'), ('grid_infrastructure')
            )
            SELECT table_name
            FROM required
            WHERE to_regclass('public.' || table_name) IS NULL;
            """
        )

        if missing_tables:
            names = ", ".join(row["table_name"] for row in missing_tables)
            raise DatabaseQueryError(
                f"Spatial analysis query failed: required ARD tables are missing ({names}). "
                "Run prepare_data.sql in the target database."
            )
