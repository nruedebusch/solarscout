import { ref } from "vue";

const API_BASE_URL = (
  import.meta.env.VITE_API_BASE_URL ?? "http://127.0.0.1:8000"
).replace(/\/+$/, "");
const ANALYZE_ENDPOINT = `${API_BASE_URL}/api/analyze`;
const HEALTH_ENDPOINT = `${API_BASE_URL}/health`;
const DEBUG_ANALYSIS = import.meta.env.DEV;

const emptyFeatureCollection = {
  type: "FeatureCollection",
  features: [],
};

const clamp = (value, min, max) => Math.min(Math.max(value, min), max);
const isNetworkFailure = (error) =>
  error instanceof TypeError ||
  /networkerror|failed to fetch/i.test(String(error?.message ?? ""));
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

const waitForBackendWakeup = async (timeoutMs = 70000, intervalMs = 3000) => {
  const startedAt = Date.now();
  while (Date.now() - startedAt < timeoutMs) {
    try {
      const healthResponse = await fetch(HEALTH_ENDPOINT, {
        method: "GET",
        cache: "no-store",
      });
      if (healthResponse.ok) {
        return true;
      }
    } catch {
      // keep polling while backend wakes up
    }
    await sleep(intervalMs);
  }
  return false;
};

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

    const requestAnalyze = async () => {
      if (DEBUG_ANALYSIS) {
        console.info("[analysis] request:start", {
          endpoint: ANALYZE_ENDPOINT,
          origin: window.location.origin,
          payload,
        });
      }

      const response = await fetch(ANALYZE_ENDPOINT, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify(payload),
      });

      if (DEBUG_ANALYSIS) {
        console.info("[analysis] request:response", {
          status: response.status,
          ok: response.ok,
        });
      }

      const responseData = await response.json().catch(() => ({}));
      return { response, responseData };
    };

    try {
      for (let attempt = 0; attempt < 2; attempt += 1) {
        const { response, responseData } = await requestAnalyze();

        if (response.ok) {
          if (
            responseData.type !== "FeatureCollection" ||
            !Array.isArray(responseData.features)
          ) {
            throw new Error("API returned an invalid GeoJSON response.");
          }

          if (DEBUG_ANALYSIS) {
            console.info("[analysis] request:success", {
              featureCount: responseData.features.length,
              attempt: attempt + 1,
            });
          }

          return responseData;
        }

        if (attempt === 0 && response.status === 503) {
          errorMessage.value = "Backend is waking up. Retrying automatically...";
          const ready = await waitForBackendWakeup();
          if (ready) {
            if (DEBUG_ANALYSIS) {
              console.info("[analysis] backend woke up, retrying analyze");
            }
            continue;
          }
        }

        throw new Error(responseData.detail || "Analysis request failed.");
      }

      throw new Error("Analysis request failed after retry.");
    } catch (error) {
      if (isNetworkFailure(error)) {
        const ready = await waitForBackendWakeup(45000, 3000);
        if (ready) {
          try {
            const { response, responseData } = await requestAnalyze();
            if (response.ok) {
              return responseData;
            }
          } catch {
            // fall through to user-facing message
          }
        }

        let healthStatus = "unreachable";
        try {
          const healthResponse = await fetch(HEALTH_ENDPOINT, { method: "GET" });
          healthStatus = String(healthResponse.status);
        } catch {
          healthStatus = "unreachable";
        }

        errorMessage.value = `NetworkError: API not reachable (${ANALYZE_ENDPOINT}). Health: ${healthStatus}.`;
      } else {
        errorMessage.value =
          error instanceof Error ? error.message : "Unexpected analysis error.";
      }

      if (DEBUG_ANALYSIS) {
        console.error("[analysis] request:error", {
          endpoint: ANALYZE_ENDPOINT,
          healthEndpoint: HEALTH_ENDPOINT,
          error,
          renderedMessage: errorMessage.value,
        });
      }

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
