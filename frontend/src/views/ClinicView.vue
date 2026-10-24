<script setup>
import { computed, ref } from "vue";
import { api, fmtDateTime, toast } from "../api.js";
import { usePolling } from "../lib/poll.js";
import { filterPatients } from "../lib/filters.js";
import PatientCard from "../components/PatientCard.vue";

const rows = ref([]);
const counts = ref({ patients: 0, need_action: 0, overdue: 0, unknown: 0 });
const brokerConnected = ref(true);
const generatedAt = ref(null);
const error = ref("");
const loaded = ref(false);
const program = ref("");
const status = ref("");
const dialog = ref(null);
const formError = ref("");

const filtered = computed(() => filterPatients(rows.value, { program: program.value, status: status.value }));
const emergencies = computed(() => rows.value.filter((p) => p.tier === "emergency").length);
const stats = computed(() => [
  { label: "Patients", value: counts.value.patients, hot: false },
  { label: "Need action", value: counts.value.need_action, hot: true, bad: emergencies.value > 0 },
  { label: "Overdue", value: counts.value.overdue, hot: true, bad: true },
  { label: "No data", value: counts.value.unknown, hot: false },
]);

async function load() {
  try {
    const data = await api("/api/clinic/worklist");
    rows.value = data.patients;
    counts.value = data.counts;
    brokerConnected.value = data.broker_connected;
    generatedAt.value = data.generated_at;
    loaded.value = true;
    error.value = "";
  } catch (e) {
    error.value = loaded.value ? "Connection problem: " + e.message + " (showing last data)" : e.message;
  }
}

function openDialog() {
  formError.value = "";
  dialog.value.showModal();
}

async function submit(event) {
  event.preventDefault();
  const form = event.target;
  const fields = Object.fromEntries(new FormData(form));
  if (!fields.caregiver_name) delete fields.caregiver_name;
  fields.caregiver_available = fields.caregiver_name ? 1 : 0;
  try {
    await api("/api/patients", { method: "POST", body: JSON.stringify(fields) });
    dialog.value.close();
    form.reset();
    toast("Patient added");
    load();
  } catch (e) {
    formError.value = e.message;
  }
}

usePolling(load, 10000);
</script>

<template>
  <section>
    <div v-if="!brokerConnected" class="banner">
      Live data is unavailable (server cannot reach the MQTT broker). Patient status is shown as unknown.
    </div>
  </section>

  <div class="page-head">
    <h1>Remote Care Clinic</h1>
    <p class="sub">Who needs attention today? Most urgent first.</p>
  </div>

  <section class="stats" aria-live="polite">
    <div v-for="stat in stats" :key="stat.label" class="stat" :class="{ hot: stat.hot && stat.value > 0, bad: stat.bad }">
      <b>{{ stat.value }}</b><span>{{ stat.label }}</span>
    </div>
  </section>

  <section class="card toolbar">
    <label>Program
      <select v-model="program">
        <option value="">All programs</option>
        <option value="hospice">Hospice</option>
        <option value="telehealth">Telehealth</option>
      </select>
    </label>
    <label>Show
      <select v-model="status">
        <option value="">Everyone</option>
        <option value="action">Needs action</option>
        <option value="overdue">Overdue</option>
      </select>
    </label>
    <button class="btn btn-primary" type="button" @click="openDialog">+ Add patient</button>
  </section>

  <p class="error" role="alert">{{ error }}</p>

  <section class="worklist" aria-live="polite">
    <PatientCard v-for="patient in filtered" :key="patient.patient_id" :patient="patient" />
    <div v-if="!filtered.length" class="card empty">
      {{ rows.length ? 'No patients match this filter.' : 'No patients yet. Click “+ Add patient” to start.' }}
    </div>
  </section>

  <p class="muted" style="margin-top: 12px">Updated {{ fmtDateTime(generatedAt) }} · refreshes every 10 s</p>

  <dialog ref="dialog">
    <form @submit="submit">
      <h2>Add patient</h2>
      <label>Name<input name="display_name" required autocomplete="off"></label>
      <label>Date of birth<input name="dob" type="date" required></label>
      <label>Program
        <select name="program">
          <option value="hospice">Hospice</option>
          <option value="telehealth">Telehealth</option>
        </select>
      </label>
      <label>Device ID<input name="device_id" required placeholder="esp32" autocomplete="off"></label>
      <p class="muted">Use <b>esp32</b> for the real board, or <b>sim01</b> / <b>sim02</b> for the simulator.</p>
      <label>Caregiver (optional)<input name="caregiver_name" autocomplete="off"></label>
      <p class="error" role="alert">{{ formError }}</p>
      <div class="btns">
        <button class="btn" type="button" @click="dialog.close()">Cancel</button>
        <button class="btn btn-primary" type="submit">Create patient</button>
      </div>
    </form>
  </dialog>
</template>
