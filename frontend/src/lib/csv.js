const HEAD = [
  "time",
  "patient",
  "mqtt_channel",
  "heart_rate_bpm",
  "spo2_percent",
  "hrv_ms",
  "temperature_c",
  "activity",
  "status",
  "event",
];

function cell(value) {
  const text = value == null ? "" : String(value);
  return /[",\n\r]/.test(text) ? '"' + text.replace(/"/g, '""') + '"' : text;
}

export function toCsv(log) {
  const lines = [HEAD.join(",")];
  for (const row of log || []) {
    const [ts, ...rest] = row;
    lines.push([new Date(ts).toISOString(), ...rest].map(cell).join(","));
  }
  return lines.join("\r\n");
}
