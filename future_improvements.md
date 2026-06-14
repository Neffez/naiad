# Naiad — Future Improvements & Innovations

Idea collection from the code review on 2026-06-10. Ordered by recommended
priority; the first two tie directly into pain points that surfaced during the
review. Recommended order: **1 → 2 → 4**, then 3/5 depending on available
hardware, with 6 as a follow-up stage.

---

## 1. Decision log ("Why didn't it water?") — ✅ implemented 2026-06-11

**Problem:** The factor calculation has grown complex (daily peaks, rain
confirmation, rain credit, decay, forecast window) but is *ephemeral* — nobody
can reconstruct why yesterday's 6:00 run watered at factor 40 % or was skipped.
The water-balance suspicion from the review ("does peak_tomorrow even apply?")
had to be settled by code analysis; a decision log would have answered it in
the UI.

**Proposal:** Persist the `FactorResult` inputs as a row on every cron/plan
fire:

- Timestamp, sequence, decision (`started` / `skipped` + reason)
- Factor inputs: temperature (max), today/tomorrow rain peaks, probabilities,
  rain credit, effective mode, resulting factor

Plus a small view in the history page ("Decisions") or an expandable detail on
each history entry.

**Effort:** small (one table, one hook in `_run_sequence_job`, one UI list).
**Value:** high — makes the system auditable.

Implemented (2026-06-11): `decision_log` table written by the shared gate path
(`run_sequence_job` — covers cron, plans and MQTT starts; expired deferred cron
occurrences are logged too). Every deterministic outcome is recorded as
`started`/`skipped` + reason (`disabled`, `user_skipped`, `paused`,
`master_off`, `wind`, `season_off`, `zero_factor`, `expired`) together with the
factor inputs actually used: max temperature, today/tomorrow rain peaks and
probabilities, rain credit, effective rain mode, manual-override flag and the
resulting factor breakdown. Transient busy/conflict outcomes are not logged —
their retry produces the row. Exposed via `GET /history/decisions` and a
"Decisions" tab on the history page with expandable per-entry inputs. Rows
older than a year are pruned automatically; "delete history" clears the
decision log alongside the runs.

---

## 2. MQTT control entities (not just statistics) — ✅ implemented 2026-06-10

**Starting point:** The MQTT discovery infrastructure already exists
(`stats_publisher.py`) but only publishes sensors.

**Proposal:** Additionally publish:

- **Master switch** (watering on/off)
- **Start/stop buttons per sequence**
- **Number entity** for the manual adjustment factor

This makes Naiad controllable from HA automations and via voice assistant
("start lawn watering") without opening the Naiad UI. The safety model stays
intact because every command goes through the existing runner gates (master,
wind, conflicts, recovery lock).

**Effort:** medium. **Value:** the biggest integration lever for the project.

Implemented (2026-06-10): `switch.naiad_master`, `switch.naiad_manual_mode`,
`number.naiad_manual_factor`, and `button.naiad_start_<sequence>` /
`button.naiad_stop_<sequence>`. Starts run through the same gate path as
scheduled runs (`run_sequence_job`); runs appear in the history with trigger
`mqtt`.

### 2b. Follow-up ideas (not yet implemented)

Candidates for a second MQTT-control iteration, roughly ordered by value:

- **Start/stop per zone.** The backend already supports standalone single-zone
  runs end to end (`runner.start_zone`: watchdog, crash recovery, pending-close,
  history; REST endpoints in `api/zones.py`). The real value: the valve switches
  are HA entities anyway, but toggling them directly bypasses Naiad entirely —
  no watchdog, no time bound, and reconciliation closes externally opened valves
  again. An MQTT zone start would use the managed path instead. One design
  question: a zone start *requires* a duration (the weather factor is
  intentionally not applied), and an HA button cannot carry one. Options:
  1. One global `number.naiad_zone_duration` plus
     `button.naiad_start_zone_<zone>` / `button.naiad_stop_zone_<zone>` per
     zone — the button starts with the configured duration (default e.g.
     10 min, matching planned zone runs without a duration). Voice-friendly,
     only one extra entity. **Recommended.**
  2. Use the implicit zone duration from sequences.
  Gates as in the REST/plan path (`_run_zone_job`: master, switch present, zone
  conflicts, recovery lock). Wind/season deliberately do not apply to single
  zones (consistent with today); the rain abort still covers running zone runs.
- **"Stop all" button.** Aborts every live run (and discards pause snapshots).
  Trivial to build, very voice-friendly ("stop the watering"), and valuable as a
  panic button in automations (window-open sensor, pool party).
