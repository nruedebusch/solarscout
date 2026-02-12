# SolarScout 🌞

**Automated Solar Farm Site Assessment Tool**

SolarScout is a geospatial analysis application that identifies and evaluates potential solar farm locations using OpenStreetMap data. The tool combines land-use analysis, exclusion zone filtering, and grid infrastructure proximity scoring to generate a list of suitable sites.

## Technology Stack

**Backend:**
- **FastAPI**: RESTful API with async support
- **PostgreSQL + PostGIS**: Spatial database for geospatial operations
- **osm2pgsql**: OpenStreetMap data import pipeline
- **asyncpg**: Asynchronous database driver

**Frontend:**
- **Vue.js 3** (Composition API): Reactive UI framework
- **MapLibre GL JS**: High-performance vector map rendering

**Infrastructure:**
- **Docker Compose**: Multi-container orchestration
- **Geofabrik OSM Extracts**: Regional OpenStreetMap data source

## Analysis Methodology

1. **Data Preparation** (`prepare_data.sql`):
   - Extracts candidate parcels (landuse: farmland, meadow, farm)
   - Generates exclusion zones from residential, natural, and protected areas
   - Indexes power grid infrastructure (transmission lines, cables)
   - Transforms all geometries to EPSG:25832 (UTM Zone 32N)

2. **Spatial Analysis** (`analyze_sites` function):
   - Buffers exclusion zones by configurable distance
   - Performs geometric difference to cut out forbidden areas
   - Filters results by minimum area threshold
   - Calculates distance to nearest grid connection
   - Scores and ranks sites based on area and grid proximity

3. **Output**: GeoJSON FeatureCollection with properties:
   - `original_area_ha`: Pre-filtering parcel size
   - `suitable_area_ha`: Post-exclusion usable area
   - `grid_distance_m`: Distance to nearest power infrastructure
   - `score`: Composite ranking metric

## Deploy on Render

This repository now includes `render.yaml` so Render can create all required services:

- `solarscout-api` (FastAPI backend)
- `solarscout-frontend` (Vite static frontend)
- `solarscout-db` (PostgreSQL database)

### One-time setup

1. Push the latest code to GitHub.
2. In Render, choose **New +** -> **Blueprint**.
3. Select this repository and deploy.

### After services are created

1. Open `solarscout-frontend` in Render.
2. Set environment variable:
   - `VITE_API_BASE_URL=https://<your-backend-service>.onrender.com`
3. Open `solarscout-api` in Render.
4. Set environment variable:
   - `CORS_ORIGINS=https://<your-frontend-service>.onrender.com`
5. Redeploy frontend and backend.

### Data import note

Render deploys the app infrastructure, but OSM data still needs to be imported into the Render Postgres database.
Use your existing `osm2pgsql` import workflow against the Render DB connection string, then run `prepare_data.sql`.
