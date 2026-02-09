import { shallowRef } from "vue";
import maplibregl from "maplibre-gl/dist/maplibre-gl-csp.js";
import maplibreWorkerUrl from "maplibre-gl/dist/maplibre-gl-csp-worker.js?url";

maplibregl.setWorkerUrl(maplibreWorkerUrl);

const defaultStyle = {
  version: 8,
  sources: {
    osm: {
      type: "raster",
      tiles: [
        "https://a.tile.openstreetmap.org/{z}/{x}/{y}.png",
        "https://b.tile.openstreetmap.org/{z}/{x}/{y}.png",
        "https://c.tile.openstreetmap.org/{z}/{x}/{y}.png",
      ],
      tileSize: 256,
      attribution: "&copy; OpenStreetMap Contributors",
    },
  },
  layers: [{ id: "osm", type: "raster", source: "osm" }],
};

export function useMapLibre() {
  const map = shallowRef(null);
  const hoverHandlersByLayer = new Map();

  const extendBoundsFromCoordinates = (coordinates, bounds) => {
    if (!Array.isArray(coordinates) || coordinates.length === 0) {
      return false;
    }

    if (
      typeof coordinates[0] === "number" &&
      typeof coordinates[1] === "number"
    ) {
      bounds.extend([coordinates[0], coordinates[1]]);
      return true;
    }

    let found = false;
    for (const childCoordinates of coordinates) {
      found = extendBoundsFromCoordinates(childCoordinates, bounds) || found;
    }
    return found;
  };

  const ensureMap = () => {
    if (!map.value) {
      throw new Error("Map is not initialized.");
    }
    return map.value;
  };

  const waitForMapLoad = async () => {
    const mapInstance = ensureMap();
    if (mapInstance.loaded()) {
      return;
    }
    await new Promise((resolve) => {
      mapInstance.once("load", () => resolve());
    });
  };

  const createMap = (
    container,
    options = {
      center: [8.8, 53.08],
      zoom: 11,
      style: defaultStyle,
    },
  ) => {
    if (map.value) {
      return map.value;
    }

    map.value = new maplibregl.Map({
      container,
      style: options.style ?? defaultStyle,
      center: options.center ?? [8.8, 53.08],
      zoom: options.zoom ?? 11,
    });

    map.value.addControl(new maplibregl.NavigationControl(), "top-right");
    return map.value;
  };

  const clearLayer = (layerId) => {
    const mapInstance = ensureMap();
    disableHoverTooltip(layerId);
    const sourceId = `${layerId}-source`;
    const fillLayerId = `${layerId}-fill`;
    const lineLayerId = `${layerId}-line`;

    if (mapInstance.getLayer(lineLayerId)) {
      mapInstance.removeLayer(lineLayerId);
    }
    if (mapInstance.getLayer(fillLayerId)) {
      mapInstance.removeLayer(fillLayerId);
    }
    if (mapInstance.getSource(sourceId)) {
      mapInstance.removeSource(sourceId);
    }
  };

  const addGeoJsonLayer = async (geojson, layerId) => {
    const mapInstance = ensureMap();
    await waitForMapLoad();

    const sourceId = `${layerId}-source`;
    const fillLayerId = `${layerId}-fill`;
    const lineLayerId = `${layerId}-line`;

    if (!geojson || !Array.isArray(geojson.features)) {
      throw new Error("Invalid GeoJSON FeatureCollection.");
    }

    clearLayer(layerId);

    mapInstance.addSource(sourceId, {
      type: "geojson",
      data: geojson,
    });

    mapInstance.addLayer({
      id: fillLayerId,
      type: "fill",
      source: sourceId,
      paint: {
        "fill-color": "#22c55e",
        "fill-opacity": 0.5,
      },
    });

    mapInstance.addLayer({
      id: lineLayerId,
      type: "line",
      source: sourceId,
      paint: {
        "line-color": "#14532d",
        "line-width": 2,
      },
    });
  };

  const formatTooltip = (feature) => {
    const areaValue = Number(feature?.properties?.area_ha);
    const areaText = Number.isFinite(areaValue)
      ? `${areaValue.toFixed(2)} ha`
      : "n/a";
    const landuseValue = feature?.properties?.landuse ?? "unknown";
    return `
      <div style="font-family: Inter, Segoe UI, Arial, sans-serif; font-size: 12px; color: #0f172a;">
        <div style="font-weight: 700; margin-bottom: 4px;">Candidate Parcel</div>
        <div><span style="font-weight: 600;">Area:</span> ${areaText}</div>
        <div><span style="font-weight: 600;">Landuse:</span> ${landuseValue}</div>
      </div>
    `;
  };

  const createTooltipElement = (mapInstance) => {
    const tooltipElement = document.createElement("div");
    tooltipElement.className = "solarscout-map-tooltip";
    Object.assign(tooltipElement.style, {
      position: "absolute",
      display: "none",
      zIndex: "20",
      pointerEvents: "none",
      background: "rgba(255, 255, 255, 0.96)",
      border: "1px solid #cbd5e1",
      borderRadius: "8px",
      boxShadow: "0 8px 20px rgba(15, 23, 42, 0.18)",
      padding: "8px 10px",
      maxWidth: "220px",
      transform: "translate(12px, 12px)",
    });
    mapInstance.getContainer().appendChild(tooltipElement);
    return tooltipElement;
  };

  const disableHoverTooltip = (layerId) => {
    const mapInstance = map.value;
    const handlers = hoverHandlersByLayer.get(layerId);
    if (!mapInstance || !handlers) {
      return;
    }

    const { fillLayerId, tooltipElement, onMouseEnter, onMouseMove, onMouseLeave } =
      handlers;
    mapInstance.off("mouseenter", fillLayerId, onMouseEnter);
    mapInstance.off("mousemove", fillLayerId, onMouseMove);
    mapInstance.off("mouseleave", fillLayerId, onMouseLeave);
    mapInstance.getCanvas().style.cursor = "";
    if (tooltipElement && tooltipElement.parentNode) {
      tooltipElement.parentNode.removeChild(tooltipElement);
    }
    hoverHandlersByLayer.delete(layerId);
  };

  const enableHoverTooltip = async (layerId) => {
    const mapInstance = ensureMap();
    await waitForMapLoad();

    const fillLayerId = `${layerId}-fill`;
    if (!mapInstance.getLayer(fillLayerId)) {
      return false;
    }

    disableHoverTooltip(layerId);

    const tooltipElement = createTooltipElement(mapInstance);

    const onMouseEnter = () => {
      mapInstance.getCanvas().style.cursor = "pointer";
    };

    const onMouseMove = (event) => {
      const feature = event.features?.[0];
      if (!feature) {
        tooltipElement.style.display = "none";
        return;
      }

      tooltipElement.innerHTML = formatTooltip(feature);
      tooltipElement.style.display = "block";
      tooltipElement.style.left = `${event.point.x}px`;
      tooltipElement.style.top = `${event.point.y}px`;
    };

    const onMouseLeave = () => {
      mapInstance.getCanvas().style.cursor = "";
      tooltipElement.style.display = "none";
    };

    mapInstance.on("mouseenter", fillLayerId, onMouseEnter);
    mapInstance.on("mousemove", fillLayerId, onMouseMove);
    mapInstance.on("mouseleave", fillLayerId, onMouseLeave);

    hoverHandlersByLayer.set(layerId, {
      fillLayerId,
      tooltipElement,
      onMouseEnter,
      onMouseMove,
      onMouseLeave,
    });

    return true;
  };

  const fitToGeoJson = async (
    geojson,
    options = {
      padding: 50,
      maxZoom: 14,
      duration: 800,
    },
  ) => {
    const mapInstance = ensureMap();
    await waitForMapLoad();

    if (
      !geojson ||
      !Array.isArray(geojson.features) ||
      geojson.features.length === 0
    ) {
      return false;
    }

    const bounds = new maplibregl.LngLatBounds();
    let hasBounds = false;

    for (const feature of geojson.features) {
      const geometry = feature?.geometry;
      if (!geometry || !geometry.coordinates) {
        continue;
      }
      hasBounds =
        extendBoundsFromCoordinates(geometry.coordinates, bounds) || hasBounds;
    }

    if (!hasBounds) {
      return false;
    }

    mapInstance.fitBounds(bounds, {
      padding: options.padding ?? 50,
      maxZoom: options.maxZoom ?? 14,
      duration: options.duration ?? 800,
    });

    return true;
  };

  const destroyMap = () => {
    if (map.value) {
      for (const layerId of hoverHandlersByLayer.keys()) {
        disableHoverTooltip(layerId);
      }
      hoverHandlersByLayer.clear();
      map.value.remove();
      map.value = null;
    }
  };

  return {
    map,
    createMap,
    addGeoJsonLayer,
    clearLayer,
    fitToGeoJson,
    enableHoverTooltip,
    disableHoverTooltip,
    destroyMap,
  };
}
