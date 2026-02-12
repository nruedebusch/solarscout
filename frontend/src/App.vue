<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from "vue";
import { useAnalysis } from "./composables/useAnalysis";
import { useMapLibre } from "./composables/useMapLibre";

const mapContainer = ref(null);
const analysisCompleted = ref(false);
const resultCount = ref(0);
const totalArea = ref(0);
const isSidebarOpen = ref(false);

const {
  bufferDistance,
  excludeNature,
  minArea,
  maxGridDistance,
  isLoading: isAnalyzing,
  errorMessage,
  runAnalysis,
} = useAnalysis();

const {
  createMap,
  addGeoJsonLayer,
  clearLayer,
  fitToGeoJson,
  enableHoverTooltip,
  destroyMap,
} = useMapLibre();

const RESULT_LAYER_ID = "analysis-results";
const hasSummary = computed(
  () => analysisCompleted.value && !isAnalyzing.value && !errorMessage.value,
);

const isMobileViewport = () =>
  typeof window !== "undefined" &&
  window.matchMedia("(max-width: 1023px)").matches;

const closeSidebar = () => {
  isSidebarOpen.value = false;
};

const toggleSidebar = () => {
  isSidebarOpen.value = !isSidebarOpen.value;
};

const closeSidebarOnMobile = () => {
  if (isMobileViewport()) {
    closeSidebar();
  }
};

const updateSummary = (featureCollection) => {
  const features = Array.isArray(featureCollection?.features)
    ? featureCollection.features
    : [];
  resultCount.value = features.length;
  totalArea.value = features.reduce(
    (sum, feature) => sum + (Number(feature?.properties?.area_ha) || 0),
    0,
  );
};

const handleAnalyze = async () => {
  analysisCompleted.value = false;

  try {
    clearLayer(RESULT_LAYER_ID);
  } catch {
    // Ignore if map has not initialized yet.
  }

  const featureCollection = await runAnalysis();
  updateSummary(featureCollection);
  analysisCompleted.value = !errorMessage.value;

  if (featureCollection.features.length === 0) {
    closeSidebarOnMobile();
    return;
  }

  try {
    await addGeoJsonLayer(featureCollection, RESULT_LAYER_ID);
    await enableHoverTooltip(RESULT_LAYER_ID);
    await fitToGeoJson(featureCollection, {
      padding: 70,
      maxZoom: 14,
      duration: 900,
    });
  } catch (error) {
    errorMessage.value =
      error instanceof Error ? error.message : "Failed to render map layer.";
  } finally {
    closeSidebarOnMobile();
  }
};

onMounted(() => {
  if (!mapContainer.value) {
    return;
  }
  createMap(mapContainer.value);
});

onBeforeUnmount(() => {
  destroyMap();
});
</script>

