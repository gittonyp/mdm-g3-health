import { esc, fmtTime, parseTs } from "../api.js";

const TIER_COLOR = {
  emergency: "#d6453d",
  actionable: "#e0743b",
  quality: "#c98a12",
  watch: "#5b6bc7",
  stable: "#0e8f83",
  clinical: "#16233f",
  caregiver: "#0e8f83",
  visit: "#5b6bc7",
  follow_up: "#c98a12",
};

export function drawLineChart(svg, series, key, options) {
  options = options || {};
  const W = 500;
  const H = 150;
  const L = 38;
  const R = 8;
  const T = 10;
  const B = 22;
  svg.setAttribute("viewBox", "0 0 " + W + " " + H);
  svg.setAttribute("preserveAspectRatio", "none");

  const points = (series || [])
    .map((row) => ({ t: parseTs(row.ts), v: row[key] == null ? null : Number(row[key]) }))
    .filter((p) => p.t != null);

  const values = points.map((p) => p.v).filter((v) => v != null && Number.isFinite(v));
  if (points.length < 2 || values.length < 2) {
    svg.innerHTML =
      '<text x="' + W / 2 + '" y="' + H / 2 + '" text-anchor="middle" font-size="13" fill="#8a94a8">Not enough data yet</text>';
    return;
  }

  let min = Math.min(...values);
  let max = Math.max(...values);
  if (options.baseline != null) {
    min = Math.min(min, options.baseline);
    max = Math.max(max, options.baseline);
  }
  const pad = (max - min) * 0.15 || 1;
  min -= pad;
  max += pad;

  const t0 = points[0].t;
  const t1 = points[points.length - 1].t;
  const x = (t) => L + ((t - t0) / (t1 - t0 || 1)) * (W - L - R);
  const y = (v) => T + (1 - (v - min) / (max - min)) * (H - T - B);

  const d =
    (options.decimals || 0) +
    (max - min < 4 ? 1 : 0) +
    (max - min < 0.4 ? 1 : 0);

  let out = "";
  [0, 0.5, 1].forEach((f) => {
    const v = min + (max - min) * f;
    const yy = y(v);
    out +=
      '<line x1="' + L + '" x2="' + (W - R) + '" y1="' + yy + '" y2="' + yy + '" stroke="#e1e6ef" stroke-width="1"/>' +
      '<text x="' + (L - 5) + '" y="' + (yy + 4) + '" text-anchor="end" font-size="10" fill="#7b869c">' + v.toFixed(d) + "</text>";
  });

  if (options.baseline != null) {
    out +=
      '<line x1="' + L + '" x2="' + (W - R) + '" y1="' + y(options.baseline) + '" y2="' + y(options.baseline) +
      '" stroke="#0e8f83" stroke-width="1.3" stroke-dasharray="5 4"/>';
  }

  (options.markers || []).forEach((marker) => {
    const t = parseTs(marker.ts);
    if (t == null || t < t0 || t > t1 || !TIER_COLOR[marker.type]) return;
    out +=
      '<line x1="' + x(t) + '" x2="' + x(t) + '" y1="' + T + '" y2="' + (H - B) + '" stroke="' + TIER_COLOR[marker.type] +
      '" stroke-width="1.5" opacity=".55"><title>' + esc(marker.label || marker.type) + "</title></line>";
  });

  let segment = [];
  const flush = () => {
    if (segment.length > 1) {
      out += '<polyline points="' + segment.join(" ") + '" fill="none" stroke="currentColor" stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/>';
    }
    segment = [];
  };
  points.forEach((p) => {
    if (p.v == null) flush();
    else segment.push(x(p.t).toFixed(1) + "," + y(p.v).toFixed(1));
  });
  flush();

  out +=
    '<text x="' + L + '" y="' + (H - 6) + '" font-size="10" fill="#7b869c">' + fmtTime(new Date(t0).toISOString()) + "</text>" +
    '<text x="' + (W - R) + '" y="' + (H - 6) + '" text-anchor="end" font-size="10" fill="#7b869c">' + fmtTime(new Date(t1).toISOString()) + "</text>";
  svg.innerHTML = out;
}
