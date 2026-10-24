<script setup>
import { computed, ref } from "vue";
import { RouterLink, useRoute } from "vue-router";
import { api, getActor, setActor } from "../api.js";
import { usePolling } from "../lib/poll.js";

const route = useRoute();
const links = [
  ["/clinic", "Clinic"],
  ["/live", "Live"],
  ["/history", "History"],
  ["/care", "Caregiver"],
];

const actor = ref(getActor());
const health = ref({ text: "Checking…", cls: "" });
const showActor = computed(() => route.path.startsWith("/clinic"));

function changeActor(event) {
  actor.value = event.target.value;
  setActor(actor.value);
}

usePolling(async () => {
  try {
    const data = await api("/api/health");
    health.value = {
      text: data.mqtt_connected ? "MQTT connected" : "MQTT offline",
      cls: data.mqtt_connected ? "on" : "bad",
    };
  } catch {
    health.value = { text: "Server unreachable", cls: "bad" };
  }
}, 15000);
</script>

<template>
  <nav class="sn" aria-label="Main">
    <RouterLink class="sn-brand" to="/clinic">
      <span class="sn-logo" aria-hidden="true">
        <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="#fff" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
          <path d="M3 12h4l2-5 4 10 2-5h6" />
        </svg>
      </span>
      <b>Remote Care</b>
    </RouterLink>
    <RouterLink
      v-for="[to, label] in links"
      :key="to"
      class="sn-link"
      :class="{ active: route.path === to || (to === '/clinic' && route.path.startsWith('/clinic/')) }"
      :to="to"
      :aria-current="route.path === to ? 'page' : undefined"
    >{{ label }}</RouterLink>
    <span class="sn-spacer"></span>
    <label v-if="showActor">Viewing as
      <select :value="actor" @change="changeActor">
        <option value="doctor">Doctor</option>
        <option value="caregiver">Caregiver</option>
      </select>
    </label>
    <a class="sn-pill" href="/api/health" title="Server and MQTT status">
      <span class="sn-dot" :class="health.cls"></span>
      <span>{{ health.text }}</span>
    </a>
  </nav>
</template>