<template>
  <div
    class="relative h-screen w-screen overflow-hidden bg-slate-200 text-slate-800"
  >
    <div class="flex h-full w-full">
      <aside
        class="fixed inset-y-0 left-0 z-40 h-full w-[88%] max-w-sm border-r border-slate-300 bg-slate-100 shadow-2xl shadow-slate-400/20 transition-transform duration-200 lg:static lg:z-10 lg:w-[30%] lg:min-w-[340px] lg:max-w-[460px] lg:translate-x-0"
        :class="
          isSidebarOpen ? 'translate-x-0' : '-translate-x-full lg:translate-x-0'
        "
      >
        <div class="flex h-full flex-col">
          <header class="border-b border-slate-200 px-6 py-5 sm:px-7 sm:py-6">
            <div class="flex items-start justify-between gap-4">
              <div>
                <h1
                  class="text-2xl font-semibold tracking-tight text-slate-900 sm:text-3xl"
                >
                  SolarScout
                </h1>
                <p class="mt-1 text-sm text-slate-600">
                  Geospatial web application that analyzes OpenStreetMap data to
                  identify optimal solar farm locations in the state of Bremen.
                </p>
              </div>
              <button
                type="button"
                class="rounded-md border border-slate-300 bg-white px-3 py-1.5 text-xs font-semibold text-slate-700 shadow-sm transition hover:bg-slate-50 lg:hidden"
                @click="closeSidebar"
              >
                Close
              </button>
            </div>
          </header>

          <section class="flex-1 overflow-y-auto px-6 py-5 sm:px-7 sm:py-6">
            <div class="space-y-6">
              <div class="space-y-2">
                <div class="flex items-center justify-between">
                  <label
                    for="buffer-distance"
                    class="text-sm font-medium text-slate-700"
                  >
                    Distance to Settlements
                  </label>
                  <span
                    class="rounded bg-slate-200 px-2 py-1 text-xs font-semibold text-slate-700"
                  >
                    {{ bufferDistance }} m
                  </span>
                </div>
                <input
                  id="buffer-distance"
                  v-model.number="bufferDistance"
                  type="range"
                  min="0"
                  max="2000"
                  step="50"
                  class="h-2 w-full cursor-pointer appearance-none rounded-lg bg-slate-300 accent-emerald-600"
                />
              </div>

              <div class="space-y-2">
                <label class="text-sm font-medium text-slate-700"
                  >Exclude Nature Reserves</label
                >
                <button
                  type="button"
                  class="flex w-full items-center justify-between rounded-lg border px-4 py-3 transition"
                  :class="
                    excludeNature
                      ? 'border-emerald-300 bg-emerald-50 text-emerald-800'
                      : 'border-slate-300 bg-white text-slate-700'
                  "
                  @click="excludeNature = !excludeNature"
                >
                  <span class="text-sm font-medium">
                    {{ excludeNature ? "Enabled" : "Disabled" }}
                  </span>
                  <span
                    class="h-6 w-11 rounded-full p-1 transition"
                    :class="excludeNature ? 'bg-emerald-500' : 'bg-slate-400'"
                  >
                    <span
                      class="block h-4 w-4 rounded-full bg-white transition"
                      :class="excludeNature ? 'translate-x-5' : ''"
                    />
                  </span>
                </button>
              </div>

              <div class="space-y-2">
                <label for="min-area" class="text-sm font-medium text-slate-700"
                  >Min Area (ha)</label
                >
                <input
                  id="min-area"
                  v-model.number="minArea"
                  type="number"
                  min="0.1"
                  step="0.1"
                  class="w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-slate-800 shadow-sm outline-none ring-emerald-400 focus:ring-2"
                />
              </div>

              <div class="space-y-2">
                <div class="flex items-center justify-between">
                  <label
                    for="max-grid-distance"
                    class="text-sm font-medium text-slate-700"
                  >
                    Max Grid Distance
                  </label>
                  <span
                    class="rounded bg-slate-200 px-2 py-1 text-xs font-semibold text-slate-700"
                  >
                    {{ maxGridDistance }} m
                  </span>
                </div>
                <input
                  id="max-grid-distance"
                  v-model.number="maxGridDistance"
                  type="range"
                  min="100"
                  max="10000"
                  step="100"
                  class="h-2 w-full cursor-pointer appearance-none rounded-lg bg-slate-300 accent-emerald-600"
                />
              </div>
            </div>

            <button
              type="button"
              class="mt-7 inline-flex w-full items-center justify-center rounded-lg bg-emerald-600 px-4 py-3 text-sm font-semibold text-white shadow-lg shadow-emerald-600/25 transition hover:bg-emerald-700 disabled:cursor-not-allowed disabled:bg-emerald-400"
              :disabled="isAnalyzing"
              @click="handleAnalyze"
            >
              <span v-if="isAnalyzing" class="inline-flex items-center gap-2">
                <span
                  class="h-4 w-4 animate-spin rounded-full border-2 border-white/40 border-t-white"
                />
                Analyzing...
              </span>
              <span v-else>Analyze Sites</span>
            </button>

            <div
              v-if="isAnalyzing"
              class="mt-4 rounded-xl border border-slate-300 bg-white p-4 shadow-sm"
            >
              <div class="flex items-center gap-3">
                <span
                  class="h-5 w-5 animate-spin rounded-full border-2 border-slate-300 border-t-emerald-600"
                />
                <p class="text-sm font-semibold text-slate-800">
                  Analysis in progress...
                </p>
              </div>
              <p class="mt-1 text-xs text-slate-600">
                Evaluating parcels, exclusion zones, and grid distance.
              </p>
            </div>

            <p
              v-if="errorMessage"
              class="mt-4 rounded-lg border border-rose-300 bg-rose-50 px-3 py-2 text-sm text-rose-700"
            >
              {{ errorMessage }}
            </p>

            <div
              v-if="hasSummary"
              class="mt-6 rounded-xl border border-slate-300 bg-white p-4 shadow-sm"
            >
              <p
                class="text-xs font-semibold uppercase tracking-wide text-slate-500"
              >
                Results Summary
              </p>
              <p class="mt-2 text-lg font-semibold text-slate-900">
                {{ resultCount }} sites found
              </p>
              <p class="mt-1 text-sm text-slate-700">
                Total area:
                <span class="font-semibold">{{ totalArea.toFixed(2) }}</span>
                hectares
              </p>
            </div>
          </section>

          <footer
            class="border-t border-slate-200 bg-slate-50 px-6 py-4 sm:px-7"
          >
            <div
              class="rounded-lg border border-slate-300 bg-white p-3 shadow-sm"
            >
              <p
                class="text-xs font-semibold uppercase tracking-wide text-slate-600"
              >
                Limitations
              </p>
              <p class="mt-1 text-xs text-slate-700">
                Data Quality: Relies on OSM completeness; protected areas may be
                underrepresented.
              </p>
            </div>
          </footer>
        </div>
      </aside>

      <main class="h-full flex-1">
        <div ref="mapContainer" class="h-full w-full" />
      </main>
    </div>

    <button
      type="button"
      class="absolute left-4 top-4 z-30 rounded-md border border-slate-300 bg-white/95 px-3 py-2 text-sm font-semibold text-slate-700 shadow-lg shadow-slate-900/10 backdrop-blur transition hover:bg-white lg:hidden"
      @click="toggleSidebar"
    >
      {{ isSidebarOpen ? "Hide Controls" : "Show Controls" }}
    </button>

    <div
      v-if="isSidebarOpen"
      class="fixed inset-0 z-30 bg-slate-900/45 lg:hidden"
      @click="closeSidebar"
    />
  </div>
</template>
