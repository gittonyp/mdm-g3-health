<script setup>
import { computed, ref, watch } from "vue";
import { useRoute } from "vue-router";
import { ageSeconds, api, fmtAge, fmtDateTime, fmtValue, toast, tierClass, tierLabel, vitalState } from "../api.js";
import { usePolling } from "../lib/poll.js";
import { baselineText, worstTier } from "../lib/patient.js";
import TrendChart from "../components/TrendChart.vue";
import AlertRow from "../components/AlertRow.vue";

const route = useRoute();
const detail = ref(null);
const trends = ref(null);
const hours = ref(1);
const error = ref("");
const loaded = ref(false);
const resolveDialog = ref(null);
const resolveError = ref("");
const resolving = ref(null);
const resolveReason = ref("");
const noteError = ref("");

const patientId = computed(() => String(route.params.id));

const tier = computed(() => (detail.value ? worstTier(detail.value.open_alerts, detail.value.latest_vital) : "unknown"));
const latest = computed(() => detail.value?.latest_vital || null);
const age = computed(() => (latest.value ? ageSeconds(latest.value.ts) : null));
const fresh = computed(() => latest.value && age.value != null && age.value <= 90 && latest.value.finger !== 0);
const tiles = computed(() => {
  if (!fresh.value) return [];
  const v = latest.value;
  return [
    { label: "Heart rate", kind: "hr", value: v.hr, unit: "bpm", digits: 0 },
    { label: "SpO2", kind: "spo2", value: v.spo2, unit: "%", digits: 0 },
    { label: "Temperature", kind: "temp", value: v.temp, unit: "°C", digits: 1 },
  ];
});
const staleNote = computed(() => {
  if (fresh.value) return "";
  if (!latest.value) return "No live values: no readings yet.";
  if (latest.value.finger === 0 && age.value <= 90) return "No live values: no finger on the sensor.";
  return "No live values: last reading was " + fmtAge(age.value) + ".";
});
const profile = computed(() => {
  const p = detail.value?.patient;
  if (!p) return [];
  const fields = [
    ["Program", p.program],
    ["Date of birth", p.dob],
    ["Condition", p.primary_condition],
    ["Reason for monitoring", p.reason_for_monitoring],
    ["Goals of care", p.goals_of_care],
    ["Mobility", p.mobility],
    ["Medications", p.medications],
    [
      "Caregiver",
      p.caregiver_name ? p.caregiver_name + (p.caregiver_available ? "" : " (unavailable)") : "None assigned",
    ],
  ];
  return fields.filter(([, value]) => value).map(([label, value]) => ({ label, value }));
});

async function loadDetail() {
  try {
    const data = await api("/api/patients/" + encodeURIComponent(patientId.value));
    detail.value = data;
    document.title = data.patient.display_name + " - Remote Care";
    error.value = "";
    loaded.value = true;
  } catch (e) {
    error.value = e.message;
    if (!loaded.value) detail.value = null;
  }
}

async function loadTrends() {
  try {
    trends.value = await api(
      "/api/patients/" + encodeURIComponent(patientId.value) + "/trends?hours=" + hours.value
    );
  } catch {
    /* the error line reports connectivity problems */
  }
}

const { run: runDetail } = usePolling(loadDetail, 5000);
const { run: runTrends } = usePolling(loadTrends, 20000);

watch(patientId, () => {
  detail.value = null;
  trends.value = null;
  loaded.value = false;
  runDetail();
  runTrends();
});

function setHours(value) {
  hours.value = value;
  runTrends();
}

async function acknowledge(alert) {
  try {
    await api("/api/alerts/" + alert.id + "/ack", { method: "POST" });
    toast("Alert acknowledged");
    runDetail();
  } catch (e) {
    toast(e.message, true);
  }
}

function openResolve(alert) {
  resolving.value = alert.id;
  resolveReason.value = alert.reason;
  resolveError.value = "";
  resolveDialog.value.showModal();
}

async function submitResolve(event) {
  event.preventDefault();
  const note = new FormData(event.target).get("note").trim();
  if (!note) {
    resolveError.value = "A note is required.";
    return;
  }
  try {
    await api("/api/alerts/" + resolving.value + "/resolve", {
      method: "POST",
      body: JSON.stringify({ note }),
    });
    resolveDialog.value.close();
    toast("Alert resolved");
    runDetail();
    runTrends();
  } catch (e) {
    resolveError.value = e.message;
  }
}

async function submitNote(event) {
  event.preventDefault();
  const form = event.target;
  const fields = Object.fromEntries(new FormData(form));
  try {
    await api("/api/patients/" + encodeURIComponent(patientId.value) + "/notes", {
      method: "POST",
      body: JSON.stringify(fields),
    });
    form.elements.text.value = "";
    noteError.value = "";
    toast("Note added");
    runDetail();
    runTrends();
  } catch (e) {
    noteError.value = e.message;
  }
}
</script>

