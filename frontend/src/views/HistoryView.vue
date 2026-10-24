<script setup>
import { computed, ref } from "vue";
import { api, fmtDateTime, fmtValue } from "../api.js";
import { usePolling } from "../lib/poll.js";

const health = ref(null);
const stats = ref({ devices: 0, messages: 0, vitals: 0, anomalies: 0 });
const devices = ref([]);
const anomalies = ref([]);
const vitals = ref([]);
const selected = ref("");
const lastRefresh = ref("");
const statusLine = ref("Loading…");
const offline = ref(false);

const deviceOptions = computed(() =>
  devices.value.map((d) => ({ value: d.device_id, label: d.device_id }))
);

function statusBadge(status) {
  const value = String(status || "offline").toLowerCase();
  return { text: value, cls: value === "online" ? "normal" : "offline" };
}

function levelBadge(level) {
  const value = String(level || "normal").toLowerCase();
  const cls = value === "alert" ? "alert" : value === "watch" ? "watch" : "normal";
  return { text: value, cls };
}

async function refresh() {
  try {
    const filter = selected.value ? "&device_id=" + encodeURIComponent(selected.value) : "";
    const [h, s, d, a, v] = await Promise.all([
      api("/api/health"),
      api("/api/stats"),
      api("/api/devices"),
      api("/api/anomalies?limit=20" + filter),
      api("/api/vitals?limit=40" + filter),
    ]);
    health.value = h;
    stats.value = s;
    devices.value = d;
    anomalies.value = a;
    vitals.value = v;
    lastRefresh.value = "Updated " + new Date().toLocaleTimeString([], { hour12: false });
    statusLine.value = "Root " + h.root + " · " + s.vitals + " vitals · " + s.anomalies + " anomalies";
    offline.value = false;
    if (selected.value && !d.some((device) => device.device_id === selected.value)) {
      selected.value = "";
    }
  } catch (e) {
    offline.value = true;
    statusLine.value = e.message;
  }
}

usePolling(refresh, 3000);
</script>

<template>
  <div class="page-head">
    <div class="row between">
      <div>
        <h1>History</h1>
        <div class="sub">Persisted MQTT readings and anomaly log</div>
      </div>
      <div class="row">
        <a class="btn" href="/api/export.csv">Download CSV</a>
        <a class="btn" href="/docs" target="_blank" rel="noopener">API docs</a>
      </div>
    </div>
  </div>

  <div class="pills" style="display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 14px">
    <div class="pill" style="display: flex; gap: 7px; align-items: center; background: var(--panel); border: 1px solid var(--line); border-radius: 999px; padding: 6px 12px; font-size: 13px">
      <i class="dot" :class="offline ? 'bad' : 'on'"></i><span>{{ offline ? 'API offline' : 'API online' }}</span>
    </div>
    <div class="pill" style="display: flex; gap: 7px; align-items: center; background: var(--panel); border: 1px solid var(--line); border-radius: 999px; padding: 6px 12px; font-size: 13px">
      <i class="dot" :class="health?.mqtt_connected ? 'on' : 'bad'"></i>
      <span>{{ health?.mqtt_connected ? 'MQTT connected' : 'MQTT offline' }}</span>
    </div>
    <div class="pill" style="background: var(--panel); border: 1px solid var(--line); border-radius: 999px; padding: 6px 12px; font-size: 13px">{{ health?.broker || 'Broker' }}</div>
    <div class="pill" style="background: var(--panel); border: 1px solid var(--line); border-radius: 999px; padding: 6px 12px; font-size: 13px">{{ stats.devices }} device{{ stats.devices === 1 ? '' : 's' }}</div>
    <div class="pill" style="background: var(--panel); border: 1px solid var(--line); border-radius: 999px; padding: 6px 12px; font-size: 13px">{{ stats.messages }} messages</div>
  </div>

  <div class="row" style="margin-bottom: 14px">
    <label>Device
      <select v-model="selected" @change="refresh">
        <option value="">All devices</option>
        <option v-for="option in deviceOptions" :key="option.value" :value="option.value">{{ option.label }}</option>
      </select>
    </label>
    <button class="btn" type="button" @click="refresh">Refresh</button>
    <span class="muted">{{ lastRefresh }}</span>
  </div>

  <section class="card">
    <h2>Devices</h2>
    <div v-if="devices.length" class="table-wrap">
      <table>
        <thead><tr><th>Device</th><th>Status</th><th>Last seen</th><th style="text-align: right">HR</th><th style="text-align: right">SpO2</th><th style="text-align: right">Temp</th><th>Activity</th><th>State</th></tr></thead>
        <tbody>
          <tr v-for="device in devices" :key="device.device_id">
            <td class="mono">{{ device.device_id }}</td>
            <td><span class="badge" :class="statusBadge(device.status).cls">{{ statusBadge(device.status).text }}</span></td>
            <td>{{ fmtDateTime(device.last_seen) }}</td>
            <td style="text-align: right">{{ fmtValue(device.last_hr) }}</td>
            <td style="text-align: right">{{ fmtValue(device.last_spo2) }}</td>
            <td style="text-align: right">{{ fmtValue(device.last_temp, 1) }}</td>
            <td>{{ device.last_activity || '—' }}</td>
            <td>{{ device.last_state || '—' }}</td>
          </tr>
        </tbody>
      </table>
    </div>
    <div v-else class="empty">No devices have published yet.</div>
  </section>

  <div class="grid2" style="display: grid; grid-template-columns: 1fr 1fr; gap: 14px">
    <section class="card">
      <h2>Recent anomalies</h2>
      <div v-if="anomalies.length" class="table-wrap">
        <table>
          <thead><tr><th>Time</th><th>Device</th><th>Level</th><th style="text-align: right">Score</th><th>Reason</th></tr></thead>
          <tbody>
            <tr v-for="(item, index) in anomalies" :key="item.id ?? index">
              <td>{{ fmtDateTime(item.ts) }}</td>
              <td class="mono">{{ item.device_id }}</td>
              <td><span class="badge" :class="levelBadge(item.level).cls">{{ levelBadge(item.level).text }}</span></td>
              <td style="text-align: right">{{ fmtValue(item.score, 2) }}</td>
              <td>{{ item.reason }}</td>
            </tr>
          </tbody>
        </table>
      </div>
      <div v-else class="empty">No anomalies recorded.</div>
    </section>

    <section class="card">
      <h2>Recent vitals</h2>
      <div v-if="vitals.length" class="table-wrap">
        <table>
          <thead><tr><th>Time</th><th>Device</th><th style="text-align: right">HR</th><th style="text-align: right">SpO2</th><th style="text-align: right">HRV</th><th style="text-align: right">Temp</th><th>State</th></tr></thead>
          <tbody>
            <tr v-for="(item, index) in vitals" :key="item.id ?? index">
              <td>{{ fmtDateTime(item.ts) }}</td>
              <td class="mono">{{ item.device_id }}</td>
              <td style="text-align: right">{{ fmtValue(item.hr) }}</td>
              <td style="text-align: right">{{ fmtValue(item.spo2) }}</td>
              <td style="text-align: right">{{ fmtValue(item.hrv) }}</td>
              <td style="text-align: right">{{ fmtValue(item.temp, 1) }}</td>
              <td>{{ item.state || '—' }}</td>
            </tr>
          </tbody>
        </table>
      </div>
      <div v-else class="empty">No vital readings recorded.</div>
    </section>
  </div>

  <div class="row between" style="color: var(--muted); font-size: 12px; margin-top: 16px">
    <span>Data is stored in SQLite on the server.</span>
    <span>{{ statusLine }}</span>
  </div>
</template>
