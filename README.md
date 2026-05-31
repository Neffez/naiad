<div align="center">
  <img src="docs/assets/logo.svg" alt="Naiad" width="420">

  **Garden irrigation controller for Home Assistant.**
</div>

---

> **Status:** alpha. Backend functional (schedules, sequences, factors, HA integration). Frontend implements the full "Naiad Control Surface" design across all four screens (Dashboard, Planner, History, Settings).

Naiad replaces the irrigation automation logic that typically lives inside Home Assistant (Irrigation Unlimited, automations, pyscript, helpers, dashboard cards) with a single standalone web application. Home Assistant remains the driver for the physical switches and the source of weather and sensor data; everything else — schedules, factor calculation, manual planning, history, UI — happens in Naiad.

## Why

The HA-native irrigation stack is powerful but spread across too many layers. A small change — adding a zone, adjusting a schedule, tweaking a watchdog — requires coordinated edits across YAML, automations, pyscript, helpers, and dashboard cards. Naiad consolidates that logic into one codebase with a clean web UI and a single configuration file.

## Scope

- **Hardware-agnostic.** A valve is any Home Assistant `switch.*` entity, so whatever HA can switch (KNX, Zigbee, Shelly, Tasmota, …) works — Naiad itself knows nothing about the underlying bus.
- **Requires Home Assistant** as the hardware driver layer: it switches valves and supplies the rain/wind/season sensors and weather forecasts over the HA WebSocket API.
- Developed and run against a KNX setup, so that combination is the most exercised; other `switch.*`/`binary_sensor.*` hardware is supported by the same driver layer but less tested.

## Tech stack

- Python 3.12 + FastAPI backend, served as a single Docker image
- React + Vite + TypeScript + CSS frontend (statically served by the backend)
- TanStack React Query for data fetching, `react-i18next` for i18n (DE + EN)
- SQLite for persistence (SQLModel ORM)
- APScheduler for cron-style scheduling
- Real-time updates via WebSocket (sequence state, valve changes, factor updates, HA status)
- Docker images published to GHCR for `amd64` + `arm64`

## Architecture

Naiad runs as a single container. The FastAPI backend serves the REST API, the
live WebSocket, and the statically built React frontend. All irrigation logic
lives in the backend; Home Assistant is reduced to a hardware driver and a
sensor/weather source.

```
┌──────────────────────────────────────────────┐
│        Browser (desktop tablet + phone)      │
│             React SPA · PWA                  │
└───────────────────┬──────────────────────────┘
                    │ HTTPS + WebSocket
┌───────────────────▼──────────────────────────┐
│  Naiad container                             │
│   FastAPI  →  REST API + live WebSocket      │
│   APScheduler  →  sequence crons · watchdog  │
│                   · plan tick                │
│   Domain  →  sequences · factors · resume    │
│              · liter tracking · mutex        │
│   SQLite (SQLModel)  →  config overrides ·   │
│                         plans · history ·    │
│                         resume snapshot      │
│   HA client (WebSocket)  →  auto-reconnect · │
│                             state cache      │
└───────────────────┬──────────────────────────┘
                    │ WebSocket
┌───────────────────▼──────────────────────────┐
│              Home Assistant                  │
│     switches · weather · notify              │
└──────────────────────────────────────────────┘
```

The valve and sensor layers sit behind `IValveDriver` / `ISensorSource`
protocols (`src/backend/naiad/drivers/`). v1 ships `HAEntityDriver` /
`HAEntitySensorSource`, which talk to any `switch.*` / `sensor.*` /
`binary_sensor.*` over the HA WebSocket API. A direct KNX/IP driver via xknx can
be added later without touching the core.

## Quickstart

```bash
git clone https://github.com/Neffez/naiad
cd naiad
cp .env.example .env          # add HA_TOKEN and NAIAD_PASSWORD_HASH
mkdir -p data
cp config.example.yaml data/config.yaml  # first-boot seed; afterwards edit in the UI
docker compose up -d
```

Open `http://<host>:8080` in your browser.

## Configuration

