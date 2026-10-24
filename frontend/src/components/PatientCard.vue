<script setup>
import { computed } from "vue";
import { RouterLink } from "vue-router";
import { ageSeconds, fmtAge, fmtValue, qualityLabel, tierClass, tierLabel, vitalState } from "../api.js";

const props = defineProps({ patient: { type: Object, required: true } });

const age = computed(() => {
  const v = props.patient.latest_vital;
  return v ? fmtAge(ageSeconds(v.ts)) : "";
});
const program = computed(() =>
  props.patient.program ? props.patient.program.charAt(0).toUpperCase() + props.patient.program.slice(1) : ""
);
const showVitals = computed(() => props.patient.data_quality === "good" && !!props.patient.latest_vital);
const reason = computed(() =>
  props.patient.data_quality === "missing"
    ? "No device is linked to this patient."
    : "No live values shown (" + qualityLabel(props.patient.data_quality).toLowerCase() + ")."
);
const tiles = computed(() => {
  const v = props.patient.latest_vital;
  if (!v) return [];
  return [
    { label: "Heart rate", kind: "hr", value: v.hr, unit: "bpm", digits: 0 },
    { label: "SpO2", kind: "spo2", value: v.spo2, unit: "%", digits: 0 },
    { label: "Temperature", kind: "temp", value: v.temp, unit: "°C", digits: 1 },
  ];
});
const nextAction = computed(() => {
  const action = props.patient.next_action;
  if (!action) return "";
  return /^next/i.test(action) ? action : "Next: " + action;
});
</script>

<template>
  <RouterLink
    class="card patient-card stripe"
    :class="tierClass(patient.tier)"
    :to="'/clinic/patient/' + encodeURIComponent(patient.patient_id)"
  >
    <div class="row between">
      <h3>{{ patient.display_name }}<small>{{ patient.patient_id }}</small></h3>
      <div class="row">
        <span class="badge" :class="tierClass(patient.tier)">{{ tierLabel(patient.tier) }}</span>
        <span v-if="patient.overdue" class="badge tier-emergency">Overdue</span>
      </div>
    </div>
    <div class="why">{{ patient.what_changed }}</div>
    <div class="meta">
      {{ program }} · {{ patient.status }}<template v-if="nextAction"> · {{ nextAction }}</template><template v-if="age"> · Reading {{ age }}</template>
    </div>
    <div v-if="showVitals" class="vitals">
      <div v-for="tile in tiles" :key="tile.kind" class="vital" :class="vitalState(tile.kind, tile.value).cls">
        <div class="label">{{ tile.label }}</div>
        <div class="value">{{ fmtValue(tile.value, tile.digits) }}<small v-if="tile.value != null">{{ tile.unit }}</small></div>
        <div class="state">{{ vitalState(tile.kind, tile.value).text }}</div>
      </div>
    </div>
    <div v-else class="vitals">
      <div class="vitals-note">{{ reason }}</div>
    </div>
  </RouterLink>
</template>
