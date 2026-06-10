# Naiad — Future Improvements & Innovations

Idea collection from the code review on 2026-06-10. Ordered by recommended
priority; the first two tie directly into pain points that surfaced during the
review. Recommended order: **1 → 2 → 4**, then 3/5 depending on available
hardware, with 6 as a follow-up stage.

---

## 1. Decision log ("Why didn't it water?")

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

---

## 2. MQTT control entities (not just statistics)

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

## 6. The big innovation: a true ET₀ water balance

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

---

## Quick wins (each < 1 day)

| Idea | Description |
|------|-------------|
| **Frost lockout** | No run when the forecast daily minimum is below e.g. 3 °C — a small additional gate in the factor path, protects pipes in the shoulder seasons. |
| **Cost display** | Liters are already tracked; a `€/m³` config value turns them into costs on the dashboard/history. |
| **Cistern mode** | Level sensor + minimum level → skip runs (or switch to mains water via a second switch). A common setup in German gardens. |
| **PWA manifest** | The mobile UI is good — making it installable as a home-screen app (manifest + service worker) is nearly free. |
| **Calendar week view in the planner** | `upcoming_runs` already provides the data; only the presentation is missing. |

---

## Related open items from the code review

Technical (non-feature) items that remain documented in `codereview.md`:
login throttle behind a reverse proxy (B-3), token hashing (B-4),
TypeDecorator for naive-UTC datetimes (B-7), request ID in logs (B-10).
