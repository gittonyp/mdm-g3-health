const TIER_LABEL = {
  emergency: "Emergency",
  actionable: "Needs action",
  quality: "Data problem",
  watch: "Watch",
  stable: "Stable",
  unknown: "No data",
};

const QUALITY_LABEL = {
  good: "Live data",
  stale: "No recent readings",
  offline: "Device offline",
  no_finger: "No finger on sensor",
  motion: "Motion - readings unreliable",
  missing: "No device linked",
};

let serverOffsetMs = 0;

export function esc(value) {
  return String(value == null ? "" : value).replace(/[&<>"']/g, (c) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  })[c]);
}

export function parseTs(value) {
  if (!value) return null;
  const text = String(value);
  const t = Date.parse(
    text.endsWith("Z") || /[+-]\d\d:\d\d$/.test(text) ? text : text + "Z"
  );
  return Number.isFinite(t) ? t : null;
}

export function getActor() {
  try {
    return localStorage.getItem("clinic.actor") || "doctor";
  } catch {
    return "doctor";
  }
}

export function setActor(name) {
  try {
    localStorage.setItem("clinic.actor", name);
  } catch {
    /* storage disabled */
  }
}

export async function api(path, options) {
  const opts = {
    ...(options || {}),
    headers: {
      "content-type": "application/json",
      "X-Demo-Actor": getActor(),
      ...((options || {}).headers || {}),
    },
  };
  const response = await fetch(path, opts);
  const date = response.headers.get("Date");
  if (date) serverOffsetMs = Date.parse(date) - Date.now();
  let body = null;
  try {
    body = await response.json();
  } catch {
    /* non-JSON error body */
  }
  if (!response.ok) {
    throw new Error((body && body.detail) || "Request failed (" + response.status + ")");
  }
  return body;
}

export function serverNow() {
  return Date.now() + serverOffsetMs;
}

export function ageSeconds(ts) {
  const t = parseTs(ts);
  return t == null ? null : Math.max(0, (serverNow() - t) / 1000);
}

export function fmtAge(seconds) {
  if (seconds == null) return "—";
  if (seconds < 5) return "just now";
  if (seconds < 60) return Math.round(seconds) + "s ago";
  if (seconds < 3600) return Math.round(seconds / 60) + "m ago";
  if (seconds < 86400) return Math.round(seconds / 3600) + "h ago";
  return Math.round(seconds / 86400) + "d ago";
}

export function fmtDateTime(value) {
  const t = parseTs(value);
  return t == null ? "—" : new Date(t).toLocaleString([], { hour12: false });
}

export function fmtTime(value) {
  const t = parseTs(value);
  return t == null ? "" : new Date(t).toLocaleTimeString([], { hour12: false, hour: "2-digit", minute: "2-digit" });
}

export function fmtValue(value, digits) {
  if (value == null || Number.isNaN(Number(value))) return "—";
  return Number(value).toFixed(digits || 0);
}

export function tierClass(tier) {
  return "tier-" + (tier || "unknown");
}

export function tierLabel(tier) {
  return TIER_LABEL[tier] || TIER_LABEL.unknown;
}

export function qualityLabel(quality) {
  return QUALITY_LABEL[quality] || quality || "";
}

export function vitalState(kind, value) {
  if (value == null) return { text: "No reading", cls: "na" };
  if (kind === "hr") {
    return value < 50 || value > 120
      ? { text: "Critical", cls: "bad" }
      : value < 60
        ? { text: "Low", cls: "warn" }
        : value > 100
          ? { text: "High", cls: "warn" }
          : { text: "Normal", cls: "" };
  }
  if (kind === "spo2") {
    return value < 92
      ? { text: "Critical", cls: "bad" }
      : value < 95
        ? { text: "Low", cls: "warn" }
        : { text: "Normal", cls: "" };
  }
  if (kind === "temp") {
    return value < 35.5 || value >= 38
      ? { text: value < 35.5 ? "Low" : "Fever", cls: "bad" }
      : value < 36.1
        ? { text: "Low", cls: "warn" }
        : value > 37.2
          ? { text: "Elevated", cls: "warn" }
          : { text: "Normal", cls: "" };
  }
  return { text: "", cls: "" };
}

export function toast(message, bad) {
  const node = document.createElement("div");
  node.className = "toast" + (bad ? " bad" : "");
  node.setAttribute("role", "status");
  node.textContent = message;
  document.body.appendChild(node);
  setTimeout(() => node.remove(), 3000);
}
