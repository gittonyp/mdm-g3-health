/* Remote Care Clinic - shared helpers (plain JS, no build step). */
(function () {
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
  const TIER_COLOR = {
    emergency: "#d6453d", actionable: "#e0743b", quality: "#c98a12",
    watch: "#5b6bc7", stable: "#0e8f83", clinical: "#16233f",
    caregiver: "#0e8f83", visit: "#5b6bc7", follow_up: "#c98a12",
  };

  let serverOffsetMs = 0; // server clock minus browser clock, from the HTTP Date header

  function esc(v) {
    return String(v == null ? "" : v).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  }

  function parseTs(v) {
    if (!v) return null;
    const t = Date.parse(String(v).endsWith("Z") || /[+-]\d\d:\d\d$/.test(String(v)) ? v : v + "Z");
    return Number.isFinite(t) ? t : null;
  }

  const ClinicUI = {
    esc,
    TIER_LABEL,
    QUALITY_LABEL,

    async api(path, options) {
      const opts = Object.assign({ headers: { "content-type": "application/json", "X-Demo-Actor": this.actor() } }, options || {});
      const r = await fetch(path, opts);
      const date = r.headers.get("Date");
      if (date) serverOffsetMs = Date.parse(date) - Date.now();
      let body = null;
      try { body = await r.json(); } catch (e) { /* non-JSON error body */ }
      if (!r.ok) throw new Error((body && body.detail) || "Request failed (" + r.status + ")");
      return body;
    },

    serverNow() { return Date.now() + serverOffsetMs; },
    ageSeconds(ts) { const t = parseTs(ts); return t == null ? null : Math.max(0, (this.serverNow() - t) / 1000); },
    fmtAge(s) {
      if (s == null) return "-";
      if (s < 5) return "just now";
      if (s < 60) return Math.round(s) + "s ago";
      if (s < 3600) return Math.round(s / 60) + "m ago";
      if (s < 86400) return Math.round(s / 3600) + "h ago";
      return Math.round(s / 86400) + "d ago";
    },
    fmtDateTime(v) { const t = parseTs(v); return t == null ? "-" : new Date(t).toLocaleString([], { hour12: false }); },
    fmtTime(v) { const t = parseTs(v); return t == null ? "" : new Date(t).toLocaleTimeString([], { hour12: false, hour: "2-digit", minute: "2-digit" }); },
    fmtValue(v, d) { return v == null ? "Unknown" : Number(v).toFixed(d || 0); },
    tierClass(t) { return "tier-" + (t || "unknown"); },
    tierLabel(t) { return TIER_LABEL[t] || TIER_LABEL.unknown; },
    qualityLabel(q) { return QUALITY_LABEL[q] || q || ""; },
    actor() { return localStorage.getItem("clinic.actor") || "doctor"; },
    setActor(a) { localStorage.setItem("clinic.actor", a); },

    // Same bands as the server rules (config.py) and the live dashboard.
    vitalState(kind, v) {
      if (v == null) return { text: "No reading", cls: "na" };
      if (kind === "hr") return v < 50 || v > 120 ? { text: "Critical", cls: "bad" } : v < 60 ? { text: "Low", cls: "warn" } : v > 100 ? { text: "High", cls: "warn" } : { text: "Normal", cls: "" };
      if (kind === "spo2") return v < 92 ? { text: "Critical", cls: "bad" } : v < 95 ? { text: "Low", cls: "warn" } : { text: "Normal", cls: "" };
      if (kind === "temp") return v < 35.5 || v >= 38 ? { text: v < 35.5 ? "Low" : "Fever", cls: "bad" } : v < 36.1 ? { text: "Low", cls: "warn" } : v > 37.2 ? { text: "Elevated", cls: "warn" } : { text: "Normal", cls: "" };
      return { text: "", cls: "" };
    },

    vitalTile(label, kind, value, unit, decimals) {
      const s = this.vitalState(kind, value);
      const shown = value == null ? "--" : Number(value).toFixed(decimals || 0);
      return '<div class="vital ' + s.cls + '"><div class="label">' + esc(label) + '</div><div class="value">' + shown +
        (value == null ? "" : "<small>" + esc(unit) + "</small>") + '</div><div class="state">' + esc(s.text) + "</div></div>";
    },

    renderNav(active) { window.SiteNav.render(active, { actor: true }); },

    poll(fn, ms) { fn(); return setInterval(fn, ms); },
    openDialog(id) { document.getElementById(id).showModal(); },

    toast(message, bad) {
      const t = document.createElement("div");
      t.className = "toast" + (bad ? " bad" : "");
      t.setAttribute("role", "status");
      t.textContent = message;
      document.body.appendChild(t);
      setTimeout(() => t.remove(), 3000);
    },

    // Line chart: series [{ts, <key>}], options {unit, baseline, markers:[{ts,type,label}], decimals}
    drawChart(svg, series, key, options) {
      options = options || {};
      const W = 500, H = 150, L = 38, R = 8, T = 10, B = 22;
      svg.setAttribute("viewBox", "0 0 " + W + " " + H);
      svg.setAttribute("preserveAspectRatio", "none");
      const pts = (series || []).map((x) => ({ t: parseTs(x.ts), v: x[key] == null ? null : Number(x[key]) })).filter((p) => p.t != null);
      const vals = pts.map((p) => p.v).filter((v) => v != null && Number.isFinite(v));
      if (pts.length < 2 || vals.length < 2) {
        svg.innerHTML = '<text x="' + W / 2 + '" y="' + H / 2 + '" text-anchor="middle" font-size="13" fill="#8a94a8">Not enough data yet</text>';
        return;
      }
      let min = Math.min.apply(null, vals), max = Math.max.apply(null, vals);
      if (options.baseline != null) { min = Math.min(min, options.baseline); max = Math.max(max, options.baseline); }
      const pad = (max - min) * 0.15 || 1;
      min -= pad; max += pad;
      const t0 = pts[0].t, t1 = pts[pts.length - 1].t;
      const x = (t) => L + ((t - t0) / (t1 - t0 || 1)) * (W - L - R);
      const y = (v) => T + (1 - (v - min) / (max - min)) * (H - T - B);
      // Tiny ranges need extra decimals or the three axis labels all read the same.
      const d = (options.decimals || 0) + ((max - min) < 4 ? 1 : 0) + ((max - min) < 0.4 ? 1 : 0);
      let out = "";
      [0, 0.5, 1].forEach((f) => {
        const v = min + (max - min) * f, yy = y(v);
        out += '<line x1="' + L + '" x2="' + (W - R) + '" y1="' + yy + '" y2="' + yy + '" stroke="#e1e6ef" stroke-width="1"/>' +
          '<text x="' + (L - 5) + '" y="' + (yy + 4) + '" text-anchor="end" font-size="10" fill="#7b869c">' + v.toFixed(d) + "</text>";
      });
      if (options.baseline != null) {
        out += '<line x1="' + L + '" x2="' + (W - R) + '" y1="' + y(options.baseline) + '" y2="' + y(options.baseline) + '" stroke="#0e8f83" stroke-width="1.3" stroke-dasharray="5 4"/>';
      }
      (options.markers || []).forEach((m) => {
        const t = parseTs(m.ts);
        if (t == null || t < t0 || t > t1 || !TIER_COLOR[m.type]) return;
        out += '<line x1="' + x(t) + '" x2="' + x(t) + '" y1="' + T + '" y2="' + (H - B) + '" stroke="' + TIER_COLOR[m.type] + '" stroke-width="1.5" opacity=".55"><title>' + esc(m.label || m.type) + "</title></line>";
      });
      let seg = [];
      const flush = () => { if (seg.length > 1) out += '<polyline points="' + seg.join(" ") + '" fill="none" stroke="currentColor" stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/>'; seg = []; };
      pts.forEach((p) => { if (p.v == null) flush(); else seg.push(x(p.t).toFixed(1) + "," + y(p.v).toFixed(1)); });
      flush();
      out += '<text x="' + L + '" y="' + (H - 6) + '" font-size="10" fill="#7b869c">' + this.fmtTime(new Date(t0).toISOString()) + "</text>" +
        '<text x="' + (W - R) + '" y="' + (H - 6) + '" text-anchor="end" font-size="10" fill="#7b869c">' + this.fmtTime(new Date(t1).toISOString()) + "</text>";
      svg.innerHTML = out;
    },
  };

  window.ClinicUI = ClinicUI;
})();
