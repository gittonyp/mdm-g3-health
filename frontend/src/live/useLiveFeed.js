import { computed, onBeforeUnmount, onMounted, reactive, ref } from "vue";
import mqtt from "mqtt";
import { api } from "../api.js";
import { toCsv } from "../lib/csv.js";
import {
  applyTopic,
  createDevice,
  getAutoAdded,
  isAlive,
  loadLog,
  loadPatients,
  restoreDevices,
  saveLog,
  savePatients,
  selectedChannel,
  setAutoAdded,
  setState,
  LOGMAX,
} from "../lib/live.js";

const BROKER_URLS = [
  "wss://broker.hivemq.com:8884/mqtt",
  "ws://broker.hivemq.com:8000/mqtt",
];

export function useLiveFeed() {
  const patients = ref(loadPatients());
  const selected = ref(selectedChannel());
  const devices = reactive({});
  const log = ref(loadLog());
  const connected = ref(false);
  const feedText = ref("Live feed offline");
  const now = ref(Date.now());

  patients.value.forEach((patient) => {
    devices[patient.channel] = createDevice(patient);
  });
  restoreDevices(devices, log.value);
  if (!selected.value || !devices[selected.value]) {
    selected.value = patients.value[0] ? patients.value[0].channel : null;
  }

  const current = computed(() => (selected.value ? devices[selected.value] || null : null));
  const currentOnline = computed(() => !!current.value && isAlive(current.value, now.value));
  const state = computed(() => (current.value ? current.value.state : "offline"));
  const events = computed(() =>
    log.value
      .filter((row) => row[2] === selected.value && row[9])
      .slice(-30)
      .reverse()
  );
  const lastReading = computed(() =>
    current.value && current.value.lastAt
      ? new Date(current.value.lastAt).toLocaleTimeString([], { hour12: false })
      : "—"
  );

  let client = null;
  let urlIndex = 0;
  let failTimer = null;
  let tickTimer = null;
  let logTimer = null;
  let saveTimer = null;

  function addRow(device, event) {
    log.value.push([
      Date.now(),
      device.name,
      device.channel,
      device.last.hr ?? null,
      device.last.spo2 ?? null,
      device.last.hrv ?? null,
      device.last.temp ?? null,
      device.motion.act || "",
      device.state,
      event || "",
    ]);
    if (log.value.length > LOGMAX) log.value.splice(0, log.value.length - LOGMAX);
  }

  function persist() {
    saveLog(log.value);
  }

  function addPatient(name, channel) {
    if (patients.value.some((p) => p.channel === channel)) return false;
    patients.value.push({ name, channel });
    devices[channel] = createDevice({ name, channel });
    selected.value = channel;
    savePatients(patients.value, selected.value);
    if (client && client.connected) client.subscribe(channel + "/#");
    return true;
  }

  function removePatient(channel) {
    patients.value = patients.value.filter((p) => p.channel !== channel);
    delete devices[channel];
    if (client && client.connected) client.unsubscribe(channel + "/#");
    selected.value = patients.value[0] ? patients.value[0].channel : null;
    savePatients(patients.value, selected.value);
  }

  function selectPatient(channel) {
    selected.value = channel || null;
    savePatients(patients.value, selected.value);
  }

  function clearLog() {
    log.value = [];
    saveLog(log.value);
  }

  function downloadCsv() {
    if (typeof document === "undefined" || !log.value.length) return false;
    const blob = new Blob(["\ufeff" + toCsv(log.value)], { type: "text/csv;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = "vitals-log-" + new Date().toISOString().slice(0, 19).replace(/[:T]/g, "-") + ".csv";
    document.body.appendChild(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
    return true;
  }

  function publishRecalibrate() {
    if (!client || !client.connected || !selected.value) return false;
    client.publish(selected.value + "/cmd", "recalibrate");
    return true;
  }

  function onMessage(topic, payload) {
    const text = payload.toString();
    let best = null;
    for (const patient of patients.value) {
      if (topic.startsWith(patient.channel + "/") && (!best || patient.channel.length > best.length)) {
        best = patient.channel;
      }
    }
    const device = best && devices[best];
    if (!device) return;
    const key = topic.slice(best.length + 1);
    const event = applyTopic(device, key, text, Date.now());
    if (event) addRow(device, event);
  }

  function startClient() {
    if (typeof window === "undefined") return;
    const override = new URLSearchParams(location.search).get("broker");
    const urls = override ? [override] : BROKER_URLS;
    client = mqtt.connect(urls[urlIndex % urls.length], {
      clientId: "spa-" + Math.random().toString(16).slice(2, 8),
      reconnectPeriod: 2000,
      connectTimeout: 6000,
    });
    client.on("connect", () => {
      if (failTimer) clearTimeout(failTimer);
      connected.value = true;
      feedText.value = "Live feed connected";
      patients.value.forEach((patient) => client.subscribe(patient.channel + "/#"));
    });
    client.on("close", () => {
      connected.value = false;
      feedText.value = "Live feed offline";
    });
    client.on("error", (error) => {
      feedText.value = "Live feed error: " + (error.message || error);
    });
    client.on("message", onMessage);
    failTimer = setTimeout(() => {
      if (client && !client.connected) {
        client.end(true);
        client = null;
        urlIndex = (urlIndex + 1) % urls.length;
        startClient();
      }
    }, 7000);
  }

  async function autoAdd() {
    if (
      typeof window === "undefined" ||
      patients.value.length ||
      !location.protocol.startsWith("http") ||
      getAutoAdded()
    ) {
      return;
    }
    try {
      const config = await api("/api/config");
      if (!config.root || patients.value.length) return;
      addPatient("ESP32 Board", config.root);
      setAutoAdded();
    } catch {
      /* the feed still works with manual patients */
    }
  }

  onMounted(() => {
    savePatients(patients.value, selected.value);
    startClient();
    autoAdd();
    tickTimer = setInterval(() => {
      now.value = Date.now();
      for (const device of Object.values(devices)) {
        if (isAlive(device, now.value)) continue;
        if ((device.lastVitals || device.lastMotion) && device.state !== "offline") {
          const event = setState(device, "offline");
          if (event) addRow(device, event);
        }
      }
    }, 500);
    logTimer = setInterval(() => {
      const stamp = Date.now();
      for (const device of Object.values(devices)) {
        if (isAlive(device, stamp)) addRow(device, "");
      }
    }, 5000);
    saveTimer = setInterval(persist, 10000);
    window.addEventListener("pagehide", persist);
  });

  onBeforeUnmount(() => {
    if (tickTimer) clearInterval(tickTimer);
    if (logTimer) clearInterval(logTimer);
    if (saveTimer) clearInterval(saveTimer);
    if (failTimer) clearTimeout(failTimer);
    if (typeof window !== "undefined") window.removeEventListener("pagehide", persist);
    persist();
    if (client) {
      client.end(true);
      client = null;
    }
  });

  return {
    patients,
    selected,
    devices,
    log,
    connected,
    feedText,
    current,
    currentOnline,
    state,
    now,
    events,
    lastReading,
    addPatient,
    removePatient,
    selectPatient,
    clearLog,
    downloadCsv,
    publishRecalibrate,
  };
}
