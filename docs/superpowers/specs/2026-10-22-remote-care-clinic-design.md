# Remote Care Clinic - Design Specification

- Date: 2026-10-22
- Status: Design approved; implementation plan written
- Scope: One implementation plan
- Related: `docs/architecture.md`, `docs/edge-ai.md`, `docs/roadmap.md`
- Plan: `docs/superpowers/plans/2026-10-22-remote-care-clinic.md`

## 1. Context

The current product is a technically working device monitor: it shows one patient's live vitals, motion, and events. It is not a clinical tool. A doctor cannot use it to decide who needs attention, why an alert fired, whether the data is trustworthy, or who acted on an alert.

The target users are:

- **Doctor**: oversees a mixed panel of telehealth and home hospice/elderly patients.
- **Caregiver**: is with the patient at home and can check the sensor or the patient.

The product must support two care programs in one worklist:

- **Telehealth**: episodic review before scheduled visits; detect drift over days/weeks.
- **Hospice/elderly care**: continuous safety net; caregiver-first response; goals of care matter.

The existing live dashboard remains available as a drill-down. The current ESP32, MQTT, FastAPI, SQLite, and model stack is reused.

## 2. Clinical jobs to be done

1. Which of my patients cannot wait until tomorrow?
2. What changed since I last looked?
3. Why did this fire, and is the data trustworthy?
4. What should happen next, and who owns it?
5. Did the caregiver act?

Success means a doctor can answer the first question in under 60 seconds and the remaining four without leaving the patient view.

## 3. Goals and non-goals

### Goals

- Risk-ranked triage worklist as the clinical home.
- Stable patient identity separated from device identity.
- Minimal clinical profile sufficient to interpret the numbers.
- Tiered alerts that separate data-quality problems from clinical problems.
- Explicit alert lifecycle with acknowledgement, overdue visibility, caregiver response, and audit.
- Visible trust signals: signal quality, freshness, baseline state, and plain-language evidence.
- One worklist with program-specific policy for telehealth and hospice.
- Preserve the current live monitor at `/live`.

### Non-goals

- Authentication, authorization, roles, or shift scheduling.
- On-call paging or external notifications.
- EHR/FHIR integration, medication ordering, or clinical documentation export.
- New model training or changes to the ML feature set.
- Native mobile apps.
- Real patient data or regulated clinical use.
- Automated end-to-end test suite (headed Playwright spot checks only, per project decision).

## 4. Design principles

1. **Triage, not telemetry.** The home page ranks work; it does not stream waveforms.
2. **Unknown is a state.** Missing or stale data is never displayed as normal or as the last value.
3. **An alert is a protocol.** Every alert has an owner, an age, evidence, a next action, and a resolution.
4. **No silent expiry.** Clinical alerts are resolved by a human, with a reason. Only data-quality tasks may auto-resolve.
5. **No invented scores.** Do not display a synthetic "AI risk" or "confidence" number. Show the worst open tier, signal quality, baseline state, and model/rule evidence.
6. **One product, two programs.** Program policy changes ordering, defaults, and messaging, not the data model.
7. **Reuse the stack.** No new services, no build step, no framework migration.

## 5. Information architecture

| Route | Purpose |
|---|---|
| `/` | Redirect to `/clinic` |
| `/clinic` | Doctor triage worklist (new home) |
| `/clinic/patient/{patient_id}` | Patient detail, trends, alerts, notes |
| `/care?patient={patient_id}` | Caregiver task view |
| `/live?patient={patient_id}` | Existing live dashboard |
| `/history` | Existing raw history page |
| `/docs` | Existing API docs |

Navigation is available on every clinical page: `Clinic`, `Live`, `History`, actor switch (Doctor/Caregiver), and a system-health indicator.

## 6. Data model

Existing tables (`devices`, `messages`, `vitals`, `events`, `anomalies`) remain unchanged. The new tables are created at startup with `CREATE TABLE IF NOT EXISTS`.

### `patients`

