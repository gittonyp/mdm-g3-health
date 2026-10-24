# Vue SPA + Adaptive Vital Display — Design

Date: 2026-10-24
Status: Draft for review

## 1. Goal

1. Replace the fixed population ranges shown on `/live` ("Normal 60–100 bpm",
   "Normal 95–100 %", "Typical 20–100 ms", "Normal 36.1–37.2 °C") with
   adaptive/personal-baseline wording that matches the firmware.
2. Convert the five separate pages into one Vue 3 single-page application:
   `/clinic`, `/clinic/patient/:id`, `/care`, `/history`, `/live`.
3. Keep the existing FastAPI backend and JSON API unchanged in behaviour.
4. Keep existing URLs working (bookmarks and deep links).

## 2. Success criteria

- No fixed clinical range is presented as the patient's normal any more.
- Navigating between the five pages does not reload the document.
- All existing features remain: clinic filters/add patient, patient detail,
  care tasks, history, live MQTT dashboard (charts, events, CSV,
  recalibrate, patient picker).
- `python -m unittest discover -s tests -v` still passes.
- Production bundle is minified and route-split.

## 3. Non-goals

- No change to alert thresholds or anomaly logic in `server/alerts.py`.
- No fix for unrelated issues found during exploration (for example the
  clinic "No device is linked" wording).
- No authentication, no new database schema, no broker change.
- No visual redesign beyond what the SPA shell requires.

## 4. Current state

- FastAPI serves five static HTML documents via `FileResponse`
  (`server/main.py:42-69`).
- Shared assets: `server/static/nav.js`, `server/static/clinic.js`,
  `server/static/clinic.css`.
- `/live` is `health_dashboard.html`, a standalone document with its own
  CSS, MQTT client, charts, and `localStorage` patient list.
- `health_dashboard.html:186-193` defines fixed ranges and states; the
  firmware now also publishes `learning`, `watch`, `emergency`, `stress`.
- `health_dashboard.html:261-271` fabricates a 37–39 °C temperature when
  the device sends `temp: null`.
- Deployment is Python-only (`Dockerfile`, `render.yaml`).

## 5. Technology decision

- Vue 3 + Vite + vue-router, in a new `frontend/` directory.
- No state library; small composables for API polling and MQTT.
- `mqtt` (mqtt.js) as the only runtime dependency for live data.
- Vite base path `/static/app/`; FastAPI serves the built files and the
  SPA shell.

## 6. Frontend structure

```text
frontend/
  package.json
  package-lock.json
  vite.config.js
  index.html
  src/
    main.js
    App.vue
    router.js
    api.js              fetch wrapper, polling helper, abort handling
    mqtt.js             connect/disconnect + message dispatch composable
    adaptive.js         label/state helpers for adaptive display
    styles.css          merged clinic.css + page styles
    views/
      ClinicView.vue
      PatientView.vue
      CareView.vue
      HistoryView.vue
      LiveView.vue
    components/
      NavBar.vue        shared nav, Viewing-as switch, MQTT status pill
      PatientCard.vue
      VitalTile.vue
      AlertRow.vue
      TrendChart.vue
```

## 7. Routing

| Path | View | Notes |
|---|---|---|
| `/` | redirect | redirects to `/clinic` |
| `/clinic` | ClinicView | worklist, filters, add-patient dialog |
| `/clinic/patient/:id` | PatientView | detail, alerts, trends, notes |
| `/care` | CareView | `?patient=` query preserved |
| `/history` | HistoryView | persisted vitals/events/anomalies |
| `/live` | LiveView | MQTT dashboard, patient list in `localStorage` |

- vue-router `createWebHistory`.
- Unknown paths render a simple Not Found view.

## 8. Backend changes

- Keep `/api/*`, `/docs`, `/openapi.json`, and the `/static` mount.
- Add `app.mount("/static/app", StaticFiles(directory=frontend/dist))`
  when the build exists.
- Add one catch-all GET route for the five page paths (and `/`) that
  returns the SPA shell (`frontend/dist/index.html` when built, otherwise
  a minimal placeholder). `/api/*` is never swallowed.
- Keep the existing `/api/health`, `/api/config` and other endpoints
  unchanged.
- Remove the old page `FileResponse` routes after parity is verified;
  old static files may stay in the repository for one release as a
  rollback path.