The configuration lives in the SQLite database and is **edited in the UI**
(Settings → System → *System configuration*): HA connection, sensor mapping,
zones, sequences, factors, and auth. Changes are validated on save and applied
live without a restart (a restart is only needed when the HA connection URL/token
itself changes). Use **Export/Import** in the config editor for backup and
git/vault versioning.

`config.yaml` is **optional**. If no database config exists yet, Naiad starts
empty and you configure everything in the UI. As a convenience you can instead
seed the first boot from a `config.yaml` (mounted at `/data/config.yaml` in
Docker, or pointed to by `NAIAD_CONFIG`) — start from
[`config.example.yaml`](config.example.yaml). After seeding, the database is
authoritative and the YAML is no longer read.

### Environment variables

Secrets are never stored in the database or YAML — they come from the
environment only (see [`.env.example`](.env.example)).

| Variable | Required | Purpose |
|---|---|---|
| `HA_TOKEN` | yes (unless running as the HA app) | Home Assistant long-lived access token (HA → profile → Security). |
| `NAIAD_PASSWORD_HASH` | when `auth.mode: password` | App password, bcrypt hash. Generate with `python -c "import bcrypt; print(bcrypt.hashpw(b'pw', bcrypt.gensalt()).decode())"`. |
| `NAIAD_CONFIG` | no | Path to an optional first-boot seed `config.yaml` (default `/data/config.yaml`). |
| `NAIAD_DATA_DIR` | no | Directory for the SQLite database (default `/data`). |
| `MQTT_PASSWORD` | when `mqtt.enabled` and the broker requires auth | Password for the MQTT broker used by the statistics bridge. |
| `TZ` | recommended | Scheduler timezone, e.g. `Europe/Berlin`. |

### Configuration sections

