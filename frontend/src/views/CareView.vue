<script setup>
import { computed, ref, watch } from "vue";
import { RouterLink, useRoute } from "vue-router";
import { api, fmtAge, setActor, tierClass, toast } from "../api.js";
import { usePolling } from "../lib/poll.js";
import { careAnswer, careHeadline } from "../lib/care.js";

setActor("caregiver");

const route = useRoute();
const patients = ref([]);
const data = ref(null);
const error = ref("");
const busy = ref(null);

const patientId = computed(() => (route.query.patient ? String(route.query.patient) : ""));
const tasks = computed(() => data.value?.tasks || []);

async function load() {
  try {
    if (!patientId.value) {
      patients.value = await api("/api/patients");
      data.value = null;
    } else {
      data.value = await api("/api/care/tasks?patient_id=" + encodeURIComponent(patientId.value));
    }
    error.value = "";
  } catch (e) {
    error.value = e.message;
    if (!data.value) patients.value = [];
  }
}

async function respond(task, response) {
  busy.value = task.id;
  try {
    await api("/api/alerts/" + task.id + "/caregiver-response", {
      method: "POST",
      body: JSON.stringify({ response }),
    });
    toast("Sent. Thank you.");
  } catch (e) {
    toast(e.message, true);
  } finally {
    busy.value = null;
  }
  load();
}

const { run } = usePolling(load, 5000);
watch(patientId, () => {
  data.value = null;
  patients.value = [];
  run();
});
</script>

<template>
  <div class="page-head">
    <h1>{{ patientId && data ? 'Tasks for ' + data.patient.display_name : 'Caregiver tasks' }}</h1>
    <p class="sub">
      <template v-if="patientId"><RouterLink to="/care">Switch patient</RouterLink></template>
      <template v-else>Choose who you are caring for.</template>
    </p>
  </div>

  <p class="error" role="alert">{{ error }}</p>

  <section v-if="!patientId">
    <div v-if="patients.length" class="picker">
      <RouterLink
        v-for="patient in patients"
        :key="patient.id"
        class="card btn-lg"
        style="display: block; text-decoration: none; color: inherit; margin: 0"
        :to="'/care?patient=' + encodeURIComponent(patient.id)"
      >
        <b>{{ patient.display_name }}</b>
        <div class="muted">{{ patient.id }}</div>
      </RouterLink>
    </div>
    <div v-else class="card empty">No patients yet.</div>
  </section>

  <section v-else aria-live="polite">
    <div v-if="data && !data.patient.caregiver_available" class="banner">
      No caregiver is assigned, so the doctor owns these tasks.
    </div>
    <article v-for="task in tasks" :key="task.id" class="card task stripe" :class="tierClass(task.tier)">
      <div class="row between">
        <h2>{{ careHeadline(task.tier) }}</h2>
        <span class="muted">{{ fmtAge(task.age_s) }}</span>
      </div>
      <p class="instruction">{{ task.instruction }}</p>
      <p class="muted">Why: {{ task.reason }}</p>
      <div v-if="task.caregiver_response" class="responded">
        You answered: {{ careAnswer(task.caregiver_response) }}
      </div>
      <div v-if="task.owner === 'caregiver'" class="buttons">
        <button class="btn btn-primary btn-lg" type="button" :disabled="busy === task.id" @click="respond(task, 'done')">Done</button>
        <button class="btn btn-lg" type="button" :disabled="busy === task.id" @click="respond(task, 'cannot')">I can’t do this</button>
        <button class="btn btn-lg" type="button" :disabled="busy === task.id" @click="respond(task, 'contact_doctor')">Call the doctor</button>
      </div>
      <div v-else class="responded" style="color: var(--muted)">
        The doctor is handling this. Nothing for you to do.
      </div>
    </article>
    <div v-if="data && !tasks.length" class="card empty">Nothing needs doing right now. ✔</div>
    <div v-else-if="!data" class="skeleton"></div>
  </section>
</template>