## 9. Views

### ClinicView
- Worklist from `/api/clinic/worklist`, 10 s polling.
- Program and status filters.
- Add-patient dialog (`POST /api/patients`).
- Preserve the current card layout via `PatientCard`.

### PatientView
- Load `/api/patients/:id`, `/trends`, `/alerts`, `/notes`, `/audit`.
- Keep acknowledge/resolve/caregiver-response actions.
- Trend chart from the existing data shape.

### CareView
- `?patient=` driven tasks from `/api/care/tasks`.
- Preserve the current caregiver action flow.

### HistoryView
- `/api/stats`, `/api/devices`, `/api/anomalies`, `/api/vitals`.
- Preserve tables, filters, and export link.

### LiveView
- Patient picker persisted in `localStorage`; first visit auto-adds the
  default channel from `/api/config`.
- MQTT connect on mount, disconnect on unmount.
- Charts, event log, CSV download, recalibrate command.
- Recognise all firmware states: `learning`, `watch`, `alert`,
  `emergency`, `stress`, `fall`, `measuring`, `no_finger`, `offline`.
- No fabricated temperature.

## 10. Adaptive vital display

Replace the fixed `range` strings in the old `VITALS` table:

| Vital | New helper text |
|---|---|
| Heart rate | `Adaptive · personal baseline` |
| SpO2 | `Adaptive · personal baseline` |
| HRV | `Adaptive · rest-only` |
| Temperature | `Estimated body temperature` |

- Per-vital chips no longer use population thresholds. They reflect the
  device-reported state (`Learning`, `Normal`, `Watch`, `Alert`,
  `Emergency`, `Stress`, `Offline`).
- When `temp` is `null`, display `—`; remove `tempTick`.
- If the selected device is bound to a patient and a baseline is exposed
  by the API, show the learned value next to the label; otherwise show
  `learning`.
- The status banner and navigation pill use the same state mapping.

## 11. Optimisation

- Route-level `import()` so each view ships in its own chunk.
- Shared vendor chunk for Vue/vue-router/mqtt.
- Minified production build (Vite default).
- Polling pauses when `document.hidden`.
- Abort in-flight fetches on navigation.
- MQTT connection only exists while `LiveView` is mounted.
- Cache the last worklist/patient response per session to make
  back-navigation instant; refresh in the background.
- No full-document reload on internal navigation.

## 12. Deployment

Multi-stage `Dockerfile`:

```text
FROM node:22-slim AS web
  npm ci
  npm run build

FROM python:3.12-slim
  pip install -r requirements.txt
  copy server/
  copy --from=web /web/dist frontend/dist
```

- `render.yaml` remains unchanged.
- Local development: `npm run dev` (Vite) with `/api` proxied to
  `uvicorn server.main:app --port 8000`.
- Production check: `curl /clinic` returns the shell, `/static/app/assets/*`
  returns hashed bundles.

## 13. Testing and verification

- Existing Python tests remain green; `/` and `/clinic` still return 200.
- Add a route test asserting `/clinic`, `/clinic/patient/PT-0001`, `/care`,
  `/history`, `/live` return 200 and the SPA root element.
- Frontend build must succeed (`npm run build`).
- Playwright smoke pass over all five routes with the server and simulator:
  navigation without reloads, no console errors, live data updates,
  adaptive labels visible, `temp: null` shows `—`.
- Existing Rust/JS-free backend behaviour is unchanged.

## 14. Migration and rollback

1. Build the Vue app alongside the existing pages.
2. Switch the page routes to the SPA.
3. Run the test suite and Playwright smoke checks.
4. Keep the old static pages in the repository for one release; deleting
   them is a separate follow-up. Rollback is reverting the route change.

## 15. Risks

- **Live MQTT port is the largest piece.** Mitigation: port the existing
  behaviour one feature at a time and verify with `simulator.py`.
- **Build tooling added to Docker.** Mitigation: multi-stage build; the
  runtime image stays Python-only.
- **Routing collisions with the API.** Mitigation: catch-all excludes
  `/api`, `/docs`, `/openapi.json`, `/static`, and `/assets`.
- **Tests without Node.** Mitigation: the catch-all falls back to a minimal
  shell when `frontend/dist` is absent, so Python tests do not require a
  frontend build.
