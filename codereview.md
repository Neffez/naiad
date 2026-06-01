# Code Review — Naiad

**Scope:** Independent full-codebase architecture and clean-code review of the
Naiad garden irrigation controller (FastAPI/SQLModel backend + React/TypeScript
frontend, integrating with Home Assistant over WebSocket).
**Date:** 2026-06-01
**Branch:** `claude/architecture-clean-code-review-WKNHX`
**Reviewed against:** `CLAUDE.md` project rules, `docs/openapi.yaml` contract.

**CI reproduced locally (Python 3.12):** `ruff check` ✅ · `ruff format --check`
(36 files) ✅ · `mypy naiad` (36 files, no issues) ✅ · `pytest` **241 passed** ✅.
Frontend `tsc -b` ✅ (baseline, before the strict-mode change below).

---

## 1. Summary / Verdict

Naiad is a cleanly layered, carefully engineered codebase. The
`config → domain → drivers → api → scheduler` layering is consistent, the
`domain/` layer is largely pure and well unit-tested, and the genuinely hard
problems (valve left open after a crash, double liter-counting, timezone
bucketing) are actually solved — not just commented. Quality is well above
average for a project of this size.

There is **one** substantive security finding (auth fails open by default in
`forward_header` mode) and a set of clean-code / consistency items, two of which
are direct `CLAUDE.md` violations (TypeScript strict mode is not enabled;
hardcoded display strings).

Counts: **High 3 · Medium 3 · Low ~7.**

> **Status (this branch):** all 3 High, M-1, M-2, and L-1/L-2 are **fixed and
> verified** — see §7. Remaining: M-3 and the minor Low items, deferred as
> follow-ups.

---

## 2. Architecture Assessment

**Strengths**

- The `IValveDriver` abstraction decouples the runner from the HA client and is
  what makes the "mock the HA client" test rule possible.
- Crash recovery (`ActiveRun` + `recover_runs` + `reconcile_valves`) is the
  standout: per persisted run it applies a "zone duration as the bound" policy,
  then idempotently closes orphaned valves. Exactly right for ephemeral
  containers.
- The state machine (`_run_zones` / `_wait_zone`) covers every path
  (done/stop/pause/watchdog) and persists in-flight state before each `await`.
  The mutex is registered synchronously before the first `await`
  (`self._runs[id] = run`) — correct against asyncio races.
- Resilient `_safe_turn_off` (retry, never raises) keeps an HA blip from
  aborting the run before history is recorded.
- In-place config reload (`mutate_config_in_place`) preserves the object
  identity that scheduler jobs / listeners hold by reference.
- Naive-UTC storage convention centralized in `timeutil.py` and applied
  consistently.

**Concerns**

1. **Two writers for `RunHistory`** (runner + `LiterTracker`), arbitrated at the
   valve-*on* event via `is_managed`. Sound, but correctness rests entirely on
   that predicate. Documented; fragile, not a bug.
2. **Unbounded task fan-out** in `ha_client._dispatch` — one task spawned *per
   callback per `state_changed` event*.
3. **Reload "race"** between `any_running()` and the in-place mutation — see L-2;
   on inspection the path is `await`-free, so it is effectively atomic.

---

## 3. High

### H-1. `forward_header` auth trusts a client-supplied header by default
**Files:** `auth_rules.py:28-39`, `dependencies.py:66-70`, `api/ws.py:226-228`, `main.py:138-144`

`forward_header_ok` returns `True` as soon as the configured header is present,
**unless** `trusted_proxies` is non-empty (default `[]`). With
`auth.mode: forward_header` and no `trusted_proxies`, any client that can reach
the direct port can send `X-Forwarded-User: anyone` and is authenticated — a full
auth bypass, on both REST and the WebSocket handshake. A startup warning exists
but the runtime still fails open.

**Fix:** Fail closed — reject when `trusted_proxies` is empty in
`forward_header` mode.

### H-2. TypeScript strict mode is not enabled — `CLAUDE.md` violation
**Files:** `src/frontend/tsconfig.app.json`

`strict` (and `strictNullChecks` / `noImplicitAny`) appears in none of the
`tsconfig*.json` files; there is no base config supplying it. `CLAUDE.md`
explicitly requires "TypeScript: strict mode." Test files are additionally
excluded from the typecheck. The code is written *as if* strict (pervasive
`?.`/`??`), so enabling it is expected to be low-churn.

### H-3. Hardcoded display string bypasses i18n — `CLAUDE.md` violation
**File:** `src/frontend/src/App.tsx:120`

`title="Konfiguration"` is hardcoded German; every other route uses
`t('nav.*')`. Should be `t('nav.config')` with the key added to both locales.

---

## 4. Medium

### M-1. Hardcoded German strings in the backend (stats publisher)
**File:** `stats_publisher.py:161-186`

MQTT entity names are hardcoded German (`"Bewässerung gesamt"`,
`"Laufzeit gesamt"`, `"Bewässerung {zone.label}"`, …). These are user-visible in
Home Assistant but bypass i18n and ignore `config.language`: server-side
notifications honor the configured language, yet a user with `language: en` still
gets German HA sensors. `CLAUDE.md` requires English code / i18n-managed UI
strings.

### M-2. Dead code in the drivers layer
**Files:** `drivers/ha_driver.py:23-78`, `drivers/protocol.py:8-25`

`HAEntitySensorSource`, `ISensorSource`, `SensorReading`, and
`HAEntityDriver.subscribe_state` are never instantiated/called (verified). The
runner only uses `turn_on`/`turn_off`; `subscribe_state` on the `IValveDriver`
protocol is pure ballast.