- **Status sensors as automation triggers:** `binary_sensor.naiad_running`,
  `sensor.naiad_current_run` (which sequence/zone) and `sensor.naiad_next_run`
  (timestamp, from `next_run_for_sequence`). Not control, but the missing half
  for HA automations — "don't start the mower while watering runs" currently
  requires watching the individual valve switches.
- **Pause/resume buttons per sequence.** `runner.pause` and resume-via-start
  already exist; pausing by voice is a real use case ("pause, I'm walking
  through the garden").
- **"Skip sequence" switch** (`SequenceOverride.paused`) — the counterpart of
  the skip toggle in the settings; rarely automated, but cheap.
- A `select` for the rain mode or similar is deliberately out: that is
  configuration, not control, and belongs in the UI.

---

## 3. Soil moisture per zone

The natural evolution of the water balance: an optional `moisture_entity` +
threshold per zone (cheap Zigbee soil moisture sensors are widespread). Zones
above the threshold are skipped **within** a sequence instead of cancelling the
whole sequence. Fits cleanly into `_run_zones` and turns the forecast heuristic
into actual closed-loop control.

**Effort:** medium (config + skip path + UI). **Prerequisite:** sensors
available.

---

## 4. Pump / master valve relay

A classic irrigation setup Naiad currently doesn't model: a pump or master
valve that must run while *any* zone is open. Today this would have to be
rebuilt in HA — error-prone exactly where Naiad is otherwise meticulous
(crash recovery, PendingClose).

**Proposal:** An optional `pump_switch` in the config that the runner opens
before the first zone and closes after the last — with the same safety
mechanisms as zone valves (pending-close retry, reconcile, crash recovery),
optionally with a configurable lead/lag time.

**Effort:** medium (runner integration done carefully). **Value:** covers a
very common hardware setup natively.

---

## 5. Flow monitoring / leak alarm

Fits the project's safety DNA. With a real flow sensor, Naiad can compare
expected vs. actual:

- Valve open but no flow → broken pump / broken valve
- Flow without an open valve → leak / burst pipe, optionally with master-off

Even without any actuation, the notification alone would be valuable. Side
effect: measured flow could replace the `flow_lph` estimation model for the
liter statistics (measured instead of computed liters).

**Effort:** medium. **Prerequisite:** flow sensor.

---

## 6. The big innovation: a true ET₀ water balance — ✅ stages 1–3 implemented 2026-06-14

The water-balance mode is halfway there: it knows the rain *income*, but the
*expenses* are only the linear temperature factor. A true balance computes
evapotranspiration (ET₀ via Hargreaves or FAO-56 Penman-Monteith; HA weather
integrations provide the inputs: temp min/max, humidity, wind, radiation)
against rain + irrigation **per zone**, with a soil reservoir based on soil
type / root depth.

That is the level of Hydrawise/OpenSprinkler and would elevate Naiad from a
"weather-driven timer" to an "irrigation controller".

**Effort:** large — best staged:
1. ET₀ as a sensor input or internal calculation
2. Daily balance per zone (reservoir size from soil type / root depth)
3. Recommended runtime derived from the balance deficit

**Important:** tackle this only after item 1 (decision log) — without an audit
trail, a soil balance cannot be debugged (see the review experience with
`peak_tomorrow`).

Stage 1 implemented (2026-06-13) as a third rain mode `et0` next to `forecast`
and `water_balance`: the water-balance factor mapping stays, but the decayed
rain credit is replaced by a physical soil water balance. Per local day the
balance gains the day's actual rain (positive deltas of
`sensors.precipitation_actual`, optionally rain-sensor-gated) and loses the
day's ET₀ — from an optional daily `sensors.et0` entity (e.g. Smart
Irrigation), else computed internally via Hargreaves (FAO-56, validated against
the FAO reference examples) from the temperature sensor's daily min/max and the
HA home latitude (fetched automatically via `get_config`). The balance is
clamped to a configurable soil reservoir (`et0_reservoir_mm`, field capacity of
the root zone); days without any ET₀ data fall back to the
`water_balance_decay` heuristic; today only adds rain (its evaporation has
mostly not happened yet at decision time — the forecast side covers the day
ahead). Refreshed hourly/on rain transitions/on settings changes like the rain
credit; surfaced in the decision log (`rain_mode: et0`, `rain_credit_mm` =
balance), the MQTT `rain_credit` sensor and the settings UI (mode toggle +
reservoir).

