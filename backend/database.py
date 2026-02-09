from __future__ import annotations

import json
from typing import Any

import asyncpg
from asyncpg import Pool


class DatabaseConnectionError(Exception):
    pass


class DatabaseQueryError(Exception):
    pass


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
        try:
            self._pool = await asyncpg.create_pool(
                dsn=self._database_url,
                min_size=1,
                max_size=10,
                command_timeout=60,
            )
        except Exception as exc:
            raise DatabaseConnectionError("Unable to connect to PostgreSQL.") from exc

    async def ensure_connected(self) -> None:
        if self._pool is None:
            await self.connect()

    async def disconnect(self) -> None:
        if self._pool is None:
            return
        await self._pool.close()
        self._pool = None

    async def ping(self) -> bool:
        pool = self._require_pool()
        try:
            value = await pool.fetchval("SELECT 1;")
        except Exception as exc:
            raise DatabaseConnectionError("Database connectivity check failed.") from exc
        return value == 1

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
        sql = """
            WITH parcels AS (
                SELECT
                    ROW_NUMBER() OVER (ORDER BY area_ha DESC, landuse) AS id,
                    area_ha,
                    landuse,
                    geom
                FROM candidate_parcels
                WHERE area_ha >= $1
            ),
            exclusions AS (
                SELECT
                    ST_UnaryUnion(
                        ST_Collect(
                            CASE
                                WHEN category = 'residential' THEN ST_Buffer(geom, $2)
                                WHEN $3 AND category IN ('woodland', 'park', 'water', 'nature_reserve', 'protected_area') THEN geom
                                ELSE NULL
                            END
                        )
                    ) AS geom
                FROM exclusion_zones
                WHERE category = 'residential'
                   OR ($3 AND category IN ('woodland', 'park', 'water', 'nature_reserve', 'protected_area'))
            ),
            parcels_cut AS (
                SELECT
                    p.id,
                    p.area_ha,
                    p.landuse,
                    CASE
                        WHEN e.geom IS NULL THEN p.geom
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

        try:
            rows = await pool.fetch(
                sql,
                min_area,
                buffer_distance,
                exclude_nature,
                max_grid_distance,
            )
        except asyncpg.PostgresError as exc:
            raise DatabaseQueryError("Spatial analysis query failed.") from exc
        except Exception as exc:
            raise DatabaseConnectionError("Database request failed.") from exc

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
