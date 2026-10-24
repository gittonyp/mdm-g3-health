<script setup>
import { computed } from "vue";

const props = defineProps({
  points: { type: Array, default: () => [] },
  min: { type: Number, default: 0 },
  max: { type: Number, default: 1 },
  color: { type: String, default: "currentColor" },
});

const path = computed(() => {
  const points = props.points || [];
  if (points.length < 2) return "";
  const span = props.max - props.min || 1;
  return points
    .map((value, index) => {
      const x = (index / (points.length - 1)) * 100;
      const y = 24 - ((Number(value) - props.min) / span) * 24;
      return x.toFixed(2) + "," + Math.max(0, Math.min(24, y)).toFixed(2);
    })
    .join(" ");
});
</script>

<template>
  <svg class="spark" viewBox="0 0 100 24" preserveAspectRatio="none" aria-hidden="true">
    <polyline v-if="path" :points="path" fill="none" :stroke="color" stroke-width="1.8" stroke-linejoin="round" stroke-linecap="round" />
  </svg>
</template>
