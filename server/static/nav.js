/* Shared top navigation for every page (Clinic, Live, History, Caregiver).
   Self-contained: injects its own CSS, so pages only need <nav id="nav"></nav> as the first
   element inside their wrapper and one call: SiteNav.render('<page key>'). */
(function () {
  const CSS = `
.sn{display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin:0 0 18px;font-family:inherit}
.sn *{box-sizing:border-box}
.sn-brand{display:flex;align-items:center;gap:11px;margin-right:10px;text-decoration:none;color:var(--ink,#16233f)}
.sn-logo{width:38px;height:38px;border-radius:11px;background:var(--nav-active,#16233f);display:grid;place-items:center;flex:none}
.sn-brand b{font-size:16px;font-weight:650}
.sn-link{background:var(--panel,#fff);border:1px solid var(--line,#d7dde8);border-radius:999px;padding:7px 14px;font-size:13px;color:var(--ink,#16233f);text-decoration:none;line-height:1.3}
.sn-link:hover{filter:brightness(.97);text-decoration:none}
.sn-link.active{background:var(--nav-active,#16233f);color:var(--nav-active-ink,#fff);border-color:var(--nav-active,#16233f)}
.sn-spacer{flex:1}
.sn label{display:flex;align-items:center;gap:6px;margin:0;font-size:12px;font-weight:650;color:var(--muted,#5d6b85);white-space:nowrap}
.sn select{font:inherit;font-size:13px;font-weight:600;color:var(--ink,#16233f);background:var(--panel,#fff);border:1px solid var(--line,#d7dde8);border-radius:8px;padding:6px 10px;min-width:0;width:auto;box-shadow:none}
.sn-pill{display:inline-flex;align-items:center;gap:7px;background:var(--panel,#fff);border:1px solid var(--line,#d7dde8);border-radius:999px;padding:6px 12px;font-size:13px;color:var(--ink,#16233f);text-decoration:none;line-height:1.3}
.sn-dot{width:9px;height:9px;border-radius:50%;background:#b5bdcc;flex:none}
.sn-dot.on{background:var(--ok,#0e8f83)}
.sn-dot.bad{background:var(--bad,#d6453d)}
.sn a:focus-visible,.sn select:focus-visible{outline:3px solid #7aa7ff;outline-offset:2px}
@media (max-width:760px){.sn-spacer{display:none}}
@media print{.sn{display:none}}
`;
  const LINKS = [
    ["/clinic", "clinic", "Clinic"],
    ["/live", "live", "Live"],
    ["/history", "history", "History"],
    ["/care", "care", "Caregiver"],
  ];
  let timer = null;

  function injectCss() {
    if (document.getElementById("sn-css")) return;
    const s = document.createElement("style");
    s.id = "sn-css";
    s.textContent = CSS;
    document.head.appendChild(s);
  }

  async function refreshHealth() {
    const dot = document.getElementById("sn-dot"), text = document.getElementById("sn-text");
    if (!dot) return;
    try {
      const h = await fetch("/api/health", { cache: "no-store" }).then((r) => r.json());
      dot.className = "sn-dot " + (h.mqtt_connected ? "on" : "bad");
      text.textContent = h.mqtt_connected ? "MQTT connected" : "MQTT offline";
    } catch (e) {
      dot.className = "sn-dot bad";
      text.textContent = "Server unreachable";
    }
  }

  window.SiteNav = {
    // opts.actor: show the "Viewing as" switch (only meaningful on the clinic pages)
    render(active, opts) {
      opts = opts || {};
      injectCss();
      let el = document.getElementById("nav");
      if (!el) {
        el = document.createElement("nav");
        el.id = "nav";
        (document.querySelector(".wrap") || document.body).prepend(el);
      }
      el.className = "sn";
      el.setAttribute("aria-label", "Main");
      const link = (l) => '<a class="sn-link' + (active === l[1] ? " active" : "") + '" href="' + l[0] + '"' + (active === l[1] ? ' aria-current="page"' : "") + ">" + l[2] + "</a>";
      el.innerHTML =
        '<a class="sn-brand" href="/clinic"><span class="sn-logo" aria-hidden="true"><svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="#fff" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 12h4l2-5 4 10 2-5h6"/></svg></span><b>Remote Care</b></a>' +
        LINKS.map(link).join("") +
        '<span class="sn-spacer"></span>' +
        (opts.actor ? '<label>Viewing as <select id="actor"><option value="doctor">Doctor</option><option value="caregiver">Caregiver</option></select></label>' : "") +
        '<a class="sn-pill" href="/api/health" title="Server and MQTT status"><span class="sn-dot" id="sn-dot"></span><span id="sn-text">Checking...</span></a>';
      if (opts.actor) {
        const s = document.getElementById("actor");
        s.value = localStorage.getItem("clinic.actor") || "doctor";
        s.onchange = () => localStorage.setItem("clinic.actor", s.value);
      }
      refreshHealth();
      if (timer) clearInterval(timer);
      timer = setInterval(refreshHealth, 15000);
    },
  };
})();
