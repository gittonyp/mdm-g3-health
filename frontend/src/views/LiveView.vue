<script setup>
import { computed, ref } from "vue";
import { toast } from "../api.js";
import { VITALS, stateInfo } from "../lib/adaptive.js";
import { useLiveFeed } from "../live/useLiveFeed.js";
import VitalTile from "../components/VitalTile.vue";
import MotionPanel from "../components/MotionPanel.vue";
import EventLog from "../components/EventLog.vue";

const {
  patients,
  selected,
  current,
  currentOnline,
  state,
  now,
  log,
  connected,
  feedText,
  events,
  lastReading,
  addPatient,
  removePatient,
  selectPatient,
  clearLog,
  downloadCsv,
  publishRecalibrate,
} = useLiveFeed();

const dialog = ref(null);
const formError = ref("");

const info = computed(() => stateInfo(state.value));
const bannerClass = computed(() => (state.value === "fall" ? "state-fall" : "state-" + info.value.cls));
const clock = computed(() => new Date(now.value).toLocaleTimeString([], { hour12: false }));
const pointsFor = (key) => (current.value ? current.value.buf[key] : []);
const valueFor = (key) => (current.value ? current.value.last[key] : null);

function openAdd() {
  formError.value = "";
  dialog.value.showModal();
}

function submitAdd(event) {
  event.preventDefault();
  const form = event.target;
  const name = form.elements.name.value.trim();
  const channel = form.elements.channel.value.trim().replace(/^\/+|\/+$/g, "");
  if (!name) {
    formError.value = "Enter the patient’s name.";
    return;
  }
  if (!channel) {
    formError.value = "Enter the MQTT channel.";
    return;
  }
  if (/[+#\s]/.test(channel)) {
    formError.value = "The channel can’t contain spaces, + or #.";
    return;
  }
  if (!addPatient(name, channel)) {
    formError.value = "That channel is already assigned to a patient.";
    return;
  }
  dialog.value.close();
  form.reset();
}

function remove() {
  if (!current.value) return;
  if (confirm("Remove " + current.value.name + " from the dashboard? Saved log entries are kept.")) {
    removePatient(current.value.channel);
  }
}

function download() {
  if (!downloadCsv()) toast("Nothing to save yet", true);
}

function recalibrate() {
  if (!publishRecalibrate()) {
    toast("Live feed is not connected", true);
    return;
  }
  toast("Recalibration sent");
}

function clear() {
  if (!confirm("Clear the saved log for all patients?")) return;
  clearLog();
  toast("Log cleared");
}

function onSelect(event) {
  selectPatient(event.target.value);
}

</script>

<template>
  <div class="live">
    <div class="page-head">
      <h1>Live monitor</h1>
      <div class="sub">Continuous monitoring from the wearable sensor node</div>
    </div>

    <div class="pills">
      <label class="sel">Patient
        <select :value="selected || ''" aria-label="Select patient" @change="onSelect">
          <option v-if="!patients.length" disabled value="">No patients added</option>
          <option v-for="patient in patients" :key="patient.channel" :value="patient.channel">
            {{ patient.name }}
          </option>
        </select>
      </label>
      <button class="ghost" type="button" @click="openAdd">Add patient</button>
      <div class="pill" title="Connection from this browser to the live data feed">
        <i class="dot" :class="connected ? 'on' : ''"></i>
        <span>{{ feedText }}</span>
      </div>
      <div class="pill">
        <i class="dot" :class="currentOnline ? 'on' : ''"></i>
        <span>{{ currentOnline ? 'Device online' : 'Device offline' }}</span>
      </div>
      <div class="pill">{{ clock }}</div>
    </div>

    <div class="who card">
      <div>
        <b>{{ current ? current.name : 'No patient added' }}</b>
        <span>{{ current ? 'MQTT channel: ' + current.channel : 'Use Add patient to start monitoring.' }}</span>
      </div>
      <button class="ghost" type="button" :disabled="!current" @click="remove">Remove patient</button>
    </div>

    <div class="live-banner" :class="bannerClass" role="status" aria-live="polite">
      <strong>{{ info.title }}</strong>
      <span>{{ info.hint }}</span>
    </div>

    <section class="vitals" aria-label="Vital signs">
      <VitalTile
        v-for="metric in VITALS"
        :key="metric.k"
        :metric="metric"
        :value="valueFor(metric.k)"
        :state="state"
        :points="pointsFor(metric.k)"
      />
    </section>

    <div class="lower">
      <MotionPanel :motion="current ? current.motion : {}" :points="pointsFor('mag')" />
      <EventLog :entries="events" @clear="clear" />
    </div>

    <div class="foot">
      <span>Last reading: <strong>{{ lastReading }}</strong> &nbsp;·&nbsp; Saved log: <strong>{{ log.length }}</strong> entries</span>
      <div class="btns">
        <button class="ghost" type="button" @click="download">Download log (CSV)</button>
        <button type="button" @click="recalibrate">Recalibrate sensors</button>
      </div>
    </div>

    <dialog ref="dialog">
      <form @submit="submitAdd">
        <h3 style="margin: 0 0 14px; font-size: 18px">Add patient</h3>
        <label>Patient name<input name="name" maxlength="40" autocomplete="off" required></label>
        <label>MQTT channel<input name="channel" maxlength="120" autocomplete="off" placeholder="mdm-g3-pcce/health" required></label>
        <p class="hint" style="font-size: 12px; color: var(--muted); margin: 8px 0">
          The channel (topic root) this patient’s monitor publishes to. Vitals, motion and events are read from it.
        </p>
        <p class="error" role="alert">{{ formError }}</p>
        <div class="btns" style="justify-content: flex-end">
          <button type="button" class="ghost" @click="dialog.close()">Cancel</button>
          <button type="submit">Add patient</button>
        </div>
      </form>
    </dialog>
  </div>
</template>