| Column | Type | Notes |
|---|---|---|
| `id` | TEXT PK | Server-generated `PT-0001` style |
| `display_name` | TEXT NOT NULL | |
| `dob` | TEXT NOT NULL | ISO date; age derived at read time |
| `sex` | TEXT | `F`, `M`, `O`, `U` |
| `primary_condition` | TEXT | Free text |
| `reason_for_monitoring` | TEXT | Free text |
| `medications` | TEXT | Free text, key meds only |
| `mobility` | TEXT | Free text |
| `goals_of_care` | TEXT | Free text; drives comfort messaging |
| `caregiver_name` | TEXT | Person at home, if any |
| `caregiver_contact` | TEXT | Free text; demo only |
| `caregiver_available` | INTEGER NOT NULL DEFAULT 1 | 0 = no caregiver; doctor owns all tasks |
| `program` | TEXT NOT NULL | `telehealth` or `hospice` |
| `comfort_mode` | INTEGER NOT NULL DEFAULT 0 | Hospice-only; suppress watch tier and adjust messaging |
| `next_review_at` | TEXT | Set by "schedule follow-up" |
| `archived` | INTEGER NOT NULL DEFAULT 0 | |
| `created_at`, `updated_at` | TEXT NOT NULL | UTC ISO |

### `patient_devices`

| Column | Type | Notes |
|---|---|---|
| `id` | INTEGER PK | |
| `patient_id` | TEXT NOT NULL | FK to `patients` |
| `device_id` | TEXT NOT NULL | MQTT device ID |
| `channel` | TEXT NOT NULL | Topic root, e.g. `mdm-g3-pcce/health/sim01` |
| `bound_at` | TEXT NOT NULL | |
| `unbound_at` | TEXT | NULL while active |

Constraints: one active binding per `device_id` and per `patient_id`; partial unique indexes on active rows. A patient has one active wearable; rebinding is allowed only after unbinding.

### `alerts`

| Column | Type | Notes |
|---|---|---|
| `id` | INTEGER PK | |
| `patient_id` | TEXT NOT NULL | |
| `device_id` | TEXT | |
| `tier` | TEXT NOT NULL | `quality`, `watch`, `actionable`, `emergency` |
| `kind` | TEXT NOT NULL | `hr`, `spo2`, `temp`, `motion_artifact`, `fall`, `model`, `offline`, `stale`, `no_finger` |
| `source` | TEXT NOT NULL | `rule`, `model`, `event`, `quality` |
| `status` | TEXT NOT NULL | `open`, `acknowledged`, `resolved` |
| `owner` | TEXT NOT NULL | `doctor` or `caregiver` |
| `caregiver_response` | TEXT | `pending`, `done`, `cannot`, `contact_doctor` (caregiver-owned alerts only) |
| `score` | REAL | Rule score or model probability when applicable |
| `reason` | TEXT NOT NULL | Short clinical sentence |
| `evidence_json` | TEXT NOT NULL | Structured evidence |
| `dedupe_key` | TEXT NOT NULL | Patient + kind + tier |
| `created_at`, `updated_at`, `last_seen_at` | TEXT NOT NULL | UTC ISO |
| `acknowledged_at`, `acknowledged_by` | TEXT | |
| `resolved_at`, `resolved_by`, `resolution_note` | TEXT | Resolution note required |
| `due_at` | TEXT | Ack/review deadline |

### `alert_events`

Immutable audit of alert transitions:

| Column | Type | Notes |
|---|---|---|
| `id` | INTEGER PK | |
| `alert_id` | INTEGER NOT NULL | |
| `ts` | TEXT NOT NULL | |
| `actor` | TEXT NOT NULL | `doctor`, `caregiver`, `system` |
| `action` | TEXT NOT NULL | `created`, `acknowledged`, `caregiver_done`, `caregiver_cannot`, `caregiver_contact_doctor`, `overdue`, `resolved` |
| `note` | TEXT | Optional |

### `notes`

| Column | Type | Notes |
|---|---|---|
| `id` | INTEGER PK | |
| `patient_id` | TEXT NOT NULL | |
| `ts` | TEXT NOT NULL | |
| `author` | TEXT NOT NULL | Demo actor label |
| `kind` | TEXT NOT NULL | `clinical`, `caregiver`, `visit`, `follow_up` |
| `text` | TEXT NOT NULL | |

### `baselines`

