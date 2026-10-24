export const VITALS = [
  { k: "hr", name: "Heart rate", unit: "bpm", d: 0, hint: "Adaptive · personal baseline" },
  { k: "spo2", name: "Oxygen (SpO₂)", unit: "%", d: 0, hint: "Adaptive · personal baseline" },
  { k: "hrv", name: "HRV (RMSSD)", unit: "ms", d: 0, hint: "Adaptive · rest-only" },
  { k: "temp", name: "Temperature", unit: "°C", d: 1, hint: "Estimated body temperature" },
];

export const STATES = {
  normal: {
    title: "Vitals within your baseline",
    hint: "Adaptive range learned from this patient.",
    cls: "ok",
  },
  measuring: {
    title: "Acquiring signal",
    hint: "Keep the finger still on the sensor.",
    cls: "warn",
  },
  no_finger: {
    title: "Sensor not in contact",
    hint: "Place a finger on the pulse oximeter.",
    cls: "warn",
  },
  learning: {
    title: "Learning your baseline",
    hint: "Keep still while the monitor adapts.",
    cls: "warn",
  },
  watch: {
    title: "Early warning",
    hint: "Vitals are drifting from the personal baseline.",
    cls: "warn",
  },
  alert: {
    title: "Abnormal vitals",
    hint: "Sustained deviation from the personal baseline.",
    cls: "bad",
  },
  emergency: {
    title: "Emergency",
    hint: "Vitals are far outside safe limits. Check now.",
    cls: "bad",
  },
  stress: {
    title: "Low HRV",
    hint: "Stress or fatigue detected while resting.",
    cls: "warn",
  },
  fall: {
    title: "Possible fall detected",
    hint: "Check on the patient now.",
    cls: "bad",
  },
  offline: {
    title: "No signal from device",
    hint: "Waiting for the monitor to reconnect.",
    cls: "warn",
  },
};

const CHIP = {
  normal: { text: "Normal", cls: "ok" },
  measuring: { text: "Acquiring", cls: "warn" },
  no_finger: { text: "No finger", cls: "warn" },
  learning: { text: "Learning", cls: "" },
  watch: { text: "Watch", cls: "warn" },
  alert: { text: "Alert", cls: "bad" },
  emergency: { text: "Emergency", cls: "bad" },
  stress: { text: "Stress", cls: "warn" },
  fall: { text: "Fall", cls: "bad" },
  offline: { text: "Offline", cls: "" },
};

const DEFAULT_RANGE = {
  hr: [50, 120],
  spo2: [90, 100],
  hrv: [0, 100],
  temp: [35, 40],
};

export function stateInfo(state) {
  return STATES[state] || STATES.offline;
}

export function vitalChip(value, state) {
  if (value == null) return { text: "—", cls: "" };
  return CHIP[state] || { text: "—", cls: "" };
}

export function sparkRange(metricKey, values) {
  const clean = (values || []).filter((v) => v != null && Number.isFinite(Number(v))).map(Number);
  if (clean.length < 2) return DEFAULT_RANGE[metricKey] || [0, 1];
  let min = Math.min(...clean);
  let max = Math.max(...clean);
  if (min === max) {
    min -= 1;
    max += 1;
  }
  const pad = (max - min) * 0.2;
  return [min - pad, max + pad];
}