### M-3. Frontend file-size / duplication hotspots
- `pages/Config.tsx` is **1202 lines**, mixing the page with ~15 component
  definitions (`EntityCombobox`, `SequenceEditor`, `SchedulePicker`, plus layout
  primitives near-duplicated from `Settings.tsx`).
- `components/TodayBlock.tsx` (461 lines) has three parallel run-row render paths
  (`TodayBlock` / `DenseTodayBlock` / `RunRow`).
- Query-key strings are repeated magic literals (`['sequences']` ×12,
  `['status']` ×9, …); a typo in `invalidateQueries` silently fails to refresh.
- `getConfig` is fetched inside leaf components (per History row) only for color
  resolution.

---

## 5. Low

- **L-1. Unbounded task fan-out per `state_changed` event** (`ha_client.py:175`):
  one task per registered callback per event (subscribers × every entity change).
- **L-2. Config-reload atomicity** (`api/config.py:177` → `apply_reloaded_config`):
  the `any_running()` guard and the in-place mutation are not lock-guarded, but
  the path between them is `await`-free, so no scheduler job can interleave on the
  single-threaded event loop — effectively atomic. Worth a clarifying note/guard.
- **L-3. Auth token in `localStorage`** (`api/client.ts`, `hooks/useWebSocket.ts`)
  — XSS-exfiltratable; documented trade-off, no stored-XSS sink found.
- **L-4. `last_used_at` write on every authenticated request**
  (`dependencies.py:84-86`, `api/ws.py:149`) — a DB commit per call.
- **L-5. DRY: `master_on` preference read reimplemented 3×** (`scheduler.py:37`,
  `system.py:37`, `api/sequences.py:32`).
- **L-6. Repeated `datetime.fromisoformat(...)` try/except** across
  `ha_driver.py`, `system.py`, `tracking.py`.
- **L-7. Frontend hardcoded color literals** — `var(--n-danger, #ff6464)` hex
  fallback (`History.tsx:241`) and ~25 `rgba(...)` glow/overlay literals that
  duplicate token colors; plus a11y gaps (combobox lacks `role`/`aria-*`,
  icon-only buttons rely on `title` not `aria-label`) and unhandled query errors.

---

## 6. Recommended priorities

1. Close the auth fail-open (H-1).
2. Enable TS strict mode (H-2) + localize the hardcoded title (H-3).
3. Backend hardcoded German → English (M-1).
4. Remove dead driver code (M-2).
5. Hardening: bound the `state_changed` fan-out (L-1), reload-atomicity note
   (L-2); larger refactors (Config.tsx split, query-key centralization,
   TodayBlock dedupe) as follow-ups.

---

## 7. Work log (this branch)

Verified after every change: backend `ruff check` ✅ · `ruff format` ✅ ·
`mypy naiad` ✅ · `pytest` **242 passed** ✅ (was 241, +1 new auth test); frontend
`tsc -b` (strict) ✅ · `eslint` ✅ · `vitest` **36 passed** ✅.

### Done

- **[H-1] ✅ Auth now fails closed in `forward_header` mode.** `forward_header_ok`
  returns `False` when `trusted_proxies` is empty (was `True`), so a spoofable
  client header is no longer trusted on the direct port — covers both REST
  (`dependencies.py`) and the WebSocket handshake (`api/ws.py`) since both call
  the same predicate. Startup warning reworded to say requests are rejected.
  Tests updated/added in `tests/test_auth_rules.py`.
  Files: `auth_rules.py:28-40`, `main.py:138-145`, `tests/test_auth_rules.py`.
- **[H-2] ✅ TypeScript strict mode enabled.** Added `"strict": true` to
  `tsconfig.app.json` and `tsconfig.node.json`; `tsc -b --force` passes with zero
  changes needed elsewhere (the code was already written as-if-strict).
- **[H-3] ✅ Hardcoded title localized.** `App.tsx:120` now uses `t('nav.config')`;
  added `nav.config` to `en.json` ("Configuration") and `de.json` ("Konfiguration").
- **[M-1] ✅ Backend German strings removed.** `stats_publisher._entity_specs`
  MQTT sensor names are now English ("Water total", "Runtime total",
  "Water {label}", …).
- **[M-2] ✅ Dead driver code removed.** Deleted `HAEntitySensorSource`,
  `ISensorSource`, `SensorReading`, and the unused `subscribe_state` from both the
  `IValveDriver` protocol and `HAEntityDriver`. `drivers/` is now just the
  valve on/off surface the runner actually uses.
- **[L-1] ✅ `state_changed` fan-out bounded.** `_dispatch` now spawns one task
  per event (`_run_callbacks`, which `gather`s the callbacks concurrently and logs
  individual failures) instead of one task per callback per event.
- **[L-2] ✅ Config-reload atomicity.** `replace_configuration` is `await`-free
  between the `any_running()` guard and the in-place swap (documented with a
  comment so it stays that way). `import_configuration` *does* `await
  request.body()` after the first guard, so a second `any_running()` re-check was
  added right before the swap to close that window.

### Deferred (recommended follow-ups, not done in this pass)

These are larger refactors or lower-risk items left for a dedicated change so they
can be verified by running the app:

- **[M-3] Frontend size/duplication:** split `Config.tsx` (1202 lines), extract
  `EntityCombobox`, centralize React Query keys into a `queryKeys` module, dedupe
  `TodayBlock` render paths. Mechanical but high-churn; better isolated.
- **[L-3] Token in `localStorage`**, **[L-4] `last_used_at` write per request**,
  **[L-5] `master_on` DRY helper**, **[L-6] `fromisoformat` helper**, **[L-7]
  frontend color literals / a11y / query-error UI** — minor; batch into a cleanup PR.
</content>