| Column | Type | Notes |
|---|---|---|
| `device_id` | TEXT PK | |
| `patient_id` | TEXT NOT NULL | |
| `ready` | INTEGER NOT NULL DEFAULT 0 | |
| `windows_collected` | INTEGER NOT NULL DEFAULT 0 | |
| `windows_required` | INTEGER NOT NULL DEFAULT 4 | |
| `hr_baseline`, `spo2_baseline`, `temp_baseline` | REAL | Median personal baseline for display and evidence |
| `calibrated_at` | TEXT | |
| `stale` | INTEGER NOT NULL DEFAULT 0 | Set after server restart |
| `updated_at` | TEXT NOT NULL | |

No synthetic confidence field. The UI shows `learning 2/4`, `ready`, or `stale - recalibrating`.

### `audit_log`

| Column | Type | Notes |
|---|---|---|
| `id` | INTEGER PK | |
| `ts` | TEXT NOT NULL | |
| `actor` | TEXT NOT NULL | |
| `entity` | TEXT NOT NULL | `patient`, `device`, `alert`, `note`, `follow_up` |
| `entity_id` | TEXT NOT NULL | |
| `action` | TEXT NOT NULL | `created`, `updated`, `bound`, `unbound`, `archived`, `alert_suppressed`, `comfort_suppressed` |
| `detail` | TEXT | JSON or plain text |

`anomalies` remains the raw rule/model output. `alerts` is the workflow layer built from those outputs. Both are written; `/api/anomalies` and `/history` keep working.

## 7. Alert engine

### 7.1 Inputs

- Rule results from `evaluate_vitals` (HR, SpO2, temp).
- Model results from the personalized model.
- Fall events.
- Device status (online/offline).
- Data freshness and signal quality.
- Baseline state (learning/ready/stale).

### 7.2 Quality gate

A clinical alert is created only when the data is usable:

- `finger = 0` for more than 60 seconds -> `quality / no_finger`.
- No vitals for more than 90 seconds -> `quality / stale`.
- Device status `offline` -> `quality / offline`.
- High motion magnitude during a vital deviation -> `quality / motion_artifact` (demo heuristic; explicitly labeled unvalidated).
- Baseline `stale` or `learning` -> no model-based alert; the UI shows baseline state.

Quality alerts do not create clinical alerts. They appear in the worklist and caregiver view as non-clinical tasks.

A background monitor runs every 5 seconds to create stale/offline/no-finger quality alerts, append one overdue audit event per alert when it first becomes overdue, and auto-resolve quality tasks when the condition clears. The monitor is part of the server process; no new service is introduced.

### 7.3 Tier mapping

| Tier | Source | Demo default |
|---|---|---|
| `emergency` | Event | Fall detected |
| `emergency` | Rule | SpO2 < 88%, HR < 40 or > 140 bpm, temp >= 39.5 C or < 35.0 C, confirmed twice within 30 s with good quality |
| `actionable` | Rule | Current alert thresholds: HR < 50 or > 120, SpO2 < 92%, temp < 35.5 or >= 38.0, sustained 2 of 3 windows |
| `actionable` | Model | Model probability >= 0.8, sustained 2 of 3 windows, baseline ready, quality good |
| `watch` | Rule | Current watch thresholds, sustained 2 of 6 windows |
| `watch` | Model | Model probability 0.5-0.8, sustained 2 of 3 windows |
| `watch` | Trend | 20% change from personal baseline sustained 30 minutes (demo heuristic) |
| `quality` | Device/quality | Offline, stale, no finger, motion artifact |

All thresholds and windows are configuration values in `server/config.py`. They are demo defaults, not validated clinical rules.

### 7.4 Deduplication and storms

- `dedupe_key = patient_id + kind + tier`.
- If an open alert with the same key exists, update `last_seen_at`, `reason`, and `evidence_json`; do not create a duplicate.
- If the tier changes, resolve the old alert with `superseded by <new tier>` and create the new one.
- Cap open alerts at 10 per patient. Suppress new `watch` alerts only; quality alerts dedupe to one per kind; `actionable` and `emergency` are never suppressed. Record suppression in `audit_log` with entity `patient`, action `alert_suppressed`, and the alert key in `detail`.
- Raw anomaly messages for `/live` continue to be published with the existing 30-second throttle. Workflow dedupe is separate and applies to `alerts` only.

### 7.5 Lifecycle

```text
open -> acknowledged -> resolved
  |          |
  +----------+--> overdue (derived; no external page)
```

