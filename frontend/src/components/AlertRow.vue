<script setup>
import { computed } from "vue";
import { fmtAge, tierClass, tierLabel } from "../api.js";
import { evidenceText } from "../lib/patient.js";

const props = defineProps({ alert: { type: Object, required: true } });
defineEmits(["ack", "resolve"]);

const evidence = computed(() => evidenceText(props.alert));
</script>

<template>
  <article class="alert-item stripe" :class="tierClass(alert.tier)">
    <div class="row between">
      <span class="badge" :class="tierClass(alert.tier)">{{ tierLabel(alert.tier) }}</span>
      <span class="muted">
        {{ fmtAge(alert.age_s) }}<template v-if="alert.overdue"> · <b style="color: var(--bad)">overdue</b></template>
      </span>
    </div>
    <div class="reason">{{ alert.reason }}</div>
    <div class="muted" style="margin-top: 4px">
      {{ alert.display_status }}<template v-if="alert.next_action"> · Next: {{ alert.next_action }}</template>
    </div>
    <div v-if="evidence" class="muted">Evidence: {{ evidence }}</div>
    <div class="actions">
      <button v-if="alert.status === 'open'" class="btn btn-primary" type="button" @click="$emit('ack', alert)">Acknowledge</button>
      <span v-else class="badge plain">Acknowledged by {{ alert.acknowledged_by || "" }}</span>
      <button class="btn btn-danger" type="button" @click="$emit('resolve', alert)">Resolve…</button>
    </div>
  </article>
</template>