| Section | Purpose |
|---|---|
| `ha` | HA WebSocket URL, token, and `notify_targets` for push notifications. |
| `mqtt` | Optional MQTT statistics bridge — see [Statistics in Home Assistant](#statistics-in-home-assistant). `enabled`, broker `host`/`port`/`username`, `discovery_prefix`, `base_topic`. |
| `auth` | `mode` (`password` \| `forward_header` \| `none`), the shared `password`, optional `auto_login` for trusted embedding contexts, `ingress` trust for the HA add-on sidebar (additive — coexists with `mode`), and `frame_ancestors` for the CSP header. |
| `sensors` | Entity IDs for rain, wind, season, temperature, and the four precipitation forecast sensors. |
| `zones` | Per-zone `label`, `switch` entity, and `flow_lph` (used for liter tracking). |
| `sequences` | Ordered `zones`, `basis_min_per_zone`, allowed `range`, `watchdog_min`, `schedule.cron`, `enabled`, and `wind_blocks` (sets the factor to 0 on a wind alarm). |
| `factors` | `temp` (linear scaling around `basis_c`) and `rain` (forecast-based reduction with `threshold_prob`, `reduce_above_mm`, `zero_above_mm`, `forecast_decay`). |

## Statistics in Home Assistant

Naiad keeps its own run history in SQLite (visible on the History screen). It can
*also* mirror the tracked liters and run durations back into Home Assistant as
native sensor entities, so the data flows on into HA's long-term statistics and —
via HA's InfluxDB integration — into InfluxDB and Grafana.

This uses [MQTT discovery](https://www.home-assistant.io/integrations/mqtt/#mqtt-discovery):
when `mqtt.enabled` is set and a broker is reachable, Naiad publishes (retained)
discovery configs and state under one **Naiad** device. The entities:

| Entity | Type | Meaning |
|---|---|---|
| `sensor.naiad_water_total` | `total_increasing`, `water`, `L` | Cumulative liters across all zones |
| `sensor.naiad_water_<zone>` | `total_increasing`, `water`, `L` | Cumulative liters per zone |
| `sensor.naiad_runtime_total` | `total_increasing`, `duration`, `min` | Cumulative run minutes |
| `sensor.naiad_runtime_<zone>` | `total_increasing`, `duration`, `min` | Cumulative run minutes per zone |
| `sensor.naiad_last_run_liters` | `measurement`, `water`, `L` | Liters of the most recent run |
| `sensor.naiad_last_run_duration` | `measurement`, `duration`, `min` | Minutes of the most recent run |
| `sensor.naiad_last_run` | `timestamp` | When the most recent run ended |

The values are recomputed from the SQLite history on every publish (after each
run, including external/manual valve activity, and on every (re)connect), so they
never drift from what Naiad recorded. Messages are retained, so the figures
survive both Naiad and Home Assistant restarts.

For the Grafana path: HA's InfluxDB integration exports **state changes** (not
the statistics tables), so it picks these sensors up automatically — point Grafana
at InfluxDB and build the dashboard from there (e.g. a per-day water consumption
panel via `difference()` on the cumulative `naiad_water_total`).

The bridge is entirely optional and best-effort: a missing or unreachable broker
is logged and ignored — it never affects irrigation.

## Hardware compatibility

Naiad works with any hardware that Home Assistant exposes as the right entity
types — it talks only to HA, never to a specific bus. The table notes which
combinations are actually exercised in practice (the author runs KNX).

| Component | Status | Notes |
|---|---|---|
| Valves — any HA `switch.*` | ✅ works | Whatever HA can switch (KNX, Zigbee, Shelly, Tasmota, …). Most exercised on KNX actuators, whose staircase timer also acts as an external hardware watchdog. |
| Sensors — any `binary_sensor.*` / `sensor.*` | ✅ works | Rain / wind / season + temperature, mapped through `sensors`. Most exercised with KNX sensors. |
| OpenWeatherMap precipitation sensors | ✅ tested | Probability + amount, today and tomorrow. |
| Push via `notify.mobile_app_*` | ✅ tested | HA Companion app. |
| Direct KNX/IP (xknx) driver | ⬜ planned (v2) | Designed for via the driver layer; not implemented. v1 talks to hardware only through Home Assistant. |

## Local Development (without Docker)

Prerequisites: Python 3.12+, Node 20+.

**One-time setup**

```bash
# From the project root — optional: seed the first boot from a config.yaml.
# Skip this entirely to start empty and configure everything in the UI.
mkdir -p data
cp config.example.yaml data/config.yaml   # adjust zones, sequences, sensors
```

If you do seed from YAML, it applies on first boot only — afterwards the
database is the source of truth and you edit the config in the UI. To re-seed
from YAML, delete `data/naiad.db` first.

**Terminal 1 — Backend**

Linux/macOS
```bash
cd src/backend
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
set -a; source ../../.env; set +a
NAIAD_CONFIG=../../data/config.yaml NAIAD_DATA_DIR=../../data \
  uvicorn naiad.main:app --host localhost --port 8080 --reload
```

Windows (PowerShell)
```powershell
cd src/backend
python -m venv .venv; .venv\Scripts\activate
pip install -e ".[dev]"
Get-Content ..\..\\.env | Where-Object { $_ -match '^[^#].+=.' } |
  ForEach-Object { $k,$v = $_ -split '=',2; [System.Environment]::SetEnvironmentVariable($k,$v) }
$env:NAIAD_CONFIG="..\..\data\config.yaml"; $env:NAIAD_DATA_DIR="..\..\data"
uvicorn naiad.main:app --host localhost --port 8080 --reload
```
**Terminal 2 — Frontend**

```bash
cd src/frontend
npm install --legacy-peer-deps  # only on first run
npm run dev
```

Open `http://localhost:5173` in Browser.

The vite-dev-server will proxy `/api/*` to `http://localhost:8080`, WebSocket included — no CORS-Setup required.

**Tests & Linting (Backend)**

```bash
cd src/backend && pytest
ruff check naiad tests
mypy naiad
```

## License

[MIT](LICENSE) — Copyright (c) 2026 Neffez.

---

<sub>Naiads are the freshwater nymphs of Greek mythology — spirits of springs, brooks and fountains. A fitting patron for a tool that decides when and how much water to send into a garden.</sub>
