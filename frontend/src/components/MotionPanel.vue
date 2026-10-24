<script setup>
import { computed } from "vue";
import Sparkline from "./Sparkline.vue";

const props = defineProps({
  motion: { type: Object, default: () => ({}) },
  points: { type: Array, default: () => [] },
});

const ACT = { rest: "At rest", walk: "Walking", run: "Running", fall: "Fall detected" };
const activity = computed(() => ACT[props.motion.act] || "—");

function num(value, digits) {
  if (value == null || Number.isNaN(Number(value))) return "—";
  return Number(value).toFixed(digits);
}
</script>

<template>
  <section class="card">
    <h2>Movement and posture</h2>
    <div class="motion">
      <div>
        <div class="act">{{ activity }}</div>
        <div class="axes">
          <div class="grp">Acceleration (g)</div>
          <div><em>X</em><span>{{ num(motion.ax, 2) }}</span></div>
          <div><em>Y</em><span>{{ num(motion.ay, 2) }}</span></div>
          <div><em>Z</em><span>{{ num(motion.az, 2) }}</span></div>
          <div class="grp">Rotation (°/s)</div>
          <div><em>X</em><span>{{ num(motion.gx, 1) }}</span></div>
          <div><em>Y</em><span>{{ num(motion.gy, 1) }}</span></div>
          <div><em>Z</em><span>{{ num(motion.gz, 1) }}</span></div>
        </div>
      </div>
      <Sparkline class="mag" :points="points" :min="0" :max="3" color="var(--ink)" />
    </div>
  </section>
</template>