- `actionable` and `emergency` are owned by the caregiver when `caregiver_available = 1`; otherwise they are owned by the doctor. The doctor sees every item regardless of owner.
- `quality` follows the same owner rule as actionable alerts.
- `watch` is owned by the doctor.
- If a patient's caregiver becomes unavailable, unresolved caregiver-owned alerts are reassigned to the doctor and audited; they are not reassigned back automatically.
- `due_at`: emergency 5 minutes, actionable 10 minutes, quality 30 minutes, watch 24 hours after creation. Configurable.
- `overdue` is derived, not stored: `status != resolved` and `now > due_at`.
- Unacknowledged or overdue items sort above other items and turn red. Because there is no on-call path, nothing pages; the item remains visible until a human resolves it.
- Clinical alerts require a human resolution with a note. Quality alerts auto-resolve when the condition clears, with a system `resolved` event.
- Caregiver actions (`done`, `cannot`, `contact_doctor`) append events. `cannot` or `contact_doctor` moves the item to the doctor and restarts the overdue clock. Caregiver `done` does not resolve a clinical alert; the doctor confirms and resolves.
- A fall is always `emergency`. Comfort mode may change the message and suggested action, but not the tier.

### 7.6 Comfort mode

Hospice patients with `comfort_mode = 1`:

- `watch` alerts are suppressed; the suppression is recorded in `audit_log` with action `comfort_suppressed`.
- `actionable` alerts remain visible with comfort-appropriate messaging; they do not recommend emergency transfer unless the doctor configured that in goals of care.
- `emergency` alerts are never suppressed. Messaging includes emergency services when appropriate.
- No automatic DNR/DNI logic. All decisions remain human.

### 7.7 Evidence and reason

`evidence_json` contains:

```json
{
  "signal": "hr",
  "value": 118,
  "baseline": 78,
  "delta_pct": 51.3,
  "duration_s": 720,
  "windows": 3,
  "quality": "good",
  "source": "rule",
  "model_score": null
}
```

`reason` is a plain sentence, for example:

> Heart rate 118 bpm, 51% above this patient's baseline of 78 bpm, sustained 12 minutes. Signal quality good.

The UI must never show a model probability without the quality and baseline context.

## 8. Worklist behavior

### 8.1 Row content

```text
[tier] [patient + program] [what changed] [data] [owner/status] [age] [next action]
```

- **Tier**: worst open tier. If the patient has no usable data, show `Unknown` rather than `Stable`.
- **Patient**: display name, `PT-xxxx`, program, age.
- **What changed**: the newest open alert's `reason`, truncated to one line.
- **Data**: signal quality badge and baseline state (`learning 2/4`, `ready`, `stale`).
- **Owner/status**: `Awaiting caregiver`, `Needs doctor review`, `Acknowledged by {actor}`, `Overdue`. This is a display status derived from the raw `status`, `owner`, `caregiver_response`, and `due_at`; it is not stored.
- **Age**: age of the oldest open item.
- **Next action**: fixed mapping by tier:
  - emergency: `Call caregiver now` (or the comfort-plan instruction)
  - actionable: `Caregiver check, then doctor review`
  - watch: `Review trend`
  - quality: `Restore sensor`
  - stable: `Next review {date}`

### 8.2 Ordering

Deterministic, no composite score:

1. overdue `emergency`, then overdue `actionable`
2. unacknowledged `emergency`, then unacknowledged `actionable`
3. acknowledged `emergency`, then acknowledged `actionable`
4. `quality` (missing data is a blind spot)
5. `watch`
6. stable, by `next_review_at` (nulls last)

Ties break by oldest item age, then patient name.

`need_action` counts patients with an open `quality`, `actionable`, or `emergency` alert, or any overdue alert. `watch` alone does not count as need action.

### 8.3 Header and states

- `N patients · N need action · N overdue · last sync HH:MM`.
- System banner when MQTT is disconnected: `Live data unavailable - clinical status is Unknown`.
- Empty state when no patient needs action: `No patients need review. N stable. Next review HH:MM`.
- Loading state, API error state with retry, and a link to `Unassigned devices`.
- Filters: program, owner, and status (`needs action`, `overdue`, `all`).
- Mobile: rows become cards; no horizontal scrolling.
- Polling: worklist and caregiver views refresh every 10 seconds and 5 seconds respectively. There is no push infrastructure.

