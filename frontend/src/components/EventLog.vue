<script setup>
import { STATES } from "../lib/adaptive.js";

defineProps({
  entries: { type: Array, default: () => [] },
});
defineEmits(["clear"]);

function when(ts) {
  const date = new Date(ts);
  const today = new Date().toDateString();
  const time = date.toLocaleTimeString([], { hour12: false });
  return date.toDateString() === today
    ? time
    : date.toLocaleDateString([], { day: "numeric", month: "short" }) + " " + time;
}

function cls(status) {
  return (STATES[status] || {}).cls || "warn";
}
</script>

<template>
  <section class="card">
    <div class="row between" style="margin-bottom: 10px">
      <h2 style="margin: 0">Events</h2>
      <button class="ghost" type="button" @click="$emit('clear')">Clear log</button>
    </div>
    <ul class="log">
      <li v-for="entry in entries" :key="entry[0]" :class="cls(entry[8])">
        <time>{{ when(entry[0]) }}</time><i></i><span>{{ entry[9] }}</span>
      </li>
      <li v-if="!entries.length" class="empty">No events yet. Changes in patient status will appear here.</li>
    </ul>
  </section>
</template>
