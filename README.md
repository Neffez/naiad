<div align="center">
  <img src="docs/assets/logo.svg" alt="Naiad" width="420">

  **Garden irrigation controller for Home Assistant, optimized for KNX.**
</div>

---

> **Status:** pre-alpha. Architecture draft only — nothing runs yet.

Naiad replaces the irrigation automation logic that typically lives inside Home Assistant (Irrigation Unlimited, automations, pyscript, helpers, dashboard cards) with a single standalone web application. Home Assistant remains the driver for the physical switches and the source of weather and sensor data; everything else — schedules, factor calculation, manual planning, history, UI — happens in Naiad.

## Why

The HA-native irrigation stack is powerful but spread across too many layers. A small change — adding a zone, adjusting a schedule, tweaking a watchdog — requires coordinated edits across YAML, automations, pyscript, helpers, and dashboard cards. Naiad consolidates that logic into one codebase with a clean web UI and a single configuration file.

## Scope

- **Optimized for** KNX setups with switch actuators, rain/wind/season sensors, and OpenWeatherMap forecasts.
- **Hardware-agnostic by design.** Any Home Assistant `switch.*` entity works as a valve through the abstract driver layer.

## Planned tech stack

- Python 3.12 + FastAPI backend, served as a single Docker image
- React + Vite + TypeScript frontend (statically served by the backend)
- SQLite for persistence
- APScheduler for cron-style scheduling
- Docker images published to GHCR for `amd64` + `arm64`

## License

[MIT](LICENSE) — Copyright (c) 2026 Neffez.

---

<sub>Naiads are the freshwater nymphs of Greek mythology — spirits of springs, brooks and fountains. A fitting patron for a tool that decides when and how much water to send into a garden.</sub>