## 9. Patient detail

Sections, in order:

1. **Identity header**: `PT-xxxx`, name, DOB/age, program, goals of care, caregiver (if any), bound device, last sync, `Open live view`.
2. **Clinical status strip**: HR, SpO2, temperature, activity. Each shows value, unit, signal quality, and freshness. Missing/stale shows `Unknown`.
3. **Open alerts**: tier, reason, evidence, owner, age, ack/resolve controls.
4. **Trends**: 24-hour and 7-day charts with a baseline band and markers for alerts, notes, and visits. Downsample server-side for rendering.
5. **Baseline**: `learning x/y`, `ready`, or `stale`; last calibrated time; recalibrate button.
6. **Notes and plan**: clinical, caregiver, visit, and follow-up notes; add note.
7. **History**: resolved alerts and audit trail for this patient.
8. **Actions**: acknowledge, resolve with note, schedule follow-up, send caregiver instruction, recalibrate.

## 10. Caregiver view

- Route `/care?patient={id}`; large, plain-language task cards.
- If `caregiver_available = 0`, the page states `No caregiver assigned - doctor owns these tasks` and tasks are doctor-owned.
- No model probabilities, no raw trend charts.
- Each task shows what to check, when it was created, and three actions: `Done`, `Cannot do`, `Contact doctor`.
- `Done` records an event; the doctor confirms resolution for clinical alerts.
- `Cannot do` or `Contact doctor` returns the item to the doctor immediately with a fresh 10-minute actionable deadline, which restarts the overdue clock.
- Quality tasks auto-resolve when the sensor recovers.
- A persistent `Unknown` state if the device is offline; the task says `Check device power and WiFi`.
- Caregiver view is a demo page with polling; it is not a notification app.

## 11. Program-specific behavior

| Policy | Telehealth | Hospice |
|---|---|---|
| Default comfort mode | Off | Off; doctor may enable |
| Review rhythm | `next_review_at` and since-last-visit summary | Continuous worklist; caregiver-first |
| Watch tier | Visible, doctor-owned | Visible unless comfort mode |
| Emergency messaging | Standard | Goals-of-care instruction; emergency services when appropriate |
| Caregiver task | Only if a caregiver is available | Caregiver-first when available |

### Telehealth summary

For `program = telehealth`, patient detail includes a `Since last visit` block above the trends:

- change in HR/SpO2/temperature vs baseline,
- alerts since the last `visit` note,
- open tasks,
- care-plan changes,
- next scheduled review.

The doctor can set `next_review_at` from the detail page. No calendar integration.

## 12. API

