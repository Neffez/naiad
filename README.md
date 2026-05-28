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

## UI

"Naiad Control Surface" — a dark, water-themed control surface. Not a plant tracker, not a marketing page.

- **Dark theme** default (`#0c1413` deep pond background), light theme optional
- **Accent:** petrol-teal (`#5ec8d8` active/live, `#1a7a8a` brand) + leaf green for idle/healthy states
- **Typography:** Helvetica Neue / Arial, tabular-nums for all timers, liters, and percentages
- **Touch-friendly:** all primary targets ≥ 44 px; designed for a 10" FullHD touchscreen in a hallway
- **Glanceable:** next irrigation run is the hero element, not the adjustment factor
- **No scroll** on the 1920×1080 Visu layout — everything above the fold

Layouts: 3-column desktop/tablet (today-block · sequence grid · valves+chart), stacked mobile (430×932) with bottom navigation. Embedded in Home Assistant via `type: iframe` with `?embed=1` hiding the sidebar.

## Tech stack

- Python 3.12 + FastAPI backend, served as a single Docker image
- React + Vite + TypeScript frontend (statically served by the backend)
- Custom CSS design system (`naiad-tokens.css`) — CSS custom properties, no utility framework
- TanStack React Query for data fetching, `react-i18next` for i18n (DE + EN)
- SQLite for persistence (SQLModel ORM)
- APScheduler for cron-style scheduling
- Real-time updates via WebSocket (sequence state, valve changes, factor updates, HA status)
- Docker images published to GHCR for `amd64` + `arm64`

## Quickstart

```bash
git clone https://github.com/Neffez/naiad
cd naiad
cp .env.example .env          # add HA_TOKEN and NAIAD_PASSWORD_HASH
cp config.example.yaml data/config.yaml  # adjust zones, sequences, sensors
docker compose up -d
```

Open `http://<host>:8080` in your browser.

## License

[MIT](LICENSE) — Copyright (c) 2026 Neffez.

---

<sub>Naiads are the freshwater nymphs of Greek mythology — spirits of springs, brooks and fountains. A fitting patron for a tool that decides when and how much water to send into a garden.</sub>