Stage 2 implemented (2026-06-14) as a fourth rain mode `et0_zonal`: the same
physical balance, but kept **per zone** and persisted to a `zone_water_balance`
table. Each zone's reservoir is derived from its configured soil type
(sand/loam/clay → plant-available water fraction) and root depth (with a
management-allowed depletion fraction), or set explicitly via `reservoir_mm`.
Reference ET₀ is scaled by a per-zone crop coefficient (`crop_coefficient`,
ETc = Kc·ET₀), and the zone's **own irrigation** becomes an income term:
completed `RunHistory` liters are converted to applied mm via the zone
`area_m2` (1 L/m² = 1 mm) and fill the balance alongside rain. The factor keeps
using one sequence-level credit (the factor path is not yet per-zone — that is
stage 3): the most-depleted zone's balance drives the adjustment, so the driest
zone is never under-watered. Refreshed on the same hourly/rain-transition/
settings cadence; surfaced in the decision log (`rain_mode: et0_zonal`), the
MQTT `rain_credit` sensor and the settings UI (mode toggle + per-zone soil
panel). Soil parameters are optional with neutral defaults, so existing
installations are unaffected until they opt in.

Stage 3 implemented (2026-06-14): in `et0_zonal` mode each zone now runs only
long enough to refill *its own* balance deficit, instead of all zones sharing
one factor-scaled duration. The runtime is `deficit_mm / application_rate`,
where the application rate is `flow_lph / area_m2` (1 L/m² = 1 mm), clamped to
the sequence's configured min/max range. This is confined to the normal start
and pause/resume path in `SequenceRunner._run_zones`; the safety-critical
override paths (standalone single-zone runs and crash recovery, which carry an
explicit duration) are untouched, and a zone without a usable application rate
falls back to the factor-scaled duration. The sequence-level skip gate still
uses the aggregate (driest-zone) factor, so a sequence whose driest zone is
already saturated is skipped wholesale as before.

Possible future refinement: skip an individual *saturated* zone within a
sequence (today its runtime is clamped up to the range minimum rather than to
zero), which would need per-zone skipping in the runner's zone loop.

---

## Quick wins (each < 1 day) — ✅ implemented 2026-06-11

| Idea | Description |
|------|-------------|
| **Frost lockout** | No run when the forecast daily minimum is below e.g. 3 °C — a small additional gate in the factor path, protects pipes in the shoulder seasons. |
| **Cost display** | Liters are already tracked; a `€/m³` config value turns them into costs on the dashboard/history. |
| **Cistern mode** | Level sensor + minimum level → skip runs (or switch to mains water via a second switch). A common setup in German gardens. |
| **PWA manifest** | The mobile UI is good — making it installable as a home-screen app (manifest + service worker) is nearly free. |
| **Calendar week view in the planner** | `upcoming_runs` already provides the data; only the presentation is missing. |

Implemented (2026-06-11):

- **Frost lockout** — optional `frost` config (forecast daily-minimum sensor +
  threshold, default 3 °C). Gates the shared automatic start path
  (`run_sequence_job`: cron, plans, MQTT) and logs `skipped`/`frost` to the
  decision log with the factor inputs; manual starts are unaffected and an
  unreadable sensor never blocks watering. Configured under Settings →
  Connection & sensors.
- **Cost display** — `water_price_per_m3` config value (Settings → Advanced);
  the dashboard usage card and the history summary show the cost of the
  tracked liters (EUR, locale-formatted). 0 hides the display.
- **Cistern mode** — optional `cistern` config (level sensor + minimum level in
  the sensor's unit). Skip-only variant: below the minimum, automatic runs are
  skipped (`cistern_low` in the decision log) — the mains-switch variant
  remains future work. Same gate semantics as frost.
- **PWA** — manifest with PNG/maskable icons (generated via
  `scripts/generate_pwa_icons.py`), apple-touch-icon, and a service worker
  (`sw.js`: app-shell network-first, hashed assets cache-first, API never
  cached). Registration is ingress-prefix-aware.
- **Calendar week view in the planner** — new `GET /plans/upcoming?days=N`
  (plans + cron fires merged, skips excluded) rendered as a 7-day grid
  (stacked list on mobile) below the planner form.

---

## Related open items from the code review

Technical (non-feature) items that remain documented in `codereview.md`:
login throttle behind a reverse proxy (B-3), token hashing (B-4),
TypeDecorator for naive-UTC datetimes (B-7), request ID in logs (B-10).
