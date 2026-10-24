const TIER_ORDER = ["emergency", "actionable", "quality", "watch"];

export function worstTier(openAlerts, latestVital) {
  const sorted = (openAlerts || []).slice().sort(
    (a, b) => TIER_ORDER.indexOf(a.tier) - TIER_ORDER.indexOf(b.tier)
  );
  if (sorted.length) return sorted[0].tier;
  return latestVital ? "stable" : "unknown";
}

export function baselineText(baseline) {
  if (!baseline) return "Baseline: not started";
  if (baseline.ready) return "Baseline: calibrated" + (baseline.stale ? " (needs refresh)" : "");
  const collected = Math.min(baseline.windows_collected, baseline.windows_required);
  return "Baseline: learning (" + collected + "/" + baseline.windows_required + " windows)";
}

export function evidenceText(alert) {
  const ev = alert.evidence || {};
  const parts = [];
  const round = (v) => (typeof v === "number" ? Math.round(v * 10) / 10 : v);
  if (ev.value != null) parts.push("value " + round(ev.value));
  if (ev.threshold != null) parts.push("threshold " + round(ev.threshold));
  if (ev.baseline != null) parts.push("baseline " + round(ev.baseline));
  if (ev.motion_g != null) parts.push("motion " + Number(ev.motion_g).toFixed(2) + " g");
  if (alert.score != null) parts.push("score " + alert.score);
  return parts.join(" · ");
}
