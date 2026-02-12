import { ref } from "vue";

const API_BASE_URL = (
  import.meta.env.VITE_API_BASE_URL ?? "http://127.0.0.1:8000"
).replace(/\/+$/, "");
const ANALYZE_ENDPOINT = `${API_BASE_URL}/api/analyze`;

const emptyFeatureCollection = {
  type: "FeatureCollection",
  features: [],
};

const clamp = (value, min, max) => Math.min(Math.max(value, min), max);

export function useAnalysis() {
  const bufferDistance = ref(500);
  const excludeNature = ref(true);
  const minArea = ref(2.0);
  const maxGridDistance = ref(2000);

  const isLoading = ref(false);
  const errorMessage = ref("");

  const runAnalysis = async () => {
    isLoading.value = true;
    errorMessage.value = "";

    const payload = {
      buffer_distance: clamp(Number(bufferDistance.value), 0, 2000),
      exclude_nature: Boolean(excludeNature.value),
      min_area: Math.max(Number(minArea.value), 0.1),
      max_grid_distance: clamp(Number(maxGridDistance.value), 100, 10000),
    };

    try {
      const response = await fetch(ANALYZE_ENDPOINT, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify(payload),
      });

      const responseData = await response.json().catch(() => ({}));
      if (!response.ok) {
        throw new Error(responseData.detail || "Analysis request failed.");
      }

      if (
        responseData.type !== "FeatureCollection" ||
        !Array.isArray(responseData.features)
      ) {
        throw new Error("API returned an invalid GeoJSON response.");
      }

      return responseData;
    } catch (error) {
      errorMessage.value =
        error instanceof Error ? error.message : "Unexpected analysis error.";
      return emptyFeatureCollection;
    } finally {
      isLoading.value = false;
    }
  };

  return {
    bufferDistance,
    excludeNature,
    minArea,
    maxGridDistance,
    isLoading,
    errorMessage,
    runAnalysis,
  };
}
