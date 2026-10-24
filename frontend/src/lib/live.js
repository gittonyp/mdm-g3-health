import { STATES } from "./adaptive.js";

export const LIM = 120;
export const MAGLIM = 100;
export const LOGMAX = 20000;

export const STORE = "vitals.log.v2";
export const SELKEY = "vitals.patient";
export const PKEY = "vitals.patients.v1";
export const AUTOADD = "vitals.autoadded";

const KEYS = ["vitals", "motion", "event", "status", "anomaly"];

const storage = {
  get(key) {
    try {
      return localStorage.getItem(key);
    } catch {
      return null;
    }
  },
  set(key, value) {
    try {
      localStorage.setItem(key, value);
    } catch {
      /* storage disabled */
    }
  },
};

export function createDevice(patient) {
  return {
    id: patient.channel,
    name: patient.name,
    channel: patient.channel,
    buf: { hr: [], spo2: [], hrv: [], temp: [], mag: [] },
    last: { hr: null, spo2: null, hrv: null, temp: null },
    motion: {},
    state: "offline",
    lastVitals: 0,
    lastMotion: 0,
    lastAt: null,
  };
}

function pushBuf(buffer, value, limit) {
  if (typeof value !== "number" || !Number.isFinite(value)) return;
  buffer.push(value);
  if (buffer.length > limit) buffer.shift();
}

function setVal(device, key, value) {
  const number = value == null ? null : Number(value);
  device.last[key] = Number.isFinite(number) ? number : null;
  if (Number.isFinite(number)) pushBuf(device.buf[key], number, LIM);
}

export function setState(device, state) {
  if (!STATES[state] || state === device.state) return "";
  device.state = state;
  return state === "measuring" ? "" : STATES[state].title;
}

export function applyTopic(device, topicKey, text, now) {
  if (!KEYS.includes(topicKey)) return "";

  if (topicKey === "status") {
    if (text === "offline") {
      device.lastVitals = 0;
      device.lastMotion = 0;
      return setState(device, "offline");
    }
    return "";
  }

  let data;
  try {
    data = JSON.parse(text);
  } catch {
    return "";
  }

  if (topicKey === "vitals") {
    device.lastVitals = now;
    device.lastAt = now;
    if (data.hr !== undefined) setVal(device, "hr", data.hr);
    if (data.spo2 !== undefined) setVal(device, "spo2", data.spo2);
    if (data.hrv !== undefined) setVal(device, "hrv", data.hrv);
    const temp = data.temp == null ? null : Number(data.temp);
    device.last.temp = Number.isFinite(temp) ? temp : null;
    if (Number.isFinite(temp)) pushBuf(device.buf.temp, temp, LIM);
    return data.state ? setState(device, data.state) : "";
  }

  if (topicKey === "motion") {
    device.lastMotion = now;
    device.motion = {
      ax: data.ax,
      ay: data.ay,
      az: data.az,
      gx: data.gx,
      gy: data.gy,
      gz: data.gz,
      act: data.act,
    };
    const magnitude = Math.hypot(data.ax, data.ay, data.az);
    if (Number.isFinite(magnitude)) pushBuf(device.buf.mag, magnitude, MAGLIM);
    return data.act === "fall" ? setState(device, "fall") : "";
  }

  if (topicKey === "event" && data.type === "fall") {
    return setState(device, "fall");
  }

  if (topicKey === "anomaly" && data.level === "alert") {
    return setState(device, "alert");
  }

  return "";
}

export function isAlive(device, now) {
  return now - Math.max(device.lastVitals, device.lastMotion) < 4000;
}

export function shouldAutoAdd({ patients, protocol, autoadded, root }) {
  return (
    Array.isArray(patients) &&
    patients.length === 0 &&
    String(protocol || "").startsWith("http") &&
    !autoadded &&
    !!root
  );
}

export function loadPatients() {
  try {
    const parsed = JSON.parse(storage.get(PKEY) || "[]");
    if (!Array.isArray(parsed)) return [];
    return parsed.filter((p) => p && p.name && p.channel);
  } catch {
    return [];
  }
}

export function selectedChannel() {
  return storage.get(SELKEY) || null;
}

export function savePatients(patients, selected) {
  storage.set(PKEY, JSON.stringify(patients));
  storage.set(SELKEY, selected || "");
}

export function loadLog() {
  try {
    const parsed = JSON.parse(storage.get(STORE) || "[]");
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

export function saveLog(log) {
  storage.set(STORE, JSON.stringify(log));
}

export function setAutoAdded() {
  storage.set(AUTOADD, "1");
}

export function getAutoAdded() {
  return storage.get(AUTOADD);
}
