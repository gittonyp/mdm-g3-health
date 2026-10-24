<script setup>
import { onBeforeUnmount, onMounted, ref, watch } from "vue";
import { drawLineChart } from "../lib/chart.js";

const props = defineProps({
  title: { type: String, required: true },
  series: { type: Array, default: () => [] },
  metricKey: { type: String, required: true },
  baseline: { type: Number, default: null },
  markers: { type: Array, default: () => [] },
  decimals: { type: Number, default: 0 },
});

const svg = ref(null);
let observer = null;

function render() {
  if (svg.value) {
    drawLineChart(svg.value, props.series, props.metricKey, {
      baseline: props.baseline,
      markers: props.markers,
      decimals: props.decimals,
    });
  }
}

watch(() => [props.series, props.baseline, props.markers], render, { deep: true });

onMounted(() => {
  render();
  observer = new ResizeObserver(render);
  observer.observe(svg.value);
});

onBeforeUnmount(() => {
  if (observer) observer.disconnect();
});
</script>

<template>
  <div class="chart">
    <h3><span>{{ title }}</span></h3>
    <svg ref="svg" role="img" :aria-label="title + ' trend'"></svg>
  </div>
</template>