All new endpoints are JSON. Existing endpoints remain unchanged. Actor is a demo label from the `X-Demo-Actor` header (`doctor` or `caregiver`, default `doctor`); it is not authentication.

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/clinic/worklist` | Risk-ranked worklist + counts + broker state |
| GET | `/api/patients` | List patients (optionally `program`, `archived`) |
| POST | `/api/patients` | Create patient + initial device binding |
| GET | `/api/patients/{id}` | Profile, devices, latest status, baseline, open alerts |
| PATCH | `/api/patients/{id}` | Update profile, program, comfort mode |
| POST | `/api/patients/{id}/devices` | Bind a device when none is active |
| DELETE | `/api/patients/{id}/devices/{device_id}` | Unbind |
| GET | `/api/patients/{id}/trends?hours=24` | Downsampled series + baseline band + markers |
| GET | `/api/patients/{id}/alerts?status=open` | Patient alert list |
| POST | `/api/alerts/{id}/ack` | Doctor acknowledgement |
| POST | `/api/alerts/{id}/resolve` | Doctor resolution with required note |
| POST | `/api/alerts/{id}/caregiver-response` | `done`, `cannot`, `contact_doctor` |
| GET | `/api/patients/{id}/notes` | Notes |
| POST | `/api/patients/{id}/notes` | Add note |
| GET | `/api/patients/{id}/audit` | Alert events and audit log |
| POST | `/api/patients/{id}/follow-up` | Set `next_review_at` and add a follow-up note |
| GET | `/api/care/tasks?patient_id={id}` | Caregiver task view |
| GET | `/api/devices/unassigned` | Devices with no active patient binding |

Patient create/update bodies include `caregiver_name`, `caregiver_contact`, and `caregiver_available` alongside the clinical profile.

### Worklist response shape

```json
{
  "generated_at": "2026-10-22T14:32:00+00:00",
  "broker_connected": true,
  "counts": {"patients": 12, "need_action": 2, "overdue": 1, "unknown": 1},
  "patients": [
    {
      "patient_id": "PT-0001",
      "display_name": "Demo Patient A",
      "program": "hospice",
      "age": 82,
      "tier": "actionable",
      "overdue": false,
      "oldest_open_age_s": 420,
      "what_changed": "Heart rate 118 bpm, 51% above baseline, sustained 12 minutes.",
      "data_quality": "good",
      "baseline": {"state": "ready", "windows_collected": 8, "windows_required": 8},
      "owner": "caregiver",
      "status": "awaiting_caregiver",
      "next_action": "Caregiver check, then doctor review",
      "last_sync": "2026-10-22T14:31:55+00:00",
      "next_review_at": null
    }
  ]
}
```

`status` here is the derived display status. The raw database status is `open`, `acknowledged`, or `resolved`.

### Error responses

- `400` invalid profile or missing required field.
- `404` patient/alert not found.
- `409` duplicate active binding or channel.
- `422` invalid state transition (for example, resolving an already resolved alert).
- `503` database unavailable.

## 13. Identity and safety

- Patient identity is a stable `patient_id`; devices are bound to it.
- Creating a patient requires a confirmation step that shows name, DOB, and channel before saving.
- A channel already bound to another active patient is rejected with `409`.
- Unbound devices appear in `Unassigned devices`; they never create patients silently.
- Every clinical page and alert displays `patient_id`, name, and program; patient detail also shows DOB.
- All timestamps are stored in UTC and displayed in the browser's local timezone with a timezone label.
- The public broker remains fake-data only. No PHI.
- The UI states that this is a research prototype and not a medical device.
- No medication recommendations are generated by the system.

## 14. Failure modes

| Failure | Behavior |
|---|---|
| MQTT disconnected | Banner; all live clinical statuses become `Unknown`; no new rule/model alerts; quality alerts after staleness; existing alerts stay open |
| Device offline | Immediate `quality / offline` task; clinical status `Unknown` |
| No vitals for >90 s | `quality / stale`; no last-value carry-forward |
| Server restart | Alerts/notes persist; model calibration is in-memory and restarts; `baselines.stale = 1`; UI shows `stale - recalibrating` |
| Database error | API returns `503` with a visible error page; no silent empty worklist |
| Duplicate binding | `409`; UI explains the existing binding |
| Alert storm | Dedupe, 10-open-alert cap, quality dedupe, watch suppression, emergency never suppressed |
| Clock skew | Server timestamps are authoritative; device `t` is uptime only |
| Unassigned device | Quarantine list; no clinical status |
| Comfort-mode suppression | `watch` suppressed and audited; emergency never suppressed |

## 15. Testing

### Unit tests

- Worklist ordering: overdue, tier, quality, watch, stable.
- Quality gate: no finger, stale, offline, motion artifact never create clinical alerts.
- Sustained-window logic and threshold mapping.
- Dedupe and supersede behavior.
- Owner routing with and without an available caregiver.
- Lifecycle transitions: ack, resolve, caregiver responses, overdue.
- Comfort-mode suppression and audit.
- Device binding constraints and duplicate rejection.
- Stale detection after restart.
- Evidence and reason generation.

### API tests

- Patient create/update/bind/unbind, duplicate binding, worklist shape, alert transitions, notes, audit.
- Use a temporary SQLite database per test.
- TestClient requires `httpx`; add it to a dev-only requirements file.

### UI checks

- Headed Playwright spot checks: worklist, patient detail, ack/resolve, caregiver done/cannot, live view, MQTT-down banner.
- No automated end-to-end suite, per project decision.

### Demo seed

`python -m server.seed` creates demo patients bound to `sim01`-`sim04` with both programs. It is idempotent and clearly marked as demo data. It does not fabricate clinical history; the simulator creates live data.

## 16. Acceptance criteria

1. `/` redirects to `/clinic`; `/live` serves the existing dashboard; `/history` is unchanged.
2. A patient cannot be created without name, DOB, program, and a valid device binding.
3. Duplicate active channel/device bindings are rejected.
4. The worklist shows tier, what changed, data quality, baseline state, owner/status, age, and next action, ordered as specified.
5. A no-finger, offline, or stale device produces a quality task and never a clinical alert or a `Stable` status.
6. An actionable or emergency alert creates a task owned per the caregiver rule; if unacknowledged past `due_at`, it is visibly overdue and sorts first.
7. Caregiver `Done`, `Cannot do`, and `Contact doctor` each create an audit event; `Cannot do` and `Contact doctor` return the item to the doctor.
8. A doctor can acknowledge and resolve an alert with a note; resolved items leave the worklist and remain in patient history.
9. Patient detail shows `Unknown` for missing/stale values, baseline state, plain-language evidence, and 24-hour trends.
10. Comfort mode suppresses watch alerts, keeps emergencies, and records suppression.
11. With MQTT down, the worklist shows a system banner and `Unknown` clinical states; no false normal state.
12. Existing `/live`, `/history`, and current REST endpoints continue to work.
13. With no caregiver assigned, tasks are doctor-owned and `/care` explains why.
14. The documented demo flow (seed plus simulator scenarios) produces at least one quality task, one watch, one actionable, one emergency, and one overdue item.

## 17. Risks and limitations

- This is a research prototype, not a validated medical device.
- Alert thresholds are demo heuristics and may cause false positives or false negatives.
- There is no on-call path; an overdue item is visible but not paged. Real hospice use requires coverage and escalation.
- There is no authentication; the actor switch is a demo label. Real use requires identity, access control, and an immutable audit store.
- The public MQTT broker is unauthenticated and unsuitable for PHI.
- The wearable measures HR, SpO2, temperature, and motion only; no blood pressure, respiratory rate, or consciousness. It cannot support a full early-warning score.
- Model calibration is in-memory and lost on restart; baseline rows are marked stale.
- SQLite and the single-container Render deployment are demo constraints; free Render storage is ephemeral.
- Browser polling is not a notification system; a closed caregiver page receives nothing.

## 18. Implementation boundaries

New files:

- `server/alerts.py` - tiering, lifecycle, evidence, worklist ordering.
- `server/clinic.py` - patient/device/note queries and trend aggregation.
- `server/static/clinic.html` - worklist.
- `server/static/patient.html` - patient detail.
- `server/static/care.html` - caregiver view.
- `server/static/clinic.css` and `server/static/clinic.js` - shared assets.
- `server/seed.py` - idempotent demo seed.
- `tests/test_alerts.py`, `tests/test_clinic.py`.

Modified files:

- `server/db.py` - new tables, indexes, queries.
- `server/main.py` - new routes and page serving.
- `server/mqtt_ingest.py` - quality gating and alert creation; keep anomaly logging.
- `server/anomaly.py` - source rule thresholds from config.
- `server/config.py` - thresholds, deadlines, stale windows.
- `health_dashboard.html` - add a `Clinic` link; no layout redesign.
- `server/static/history.html` - add a `Clinic` link.
- `requirements-dev.txt` - test-only `httpx`.

No new runtime service, no build step, no JavaScript framework. Shared behavior stays in vanilla JS/CSS, consistent with the current single-file dashboard.

## 19. Decisions recorded

| Decision | Value |
|---|---|
| Clinical settings | Telehealth + home hospice/elderly |
| Primary user | Doctor, with caregiver at home |
| Home screen | Triage worklist |
| Alerting | Tiered, caregiver-first, tunable |
| Patient context | Minimal clinical profile |
| Accountability | Doctor + caregiver; caregiver optional per patient; doctor owns when absent; no on-call |
| Risk display | Worst open tier + age; no synthetic risk score |
| Zero state | `Unknown`, never `Stable` or last value |
| Comfort mode | Suppresses watch, never emergency |
| Polling | Worklist 10 s, caregiver 5 s |
| Ack deadlines | Emergency 5 min, actionable 10 min, quality 30 min, watch 24 h |
| Stale thresholds | Offline status immediate; stale data 90 s; no finger 60 s |
| Sustained logic | 2 of 3 windows for actionable/emergency, 2 of 6 for watch |
| Open-alert cap | 10 per patient; only watch suppressed; emergency never suppressed |
