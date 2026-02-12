from __future__ import annotations

import asyncio
import ssl
import json
import logging
from typing import Any

import asyncpg
from asyncpg import Pool


class DatabaseConnectionError(Exception):
    pass


class DatabaseQueryError(Exception):
    pass


logger = logging.getLogger(__name__)
TRANSIENT_CONNECTION_SQLSTATE_PREFIXES = ("08", "57")
TRANSIENT_CONNECTION_MESSAGES = (
    "connection was closed",
    "connection is closed",
    "terminating connection",
    "connection reset",
)


class Database:
    def __init__(self, database_url: str) -> None:
        self._database_url = database_url
        self._pool: Pool | None = None

    @property
    def is_connected(self) -> bool:
        return self._pool is not None

    async def connect(self) -> None:
        if self._pool is not None:
            return
        
        ssl_ctx = ssl.create_default_context()
        ssl_ctx.check_hostname = False
        ssl_ctx.verify_mode = ssl.CERT_NONE

        try:
            self._pool = await asyncpg.create_pool(
                dsn=self._database_url,
                min_size=0,
                max_size=5,
                command_timeout=180,
                max_inactive_connection_lifetime=10,
            )
        except Exception as exc:
            raise DatabaseConnectionError(
                "Unable to connect to PostgreSQL. Check DATABASE_URL. "
                "On Render: prefer the Internal Database URL; if you use the External URL, ensure it has ?sslmode=require."
            ) from exc

    async def ensure_connected(self) -> None:
        if self._pool is None:
            await self.connect()



    async def disconnect(self) -> None:
        if self._pool is None:
            return
        await self._pool.close()
        self._pool = None

    async def _reconnect(self) -> None:
        await self.disconnect()
        await self.connect()

    async def ping(self) -> bool:
        pool = self._require_pool()
        try:
            value = await pool.fetchval("SELECT 1;")
        except Exception as exc:
            raise DatabaseConnectionError("Database connectivity check failed.") from exc
        return value == 1

    def _is_transient_connection_error(self, exc: Exception) -> bool:
        sqlstate = str(getattr(exc, "sqlstate", ""))
        raw_message = " ".join(str(exc).splitlines()).strip().lower()
        return sqlstate.startswith(TRANSIENT_CONNECTION_SQLSTATE_PREFIXES) or any(
            token in raw_message for token in TRANSIENT_CONNECTION_MESSAGES
        )

    def _require_pool(self) -> Pool:
        if self._pool is None:
            raise DatabaseConnectionError("Database pool is not initialized.")
        return self._pool

    async def analyze_sites(
        self,
        *,
        buffer_distance: int,
        exclude_nature: bool,
        min_area: float,
        max_grid_distance: int,
    ) -> dict[str, Any]:
        pool = self._require_pool()
        await self._ensure_analysis_tables(pool)

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

        query_args = (
            min_area,
            buffer_distance,
            exclude_nature,
            max_grid_distance,
        )

        rows: list[asyncpg.Record] | None = None
        last_exc: Exception | None = None
        max_attempts = 3

        for attempt in range(max_attempts):
            try:
                rows = await pool.fetch(sql, *query_args)
                last_exc = None
                break
            except (asyncpg.PostgresError, asyncpg.InterfaceError) as exc:
                last_exc = exc
                sqlstate = str(getattr(exc, "sqlstate", "unknown"))
                if attempt < max_attempts - 1 and self._is_transient_connection_error(exc):
                    logger.warning(
                        "Database connection dropped during analysis (sqlstate=%s). Reconnecting and retrying (attempt %s/%s).",
                        sqlstate,
                        attempt + 2,
                        max_attempts,
                    )
                    await self._reconnect()
                    pool = self._require_pool()
                    await self._ensure_analysis_tables(pool)
                    await asyncio.sleep(0.25 * (attempt + 1))
                    continue

                break
            except Exception as exc:
                last_exc = exc
                break

        if last_exc is not None or rows is None:
            exc = last_exc or Exception("Unknown database failure.")
            sqlstate = getattr(exc, "sqlstate", "unknown")
            raw_message = " ".join(str(exc).splitlines()).strip()
            logger.exception("Spatial analysis query failed (sqlstate=%s): %s", sqlstate, raw_message)

            if self._is_transient_connection_error(exc):
                raise DatabaseConnectionError(
                    "Database connection dropped during analysis. Please retry in a few seconds. "
                    "If this persists on Render, check service/database region and DATABASE_URL."
                ) from exc

            if sqlstate == "42P01":
                raise DatabaseQueryError(
                    "Spatial analysis query failed: required ARD tables are missing. "
                    "Run prepare_data.sql in the target database."
                ) from exc
            if sqlstate == "42883":
                raise DatabaseQueryError(
                    "Spatial analysis query failed: PostGIS functions are unavailable. "
                    "Enable extension with CREATE EXTENSION postgis;"
                ) from exc
            if "mixed SRID" in raw_message:
                raise DatabaseQueryError(
                    "Spatial analysis query failed: mixed SRID geometries detected. "
                    "Rebuild ARD tables using prepare_data.sql so all tables use EPSG:25832."
                ) from exc
            if "TopologyException" in raw_message:
                raise DatabaseQueryError(
                    "Spatial analysis query failed: invalid topology in source geometries. "
                    "Re-run prepare_data.sql and retry."
                ) from exc

            raise DatabaseQueryError(
                f"Spatial analysis query failed (sqlstate {sqlstate}): {raw_message}"
            ) from exc

        features: list[dict[str, Any]] = []
        for row in rows:
            features.append(
                {
                    "type": "Feature",
                    "geometry": json.loads(row["geometry"]),
                    "properties": {
                        "id": row["id"],
                        "area_ha": float(row["area_ha"]),
                        "landuse": row["landuse"],
                    },
                }
            )

        return {"type": "FeatureCollection", "features": features}

    async def _ensure_analysis_tables(self, pool: Pool) -> None:
        missing_tables = await pool.fetch(
            """
            WITH required(table_name) AS (
                VALUES
                    ('candidate_parcels'),
                    ('exclusion_zones'),
                    ('grid_infrastructure')
            )
            SELECT table_name
            FROM required
            WHERE to_regclass('public.' || table_name) IS NULL
            ORDER BY table_name;
            """
        )

        if missing_tables:
            names = ", ".join(row["table_name"] for row in missing_tables)
            raise DatabaseQueryError(
                "Spatial analysis query failed: required ARD tables are missing "
                f"({names}). Run prepare_data.sql in the target database."
            )
