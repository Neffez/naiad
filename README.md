<div align="center">
  <img src="docs/assets/logo.svg" alt="Naiad" width="420">

  **Garden irrigation controller for Home Assistant, optimized for KNX.**
</div>

---

> **Status:** alpha. Backend functional (schedules, sequences, factors, HA integration). Frontend implements the full "Naiad Control Surface" design across all four screens (Dashboard, Planner, History, Settings).

Naiad replaces the irrigation automation logic that typically lives inside Home Assistant (Irrigation Unlimited, automations, pyscript, helpers, dashboard cards) with a single standalone web application. Home Assistant remains the driver for the physical switches and the source of weather and sensor data; everything else — schedules, factor calculation, manual planning, history, UI — happens in Naiad.

## Why

The HA-native irrigation stack is powerful but spread across too many layers. A small change — adding a zone, adjusting a schedule, tweaking a watchdog — requires coordinated edits across YAML, automations, pyscript, helpers, and dashboard cards. Naiad consolidates that logic into one codebase with a clean web UI and a single configuration file.

## Scope

- **Optimized for** KNX setups with switch actuators, rain/wind/season sensors, and OpenWeatherMap forecasts — specifically developed and tested on **KNX** hardware.
- **Hardware-agnostic by design.** Any Home Assistant `switch.*` entity works as a valve through the abstract driver layer. Non-KNX setups are experimental and untested.
- **Requires Home Assistant** as the hardware driver layer (v1). A direct KNX/IP driver via xknx is planned for v2.

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
cp config.example.yaml data/config.yaml  # adjust zones, sequences, sensors
docker compose up -d
```

Open `http://<host>:8080` in your browser.

## Configuration

Naiad reads a single `config.yaml` (mounted at `/data/config.yaml` in Docker,
or pointed to by `NAIAD_CONFIG`). It is validated at startup with descriptive
errors. Tunable values (base durations, watchdog minutes, factor parameters)
can be overridden from the Settings UI; those overrides are stored in SQLite,
while the YAML serves as the versioned default. Start from
[`config.example.yaml`](config.example.yaml).

### Environment variables

Secrets never live in the YAML — they are referenced as `${VAR}` and read from
the environment (see [`.env.example`](.env.example)).

| Variable | Required | Purpose |
|---|---|---|
| `HA_TOKEN` | yes | Home Assistant long-lived access token (HA → profile → Security). |
| `NAIAD_PASSWORD_HASH` | when `auth.mode: password` | App password, bcrypt hash. Generate with `python -c "import bcrypt; print(bcrypt.hashpw(b'pw', bcrypt.gensalt()).decode())"`. |
| `NAIAD_CONFIG` | no | Path to `config.yaml` (default `/data/config.yaml`). |
| `NAIAD_DATA_DIR` | no | Directory for the SQLite database (default `/data`). |
| `TZ` | recommended | Scheduler timezone, e.g. `Europe/Berlin`. |

### Configuration sections

| Section | Purpose |
|---|---|
| `ha` | HA WebSocket URL, token, and `notify_targets` for push notifications. |
| `auth` | `mode` (`password` \| `forward_header` \| `none`), the shared `password`, optional `auto_login` for trusted embedding contexts, and `frame_ancestors` for the CSP header. |
| `sensors` | Entity IDs for rain, wind, season, temperature, and the four precipitation forecast sensors. |
| `zones` | Per-zone `label`, `switch` entity, and `flow_lph` (used for liter tracking). |
| `sequences` | Ordered `zones`, `basis_min_per_zone`, allowed `range`, `watchdog_min`, `schedule.cron`, `enabled`, and `wind_blocks` (sets the factor to 0 on a wind alarm). |
| `factors` | `temp` (linear scaling around `basis_c`) and `rain` (forecast-based reduction with `threshold_prob`, `reduce_above_mm`, `zero_above_mm`, `forecast_decay`). |

## Hardware compatibility

Naiad is developed and tested against a specific KNX setup. Anything that
exposes the right entity types in Home Assistant should work, but only the
combinations below are exercised in practice.

| Component | Status | Notes |
|---|---|---|
| KNX switch actuators | ✅ tested | Any HA `switch.*` works. The actuator's 3 h staircase timer acts as an external hardware watchdog. |
| Generic HA `switch.*` valves | 🟡 experimental | Supported by design via the driver layer; not tested on non-KNX hardware. |
| KNX rain / wind / season `binary_sensor.*` | ✅ tested | Mapped through `sensors`. Any `binary_sensor.*` works. |
| OpenWeatherMap precipitation sensors | ✅ tested | Probability + amount, today and tomorrow. |
| Direct KNX/IP (xknx) driver | ⬜ planned (v2) | Designed for; not implemented. v1 talks to hardware only via the HA WebSocket API. |
| Push via `notify.mobile_app_*` | ✅ tested | HA Companion app. |

## Local Development (without Docker)

Prerequisites: Python 3.12+, Node 20+.

**One-time setup**

```bash
# From the project root
cp config.example.yaml data/config.yaml   # adjust zones, sequences, sensors
```

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