<template>
  <RouterLink class="back" to="/clinic">← Back to worklist</RouterLink>
  <p class="error" role="alert">{{ error }}</p>

  <section v-if="detail">
    <section class="card stripe" :class="tierClass(tier)">
      <div class="row between">
        <h1>{{ detail.patient.display_name }} <small class="muted">{{ detail.patient.id }}</small></h1>
        <span class="badge" :class="tierClass(tier)">{{ tierLabel(tier) }}</span>
      </div>
      <p class="muted" style="margin-top: 6px">
        <template v-if="detail.device">Device <b>{{ detail.device.device_id }}</b> · {{ latest ? 'last reading ' + fmtAge(age) : 'no readings yet' }}</template>
        <template v-else>No device linked</template>
        · {{ baselineText(detail.baseline) }}
      </p>
      <div v-if="fresh" class="vitals">
        <div v-for="tile in tiles" :key="tile.kind" class="vital" :class="vitalState(tile.kind, tile.value).cls">
          <div class="label">{{ tile.label }}</div>
          <div class="value">{{ fmtValue(tile.value, tile.digits) }}<small v-if="tile.value != null">{{ tile.unit }}</small></div>
          <div class="state">{{ vitalState(tile.kind, tile.value).text }}</div>
        </div>
      </div>
      <div v-else class="vitals">
        <div class="vitals-note">{{ staleNote }}</div>
      </div>
      <div class="profile">
        <div v-for="field in profile" :key="field.label">
          <span>{{ field.label }}</span><b>{{ field.value }}</b>
        </div>
      </div>
    </section>

    <section class="card">
      <div class="row between" style="margin-bottom: 12px">
        <h2 style="margin: 0">Trends</h2>
        <div class="seg" role="group" aria-label="Time range">
          <button v-for="h in [1, 6, 24]" :key="h" type="button" :class="{ on: hours === h }" @click="setHours(h)">{{ h }} h</button>
        </div>
      </div>
      <div class="charts">
        <TrendChart title="Heart rate (bpm)" :series="trends?.series || []" metric-key="hr" :baseline="trends?.baseline?.hr ?? null" :markers="trends?.markers || []" :decimals="0" />
        <TrendChart title="SpO2 (%)" :series="trends?.series || []" metric-key="spo2" :baseline="trends?.baseline?.spo2 ?? null" :markers="trends?.markers || []" :decimals="0" />
        <TrendChart title="Temperature (°C)" :series="trends?.series || []" metric-key="temp" :baseline="trends?.baseline?.temp ?? null" :markers="trends?.markers || []" :decimals="1" />
      </div>
      <p class="legend">Vertical lines mark alerts and notes (hover for details). The dashed green line is the patient's own baseline, once calibrated.</p>
    </section>

    <section class="card">
      <h2>Open alerts</h2>
      <AlertRow
        v-for="alert in detail.open_alerts"
        :key="alert.id"
        :alert="alert"
        @ack="acknowledge"
        @resolve="openResolve"
      />
      <div v-if="!detail.open_alerts.length" class="empty">No open alerts.</div>
    </section>

    <section class="card">
      <h2>Recent alert history</h2>
      <div class="table-wrap">
        <table v-if="detail.recent_alerts.length">
          <thead><tr><th>Time</th><th>Level</th><th>Reason</th><th>Status</th></tr></thead>
          <tbody>
            <tr v-for="alert in detail.recent_alerts" :key="alert.id">
              <td>{{ fmtDateTime(alert.created_at) }}</td>
              <td><span class="badge" :class="tierClass(alert.tier)">{{ tierLabel(alert.tier) }}</span></td>
              <td>{{ alert.reason }}</td>
              <td>{{ alert.status === 'resolved' ? 'Resolved' + (alert.resolution_note ? ': ' + alert.resolution_note : '') : (alert.display_status || alert.status) }}</td>
            </tr>
          </tbody>
        </table>
        <div v-else class="empty">No alerts recorded yet.</div>
      </div>
    </section>

    <section class="card">
      <h2>Notes</h2>
      <form class="note-form" @submit="submitNote">
        <label>Type
          <select name="kind">
            <option value="clinical">Clinical</option>
            <option value="caregiver">Caregiver</option>
            <option value="visit">Visit</option>
            <option value="follow_up">Follow-up</option>
          </select>
        </label>
        <label>Note<input name="text" required autocomplete="off" placeholder="Write a note…"></label>
        <button class="btn btn-primary" type="submit">Add note</button>
      </form>
      <p class="error" role="alert">{{ noteError }}</p>
      <div class="notes-list">
        <div v-for="note in detail.notes" :key="note.id ?? note.ts" class="note">
          <span class="badge plain">{{ note.kind.replace('_', '-') }}</span> {{ note.text }}
          <div class="who">{{ note.author }} · {{ fmtDateTime(note.ts) }}</div>
        </div>
        <div v-if="!detail.notes.length" class="empty">No notes yet.</div>
      </div>
    </section>
  </section>

  <dialog ref="resolveDialog">
    <form @submit="submitResolve">
      <h2>Resolve alert</h2>
      <p class="muted">{{ resolveReason }}</p>
      <label>What was done? (required)<textarea name="note" required></textarea></label>
      <p class="error" role="alert">{{ resolveError }}</p>
      <div class="btns">
        <button class="btn" type="button" @click="resolveDialog.close()">Cancel</button>
        <button class="btn btn-danger" type="submit">Resolve</button>
      </div>
    </form>
  </dialog>
</template>
