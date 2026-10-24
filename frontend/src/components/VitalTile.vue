<script setup>
import { computed } from "vue";
import { fmtValue } from "../api.js";
import { sparkRange, vitalChip } from "../lib/adaptive.js";
import Sparkline from "./Sparkline.vue";

const props = defineProps({
  metric: { type: Object, required: true },
  value: { type: Number, default: null },
  state: { type: String, default: "offline" },
  points: { type: Array, default: () => [] },
});

const chip = computed(() => vitalChip(props.value, props.state));
const range = computed(() => sparkRange(props.metric.k, props.points));
const color = computed(() => (props.metric.k === "hr" ? "var(--state, currentColor)" : "var(--ink)"));
</script>

<template>
  <section class="card vital" :aria-label="metric.name">
    <div class="head">
      <span class="name">{{ metric.name }}</span>
      <span class="chip" :class="chip.cls">{{ chip.text }}</span>
    </div>
    <div class="val">
      <b>{{ fmtValue(value, metric.d) }}</b>
      <span>{{ metric.unit }}</span>
    </div>
    <Sparkline :points="points" :min="range[0]" :max="range[1]" :color="color" />
    <div class="rng">{{ metric.hint }}</div>
  </section>
</template>
