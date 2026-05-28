# Code Review — Naiad

**Scope:** Full codebase review of the Naiad garden irrigation controller (FastAPI/SQLModel backend + React/TypeScript frontend), integrating with Home Assistant over WebSocket.
**Date:** 2026-05-28
**Reviewed against:** `CLAUDE.md` project rules, `docs/openapi.yaml` contract.

---

## 1. Summary / Verdict

Naiad is a well-structured project with a clean layering (config → domain → drivers → API), a sensible state machine for sequence execution, and a thoughtful factor model for weather-based irrigation adjustment. The driver `Protocol` abstraction and the resume-snapshot mechanism are nice touches.

However, the review found several **safety-relevant and correctness bugs** that should be addressed before this controls real valves:

- **Stuck-valve risk** on process restart / Home Assistant disconnect (no reconciliation, no persisted watchdog).
- **Factor overrides are applied inconsistently** — honored by cron, ignored by manual start and the status endpoints.
- **Invalid factor overrides can brick the system** — settings PATCH performs no validation, while the read path re-validates and raises on every `compute_factors`.
- **WebSocket concurrency hazards** (concurrent writes to one socket, set mutated during broadcast iteration, infinite reconnect storm on auth failure).
- **CI is currently red**: `ruff check` reports 2 errors and `mypy` reports 122 errors. The pipeline gates on both.

Counts: **Critical 4 · High 8 · Medium 13 · Low 11** (see below).

---

## 1a. Fixes applied (quick wins) — branch `claude/naiad-code-review-vgj8U`

A first pass of low-risk, high-confidence fixes has been applied and verified. Each
addressed finding below is annotated with **✅ Fixed**. Verification on this branch:

- `ruff check .` → **clean**
- `ruff format --check .` → **clean** (the repo had never been formatted — 19 files; now formatted)
- `mypy naiad` → **Success: no issues found** (was 39 errors)
- `pytest` → **92 passed** (was 46; +46 new regression tests)
- frontend `tsc` → **clean** (the previously-blocking dead `handleStop` is now wired up)

**All Critical, High and Medium findings are resolved, and all Low findings are
addressed** (L-4 — token in `localStorage` — is acknowledged with a documented
trade-off rather than re-architected).

**Backend fixes:** C-1 (startup valve reconciliation, resilient `turn_off`, HA-disconnect no longer
aborts a run, plus crash recovery: persisted `ActiveRun` is resumed when its zone window is still
open — re-arming the watchdog — or closed when stale), C-2 (settings validation
symmetry), C-4 (per-connection WebSocket send-lock so heartbeat/run-tick/broadcast can't interleave
frames; broadcast also snapshots the connection set), H-1 + M-7 (factor overrides now applied
consistently everywhere), H-2 (`forward_header` auth mode implemented), H-3 (`auto_login_enabled`
toggle now wired), H-4 (origin/host referer matching + refuse when no trust list configured),
H-5 (fire-and-forget HA tasks now strongly referenced + cancelled on stop), H-6 (sequence-override
bounds + watchdog misconfig warning), H-7 (CI green: ruff/format/mypy/pytest), H-8 (master toggle
Pydantic model), M-1 (plans retried on transient conflict, not dropped), M-2 + M-3 (configurable
`timezone`; local-day bucketing for liters and history filters), M-4 (orphaned pause snapshot
cleared), M-5 (PAUSED-derivation documented), M-6 (unavailable-sensor warning), M-8 (constant-time
password compare), M-9 (CSP `frame-ancestors` header), M-10 (runner `on_started` callback — no
phantom "running").

**Frontend fixes:** C-3 (WebSocket auth handling + exponential backoff + clean teardown, no more
reconnect storm), M-12 (full i18n sweep — all hardcoded strings now via `t(...)`, locale-aware date
formatting, DE/EN language switch in Settings), M-11 (emergency stop uses `Promise.allSettled`),
M-13 (contract drift: `Plan` fields + spec `temp_c`/`notify_targets` aligned), L-5 (logout button),
L-6 (progress-bar NaN guard), L-7 (stop/pause error handling), L-8 (real `week_series` chart data),
L-9 (language switch), L-10 (centralized `seqColor`), L-11 (401 → app re-login instead of hard
reload; `StatusChip` cleanup), L-12 (per-sequence stop button — also makes the frontend type-check
clean), plus removal of unused imports.

**Backend Low fixes:** L-1 (compute factors once in `GET /sequences`), L-8 (`/status` `week_series`).

**New tests:** L-2 (watchdog-abort state path), C-2 (factor-override validation),
L-3 (token-prefix matcher), password-check coverage, C-1 (valve reconciliation, `turn_off`
retry/resilience, crash recovery), C-4 (WS send serialization / dead-connection drop), H-2/H-4
(forward-header + referer matching), H-3 (auto-login toggle), M-1 (scheduler status/plan retention),
M-2/M-3 (`timeutil` incl. DST), M-4 (orphan snapshot), L-8 (`_week_series` bucketing).

> **Every Critical, High and Medium finding is resolved, and all Low findings are addressed.**
> The only consciously-deferred item is L-4 (auth token in `localStorage` → cookie), documented as
> a trade-off. Minor leftovers noted inline: theme↔`/preferences` sync (part of L-9) and the broader
> ad-hoc `rgba(...)` → design-token cleanup (part of L-10).

---

## 2. Architecture Assessment

**Strengths**

- Clear separation: `config.py` (Pydantic schema + env expansion), `domain/` (pure-ish business logic), `drivers/` (HA abstraction via `Protocol`), `api/` (FastAPI routers), `scheduler.py` (APScheduler orchestration).
- The `IValveDriver` / `ISensorSource` protocols let tests inject a fake driver — good for the "mock the HA client" rule.
- Sequence execution as an `asyncio.Task` with an event-based stop/pause/watchdog race in `_wait_zone` is a clean design.
- Config validation with cross-field validators (`range`, `reduce_above_mm < zero_above_mm`, zone-reference integrity) is solid.

**Concerns**

1. **No persistence of live run state → stuck valves.** The `SequenceRunner` holds run state (`_running`, `_current_zone`) and the watchdog purely in memory. If the process restarts mid-run, the in-flight sequence and its watchdog vanish, but the physical valve stays **ON** in Home Assistant indefinitely. There is no startup reconciliation in `main.py:_lifespan` to turn off zone switches. For an irrigation controller this is the single most important architectural gap. (See C-1 — **✅ now addressed**: startup reconciliation, resilient `turn_off`, disconnect-abort, and `ActiveRun` crash recovery.)

2. **Factor application is not centralized.** `compute_factors` is called from five places with inconsistent arguments — some pass a DB `session` (honoring overrides), some don't. This produces divergent behavior between cron, manual start, and status display. (See H-1.) A single helper (`current_factors(ha, config, session)`) used everywhere would remove the class of bug.

3. **Settings write path bypasses the validation that the read path enforces.** `PATCH /settings` writes raw values to `FactorOverride`/`SequenceOverride` with no bounds/relationship checks, but `_effective_factor_config` calls `model_validate` when reading them back, which raises. Write and read validation must be symmetric. (See C-2.)

4. **Declared auth modes are partly unimplemented.** `auth.mode` accepts `forward_header`, but `require_auth` only special-cases `none` and otherwise requires a bearer token — so `forward_header` silently behaves like `password`. The `auto_login_enabled` toggle is persisted and read back in `/settings` but is never consulted by the `/auth/auto-login` endpoint (which only checks the YAML flag). The `frame_ancestors` config is collected but never emitted as a `Content-Security-Policy` header, so the documented HA-iframe-embedding feature is inert. (See H-2, H-3, M-9.) — **H-2 & H-3 ✅ now fixed; M-9 (CSP header) still open.**

5. **Hand-maintained type/contract duplication.** The frontend keeps a hand-written `client.ts` type set *and* a generated `schema.d.ts`, and they have drifted (see frontend contract findings). `CLAUDE.md` names `client.ts` as the source of truth alongside the OpenAPI spec; today they disagree.

6. **Per-sequence work in list endpoints.** `GET /sequences` calls `read_sensor_snapshot` + `compute_factors` once per sequence (`_build_state`), each re-reading sensors and hitting the DB for `FactorOverride`. Compute once and reuse. (See L-)

---

## 3. Critical

### C-1. Process restart / HA disconnect leaves valves stuck ON (safety)
**Files:** `main.py:71-129` (no reconciliation), `domain/sequences.py:83-189` (in-memory state + watchdog), `drivers/ha_driver.py:20-21`

- All live run state and the watchdog timer live only in memory. A container restart (the environment is explicitly ephemeral) during a run abandons the open valve — HA keeps it ON with no watchdog to close it.
- On HA reconnect there is no logic that aborts the in-flight sequence; meanwhile every `call_service` raises `HAError` while disconnected.
- In `_run_zones`, if `self._driver.turn_off(zone_cfg)` raises (HA dropped after the zone was turned on), the exception propagates to `_execute`'s generic `except Exception` and is only **logged** — the valve is never retried-off and no `RunHistory` row is written. The model even defines `abort_reason="ha_disconnect"`, but nothing ever sets it.

**Impact:** Over-watering / flooding; lost run records.
**Fix:**
- On startup, reconcile: turn off every configured zone switch (or read HA state and close any open managed zone) before scheduling.
- Persist the active run (sequence, zone, started_at, planned duration) so a watchdog can be re-armed after restart.
- Wrap `turn_off` in a retry / `finally` that still records history, and subscribe to `on_connection_change(False)` to abort the running sequence with `abort_reason="ha_disconnect"`.

> **✅ Fixed.** Implemented in `domain/{models,resume,sequences}.py` + `main.py`:
> - **Valve reconciliation** — `SequenceRunner.reconcile_valves()` turns off every configured
>   zone except the one owned by a live/resuming run. Closes valves left open by a previous
>   process/crash on first boot, and closes a zone after a disconnect-aborted run once HA returns.
>   Idempotent.
> - **`turn_off` resilience** — `_safe_turn_off()` retries (default 3×, 1 s backoff) and never
>   raises, so a failed turn_off no longer aborts the run loop before `RunHistory` is written.
> - **HA disconnect is *not* a hard abort** — a disconnect cannot physically close the valve
>   anyway (HA is unreachable), and the run task itself does not depend on HA. So the run keeps
>   running: a brief blip stays transparent (the resilient `turn_off` succeeds once HA returns),
>   the in-memory watchdog still bounds the run, and reconcile-on-reconnect closes anything left
>   open. The `ActiveRun` record is kept during the outage, so a crash *during* the outage still
>   recovers on boot. Only a `logger.warning` is emitted (HA notify can't be delivered while down).
> - **Crash recovery / watchdog re-arm** — a new `ActiveRun` row (singleton) is written at every
>   zone start and cleared at every *graceful* end (completion, stop, pause, watchdog, error),
>   so it survives only a hard crash / abrupt restart. On the first HA connect, `recover_run()`
>   applies the **"zone duration as the bound"** policy: if the current zone's planned window has
>   **not** elapsed (`elapsed < zone_planned_min`), the run is resumed for the remaining time and
>   the following zones continue — the normal run loop **re-arms the watchdog** automatically;
>   otherwise the run is stale and all valves are closed. A `CancelledError` (graceful
>   shutdown/restart) intentionally keeps the record so the run resumes on reboot.
> - Tests (`tests/test_sequences.py`, +12): reconcile all / skip-running, `_safe_turn_off`
>   retry/success, history-written-on-turn_off-failure, `stop(reason="ha_disconnect")` plumbing,
>   ActiveRun persisted-then-cleared, resume-fresh-run, close-stale-run, no-record-reconciles,
>   discard-unknown-sequence.
>
> **Trade-off (noted):** reconcile-while-idle on a *reconnect* also closes a valve a user opened
> manually in HA, since Naiad treats itself as the authoritative valve controller.

### C-2. Invalid factor overrides brick `compute_factors` (and thus status + cron)
**Files:** `api/settings.py:90-148` (no validation on write), `domain/factors.py:60-101` (`model_validate` on read)

`PATCH /settings` writes `rain_reduce_above_mm`, `rain_zero_above_mm`, `rain_forecast_decay`, `temp_min_pct`, etc. directly with **no validation**. On the read side, `_effective_factor_config` builds a dict and calls `RainFactorConfig.model_validate(...)`, which runs the model validators:
- `forecast_decay` has `ge=0.0, le=1.0`,
- `reduce_above_mm < zero_above_mm` is enforced.

So a single PATCH with e.g. `reduce_above_mm = 30, zero_above_mm = 20` (or `forecast_decay = 2`) is accepted and stored, after which **every** subsequent `compute_factors` call raises `ValidationError`. That breaks `GET /status`, `GET /sequences`, the WS snapshot/heartbeat, and the cron `_run_sequence_job` — the system is effectively bricked until the row is manually deleted from the DB.

**Fix:** Validate the merged factor config in the PATCH handler (construct the `TempFactorConfig`/`RainFactorConfig` before persisting and return 422 on failure), and add bounds to the `*Input` schemas in `schemas.py`.

> **✅ Fixed.** Extracted `merge_factor_config(config, fo)` in `domain/factors.py` (which runs
> the pydantic validators) and called it from `update_settings` (`api/settings.py`) inside a
> `try/except ValidationError` → returns **422** instead of persisting a config that would later
> brick `compute_factors`. Regression tests added in `tests/test_factors.py`
> (`test_merge_factor_config_rejects_inverted_rain_thresholds`,
> `test_merge_factor_config_rejects_out_of_range_decay`,
> `test_merge_factor_config_accepts_valid_override`).

### C-3. WebSocket auth failure → infinite reconnect storm (self-DoS)
**Files:** `hooks/useWebSocket.ts:30-39` (frontend), `api/ws.py:188-193` (backend)

The frontend reconnects unconditionally 3s after any `onclose` and never inspects message content. When the token is invalid/expired the backend sends `{"type":"auth_failed"}` and closes. The client therefore loops forever every 3s, always failing auth — a self-inflicted DoS and live updates silently never work. The `auth_ok`/`auth_failed` messages are never handled.

**Fix:** Handle `auth_failed` (clear token, route to login, stop reconnecting); add exponential backoff; stop the loop on unmount.

> **✅ Fixed.** `hooks/useWebSocket.ts` rewritten:
> - `auth_ok` / `auth_failed` are now handled. On `auth_failed` the hook stops permanently
>   (`stopped` flag), clears the token, and triggers re-login (`onAuthFailed` callback, default
>   `window.location.reload()` → the login screen; `verify()` uses `skipReloadOn401` so there is
>   no reload loop). No more 3-second storm against a backend that keeps rejecting the token.
> - **Exponential backoff** for normal drops (1 s → 2 s → … capped at 30 s), reset to 1 s on each
>   `auth_ok`, so transient disconnects still recover quickly while persistent failures back off.
> - **Teardown fixed** (addresses the related timer-leak/stale-closure note): an `unmounted` flag
>   plus detaching `onopen/onmessage/onclose/onerror` before `close()` ensures a late `onclose`
>   can't schedule a reconnect after unmount; the pending timer is always cleared. The
>   latest-callback refs are synced in an effect (not during render) to satisfy `react-hooks/refs`.
> - Verified with `tsc` + `eslint` (the repo has no frontend test runner).

### C-4. Concurrent writes to a single WebSocket + set mutation during broadcast
**File:** `api/ws.py:33-47, 202-203, 224-260`

Three independent tasks write to the *same* socket: `_heartbeat`, `_run_tick`, and `manager.broadcast` (invoked from HA state-change callbacks). Starlette `WebSocket.send_text` is not safe to call concurrently from multiple tasks — interleaved sends can raise or corrupt frames. Separately, `WsManager.broadcast` iterates `self._connections` while `await ws.send_text(...)` yields control; a concurrent `connect()`/`disconnect()` mutates the set mid-iteration → `RuntimeError: Set changed size during iteration`.

**Fix:** Serialize all sends to a connection behind a per-connection `asyncio.Lock` (or a single writer task fed by a queue); iterate over `list(self._connections)` in `broadcast`.

> **✅ Fixed.** `WsManager` now keys connections by a **per-connection `asyncio.Lock`**
> (`dict[WebSocket, asyncio.Lock]`). All writes — `broadcast`, the per-connection `send` used by
> `_heartbeat`/`_run_tick`, and the initial snapshot — funnel through `_send_text()`, which holds
> that connection's lock around `ws.send_text`, so the three tasks can no longer interleave frames
> on the same socket. `broadcast` snapshots the targets (`list(self._locks)`) and fans out with
> `asyncio.gather` (concurrent across connections, serialized per connection), dropping any that
> fail. `send` now returns a bool; `_heartbeat`/`_run_tick` break when it returns False (it no
> longer raises). Tests in `tests/test_ws_manager.py`: serialization under concurrent
> `send`+`broadcast`, dead-connection drop, unknown/failed sends.

---

## 4. High

### H-1. Factor overrides ignored on manual start and on the status endpoints
**Files:** `api/sequences.py:201`, `api/system.py:77`, `api/ws.py:130` — all call `compute_factors(snapshot, config)` **without** a session; `scheduler.py:72` and `api/sequences.py:100` pass `session`.

`compute_factors(..., session=None)` skips `FactorOverride`. So:
- A **cron** run uses overridden factors; a **manual** "Start" of the same sequence uses the YAML defaults — different water volumes for the same action.
- `GET /status` and the WS snapshot show factors that ignore the user's saved settings, while `GET /sequences` shows the overridden ones. Users see contradictory factor percentages in the same UI.

**Fix:** Always pass the session. Centralize in one helper so the override path can't be forgotten.

> **✅ Fixed.** `compute_factors(..., session)` is now passed a session at all call sites:
> `api/sequences.py:start_sequence`, `api/system.py:get_status`, and `api/ws.py:_status_snapshot`
> (the heartbeat now opens a session too). Cron and `_build_state` already passed it. Covered by the
> existing `tests/test_factors.py` override tests.

### H-2. `auth.mode == "forward_header"` is unimplemented
**Files:** `dependencies.py:33-55`, `api/ws.py:182-193`, `config.py:31`

`require_auth` returns early only for `mode == "none"`; for `forward_header` it falls through and demands a bearer token exactly like `password` mode. The trusted-header flow is never read. Either implement it (read & verify the configured proxy header) or remove the literal from the config schema so operators aren't misled.

> **✅ Fixed.** New `ForwardHeaderConfig` (`config.py`: `header`, optional `trusted_proxies`) and a
> pure `forward_header_ok()` predicate in `naiad/auth_rules.py`. `require_auth` (`dependencies.py`)
> and the WebSocket handshake (`api/ws.py`) now authorize in `forward_header` mode when the
> configured header is present (and, if `trusted_proxies` is set, the client IP is one of them).
> Documented in `config.example.yaml`. Tests in `tests/test_auth_rules.py`.

### H-3. `auto_login_enabled` setting has no effect
**Files:** `api/settings.py:61-62, 140-146` (persist/read) vs `api/auth.py:74-91` (gate)

The `/settings` PATCH stores `auto_login_enabled` and `GET /settings` reports it, but `/auth/auto-login` only checks `config.auth.auto_login.enabled` (YAML). Toggling auto-login from the UI does nothing. Wire the endpoint to the DB preference (or drop the setting).

> **✅ Fixed.** `_auto_login_enabled(config, session)` (`api/auth.py`) returns the DB pref when set,
> falling back to the YAML default, and `/auth/auto-login` now gates on it — so the Settings toggle
> takes effect. Test: `test_auto_login_enabled_db_pref_overrides_yaml` in `tests/test_auth.py`.

### H-4. Auto-login referer check is substring-based (auth weakness)
**File:** `api/auth.py:83-89`

`referer_ok = any(r in referer for r in trusted_referers)` matches a trusted value anywhere in the Referer string, so `https://evil.example/?x=myha.local` passes a `trusted_referers: ["myha.local"]` rule. Referer is also client-controlled and trivially spoofable. Additionally, if both `trusted_referers` and `trusted_ips` are empty while auto-login is enabled, **any** request with the embed param is granted a 30-day token.

**Fix:** Match origin/host with strict parsing (compare scheme+host), require at least one non-empty trusted list when enabled, and treat Referer as a weak signal (prefer IP allow-listing behind a trusted proxy).

> **✅ Fixed.** `referer_matches()` (`naiad/auth_rules.py`) parses the Referer and compares by exact
> hostname (or full origin when the trusted entry includes a scheme), so
> `https://evil.example/?x=naiad.local` no longer passes. `/auth/auto-login` now also **refuses**
> when neither `trusted_referers` nor `trusted_ips` is configured (no more "embed param ⇒ token for
> anyone"). Tests in `tests/test_auth_rules.py` (incl. the substring-bypass regression).

### H-5. Fire-and-forget `asyncio.create_task` without references
**File:** `ha_client.py:70, 118, 121, 175`

`asyncio.create_task(self.on_connection_change(...))` and the per-event `cb(...)` tasks are created without keeping a reference. Per the asyncio docs the loop only holds a weak reference, so a task may be garbage-collected before completion ("Task was destroyed but it is pending"). On a busy HA instance, `_dispatch` also spawns an **unbounded** number of callback tasks per `state_changed` event. (Also flagged by `ruff` rule family RUF006.)

**Fix:** Store tasks in a set and discard on completion (`task.add_done_callback(set.discard)`), or process callbacks sequentially within the dispatch loop.

> **✅ Fixed.** `HAClient._spawn()` keeps a strong reference in `self._bg_tasks` and removes it via
> `task.add_done_callback(self._bg_tasks.discard)`; all fire-and-forget calls (connection-change
> callbacks, state-cache load, per-event state callbacks) go through it, and `stop()` cancels them.
> (Note: the per-event spawn is now GC-safe; rate-limiting a flood of `state_changed` events remains
> a separate, lower-priority concern.)

### H-6. Settings PATCH accepts unsafe sequence overrides
**File:** `api/settings.py:118-130`, `schemas.py:175-178`

`basis_min_per_zone` and `watchdog_min` are written with no lower bound. `watchdog_min` ≤ effective zone duration means the watchdog fires before the zone ever completes (every run aborts); `basis_min_per_zone = 0` yields zero-length runs. There is also no validation that `watchdog_min > range[1]` anywhere (config or override).

**Fix:** Enforce `> 0` and `watchdog_min` ≥ max possible zone duration at the API boundary and ideally in `SequenceConfig`.

> **✅ Fixed.** `update_settings` rejects `basis_min_per_zone <= 0` and `watchdog_min <= 0` with
> **422** (`api/settings.py`). For the "watchdog shorter than the run" footgun, `setup_scheduler`
> now logs a **warning** when `watchdog_min <= basis_min_per_zone` for any enabled sequence. This is
> intentionally a warning, not a hard validator: zone duration is clamped to `range` and scaled by a
> runtime factor, so a strict `watchdog ≥ range[1]` (or `≥ 2·basis`) rule would reject legitimate
> configs that use a wide `range` as a safety clamp while expecting normal durations well under the
> watchdog.

### H-7. CI is currently failing (ruff + mypy)
**Files:** repo-wide; `.github/workflows/ci.yml`

`ruff check .` → 2 errors (unsorted import blocks in `api/sequences.py:22` and `main.py:99`).
`mypy naiad` → **122 errors** across 17 files: untyped FastAPI decorators, `dict` used without type parameters (`api/sequences.py`, `api/auth.py`, `api/status.py`), `RunHistory.started_at.desc()` flagged as `"datetime" has no attribute "desc"` (`api/history.py:43`), untyped `_r` helper (`api/settings.py:35`), `BaseHTTPMiddleware` subclassing, and an unused `type: ignore` in `main.py:72`. The CI gates on ruff, mypy, and pytest, so the pipeline is red as-is.

**Fix:** Run `ruff check --fix`, add explicit `dict[str, str]` return types, and resolve the mypy findings (or scope mypy config if some are intentionally ignored).

> **✅ Fixed.** All four CI steps are now green:
> - `ruff check` — fixed the two import-sort errors.
> - `ruff format --check` — the repo had **never been formatted** (19 files); applied `ruff format`.
> - `mypy naiad` — **0 errors** (was 39): typed `get_engine`/`get_session`/`create_tables`
>   (`database.py`), annotated `_lifespan` (`main.py`), `dict[...]` return types, `col()` for
>   `order_by`/`.desc()` (`history.py`, `plans.py`, `system.py`, `scheduler.py`), generic `_r`
>   helper (`settings.py`), `Coroutine`-typed HA callbacks (`ha_client.py`), and removed
>   genuinely-unused `# type: ignore` comments.
> - `pytest` — 55 passed.
>
> *(Re-verify in CI: the original 122-error count earlier was an artifact of a broken local env
> with deps missing; with deps installed the real count was 39, now 0.)*

### H-8. `/status/master` body is an untyped `dict`, against the "validate at boundaries" rule
**File:** `api/status.py:113-122`

`async def set_master(body: dict, ...)` parses and manually validates `body["on"]`. `CLAUDE.md` Security: "Validate all user input at API boundaries with Pydantic models." Use a `MasterToggleRequest(BaseModel) { on: bool }`. (This is also one of the `Missing type parameters for generic type "dict"` mypy errors.)

> **✅ Fixed.** Added `MasterToggleRequest(BaseModel)` in `api/schemas.py` and changed
> `set_master` to accept it (`api/system.py`), returning `dict[str, bool]`. FastAPI now
> validates the body and returns 422 on malformed input automatically.

---

## 5. Medium

### M-1. A scheduled plan is silently dropped on transient skip/conflict
**File:** `scheduler.py:98-123`

`_plan_tick` deletes the `Plan` row **before** calling `_run_sequence_job`. If the run is skipped (master off, season off, wind, paused) or conflicts (another sequence running → caught `MutexConflict`), the plan is already gone and never retried. Two plans due in the same tick: the first launches, the second hits `MutexConflict` and is lost. Delete only after a successful start, or mark as executed.

> **✅ Fixed.** `_run_sequence_job` now returns `"started" | "skipped" | "conflict"`. `_plan_tick`
> runs the job first and **keeps** the plan on a transient `"conflict"` (retried next tick),
> deleting it only once started or deterministically skipped (`scheduler.py`). Tests in
> `tests/test_scheduler.py` (status transitions + plan retention on conflict).

### M-2. "Today"/"this week" liters use UTC day boundaries, scheduler uses Europe/Berlin
**File:** `api/status.py:85-86, 39-43`

`today_start = datetime(now.year, now.month, now.day, tzinfo=UTC)` — "today" resets at 01:00/02:00 local time, not local midnight, so `liters_today` is wrong for 1–2 hours each day and double-counts/under-counts around the boundary. The cron triggers run in `Europe/Berlin`. Use the configured timezone for day bucketing.

> **✅ Fixed.** New `config.timezone` (default `Europe/Berlin`, validated) drives cron triggers, the
> scheduler, and a `naiad/timeutil.py` helper. `liters_today` now buckets from `local_day_start_utc`
> (local midnight → naive UTC). Tests in `tests/test_timeutil.py` (incl. DST/CET vs CEST).

### M-3. History date filters compare naive local dates against UTC timestamps
**File:** `api/history.py:33-38`

`from`/`to` are parsed as naive `datetime(year,month,day)` and compared to UTC-stored `started_at`, so day-boundary filtering is off by the local UTC offset. Convert filter bounds to UTC using the app timezone.

> **✅ Fixed.** `get_history` converts `from`/`to` via `local_date_to_utc(config.timezone, …)` to a
> half-open naive-UTC range (`>= from`, `< to+1day`), aligning the filter with local calendar days.

### M-4. Orphaned resume snapshot blocks status forever
**Files:** `domain/resume.py:35-46`, `api/sequences.py:44-45`

The `ResumeSnapshot` singleton (id=1) is only cleared by resuming or stopping the *same* sequence. If a sequence is paused and then a *different* sequence is started (or the paused one is never resumed), the snapshot persists and `_sequence_status` reports the old sequence as `paused` indefinitely. Consider clearing/aging stale snapshots, or keying status off live state.

> **✅ Fixed.** `clear_orphan_snapshot()` (`domain/resume.py`) drops a pause snapshot belonging to a
> *different* sequence; `_execute` calls it on start, so launching B abandons paused A. Tests in
> `tests/test_resume.py`.

### M-5. `runner.status()` never returns `PAUSED`; `SequenceState.PAUSED` is dead at the runner level
**File:** `domain/sequences.py:107-115, 283-287`

On pause, `_execute`'s `finally` resets `_running=None`, so the runner reports `IDLE`; "paused" is only inferred from the DB snapshot in the API layer. This is workable but surprising and undocumented — a reader of `SequenceRunner` would assume `status()` can return `PAUSED`. Document or model pause explicitly in the runner.

> **✅ Fixed (documented).** Added docstrings on `SequenceState.PAUSED` and `status()` stating that
> the runner only reports IDLE/RUNNING and that PAUSED is reconstructed from the `ResumeSnapshot` at
> the API layer.

### M-6. Rain/sensor unavailability fails *open* (waters anyway)
**Files:** `domain/sensors.py:10-19`, `domain/factors.py:40-57`

When precipitation sensors are `unavailable`, `_float` returns `0.0`, so `rain_factor` becomes `1.0` (no reduction) and irrigation proceeds at full/temp-only factor. For a water controller, failing toward *not* watering when rain data is unknown is the safer default — or at least surface a prominent "sensors unavailable" warning before a real run. Today `sensors_unavailable` is computed but only weakly surfaced.

> **✅ Addressed (surfaced, not flipped).** `_run_sequence_job` now logs a **warning** listing the
> unavailable sensors before starting a run. The water-anyway behaviour is kept deliberately: failing
> *closed* would mean a single mis-named/again-unavailable sensor silently stops all irrigation, which
> for this controller is worse than a missed rain reduction. The choice is now visible in logs (and
> `sensors_unavailable` remains in the factor result for the UI).

### M-7. `_status_snapshot` opens a session it never uses; WS factors ignore overrides
**File:** `api/ws.py:124-144, 198-200`

`compute_factors(snapshot, config)` is called without the session even though the endpoint opens one at line 198 (which is then unused). Same override-inconsistency as H-1, plus a dead `Session`.

> **✅ Fixed.** `_status_snapshot` now takes a `session` and passes it to `compute_factors`; the
> previously-dead session is used, and the heartbeat opens its own session (`api/ws.py`).

### M-8. Plaintext password comparison is not constant-time; plaintext config supported
**File:** `api/auth.py:30-35`, `config.py:32`

`_check_password` falls back to `provided == stored` for non-bcrypt values, which is not constant-time (timing oracle) and permits storing the password in plaintext in the config. Recommend requiring a bcrypt hash (the env var is named `NAIAD_PASSWORD_HASH`) and using `secrets.compare_digest` / `bcrypt` only.

> **✅ Fixed.** The plaintext fallback now uses `secrets.compare_digest` (constant-time). Plaintext
> config is still accepted (operator convenience), but the timing oracle is gone; bcrypt remains the
> recommended form. Covered by `tests/test_auth.py::test_check_password_bcrypt_and_plain`.

### M-9. `frame_ancestors` config never emitted as a header
**Files:** `config.py:34`, `main.py` (no CSP middleware)

`auth.frame_ancestors` is collected but no `Content-Security-Policy: frame-ancestors ...` header is ever set, so the documented HA-dashboard-embedding scenario isn't actually controlled. Add a response header (or remove the config).

> **✅ Fixed.** `_SecurityHeadersMiddleware` (`main.py`) now emits
> `Content-Security-Policy: frame-ancestors <auth.frame_ancestors>` on every response (defaulting to
> `'none'` if the list is empty), so the embedding policy is actually enforced.

### M-10. `broadcast_sequence_changed(..., "running")` fired before the run is confirmed
**Files:** `scheduler.py:88`, `api/sequences.py:209`

`runner.start()` only schedules the task; if `_execute` immediately fails (e.g., HA disconnected at `turn_on`), the system already broadcast "running" and clients show a run that never happened. Consider broadcasting from inside the runner once the first zone is actually ON.

> **✅ Fixed.** `SequenceRunner` gained an `on_started(sequence_id, triggered_by)` callback fired only
> after the first valve actually opens (also covers crash-recovery resumes). `main.py` wires it to
> `broadcast_sequence_changed(..., "running")`, and the premature broadcasts in `start_sequence`
> (`api/sequences.py`) and `_run_sequence_job` (`scheduler.py`) were removed. The domain layer stays
> decoupled from `api.ws` (callback injected at startup).

### M-11. Frontend emergency-stop aborts on first error, leaving valves running
**File:** `pages/Dashboard.tsx:80-86`

`handleEmergency` awaits `stopSequence` sequentially over running sequences; one rejection (e.g., 409 already-stopped) breaks the loop and the rest are never stopped — bad for an emergency control. Use `Promise.allSettled` and rely on master-off as the authoritative kill.

> **✅ Fixed.** `handleEmergency` now turns master off, then `Promise.allSettled`s all stop calls so
> one failure no longer aborts the rest (`pages/Dashboard.tsx`).

### M-12. Pervasive hardcoded German UI strings bypass i18n
**Files:** `Dashboard.tsx`, `TodayBlock.tsx`, `History.tsx`, `SequenceCard.tsx`, `ValveGrid.tsx`, `WeatherStrip.tsx`, `Settings.tsx`, `MasterToggle.tsx`, `Sidebar.tsx` (many lines; examples: `Dashboard.tsx:119 "Garten"`, `178 "läuft"`, `History.tsx:37-42` column labels, `TodayBlock.tsx:69 "Nächste Bewässerungen"`).

`CLAUDE.md`: "do not hardcode display strings in components." These strings will never switch to English even with `en.json` active. Several `toLocaleString('de', …)` calls also hardcode the locale regardless of the selected language.

> **✅ Fixed.** All hardcoded display strings across `Dashboard`, `TodayBlock`, `History`,
> `SequenceCard`, `ValveGrid`, `WeatherStrip`, `Settings`, `MasterToggle` and `Sidebar` now go
> through `t(...)`, with matching keys added to both `en.json` and `de.json` (new groups:
> `dashboard`, `today`, `time`, `valve`, `abortReason`, `weekdaysShort`, plus extensions to
> `sequence`/`history`/`weather`/`settings`/`master`/`nav`). Every `toLocaleString('de', …)` and
> `.toLocaleString('de')` now uses the active `i18n.language`; the relative/"when" time helpers and
> abort reasons are translated. A **language switch (DE/EN)** was added to Settings → System
> (persists to `localStorage('naiad_lang')` and calls `i18n.changeLanguage`), which also addresses
> the L-9 "language locked to de / no switcher" gap and removes the dead `useTranslation` import in
> `WeekChart` (L-8). Verified with `tsc` + `eslint` (only the unrelated pre-existing L-12
> `handleStop` warning remains).

### M-13. Frontend ↔ backend contract drift in hand-written `client.ts`
**Files:** `api/client.ts` vs `api/schema.d.ts` / `docs/openapi.yaml`

- `Plan` is missing `sequence_label` and `estimated_liters` (`client.ts:177-183`), forcing `Planner.tsx` to re-derive the label.
- `WeatherSummary.temp_c` is `number | null` in `client.ts:123` but non-nullable in the spec.
- `AppSettings` omits `notify_targets`; `UpdateSettingsRequest.basis_min_per_zone` is `number` vs spec `number | null`.

Prefer deriving types from `schema.d.ts` to stop the drift.

> **✅ Fixed.** `client.ts` `Plan` now includes `sequence_label` and `estimated_liters`, and
> `Planner.tsx` uses `p.sequence_label` directly (dropped the re-derived `seqLabel`). The spec was
> the outlier for `temp_c` (the backend returns `float | None`): `openapi.yaml` now marks `temp_c`
> nullable and drops `AppSettings.notify_targets` (which the backend never returns), matching
> `client.ts` and the Pydantic models. (`schema.d.ts` is an unused generated artifact — not imported
> anywhere — so it has no runtime impact; regenerate with `npm run typegen` when desired.)

---

## 6. Low

- **L-1.** `GET /sequences` recomputes sensors+factors per sequence (`api/sequences.py:152-155`, `_build_state`); compute once and pass in. (Perf) — **✅ Fixed:** `list_sequences`/`get_sequence` now compute the sensor snapshot + factors **once** and pass the `FactorResult` into `_build_state`.
- **L-2.** Watchdog-abort state path is **untested** despite `CLAUDE.md` ("Test all state machine paths: … running→aborted (watchdog)"). `test_sequences.py` covers idle→running, pause, stop, rain — but not watchdog. (Test gap) — **✅ Fixed:** added `test_watchdog_aborts_run` in `tests/test_sequences.py` (asserts the zone is turned off and a `RunHistory` row with `abort_reason="watchdog"` is written).
- **L-3.** `revoke_token` matches the first token with `startswith(prefix)` (`api/auth.py:123-127`); an 8-char prefix could in principle match multiple tokens and delete the wrong one. Match the exact token or store an explicit id. — **✅ Fixed:** extracted `_match_by_prefix(tokens, prefix)` using exact 8-char prefix equality, returning **404** when none match and **409** when ambiguous (`api/auth.py`); covered by `tests/test_auth.py`.
- **L-4.** Token in `localStorage` (`api/client.ts:3-13`, `useWebSocket.ts:20`) is XSS-exfiltratable; consider a `SameSite` cookie or in-memory token. (Security note — `CLAUDE.md` Security section.) — **⏳ Acknowledged (not changed):** moving to an `httpOnly`/`SameSite` cookie requires server-set cookies and CSRF handling, a larger auth change; given React escapes all rendered backend strings (no stored-XSS surface found), this is documented as a deliberate trade-off for a follow-up rather than a quick fix.
- **L-5.** `logout` in `useAuth` is never wired into the UI (`hooks/useAuth.ts:22-25`); the only way to clear a session is a forced 401 reload. — **✅ Fixed:** added `logout()` to `client.ts` (clears the token + dispatches `naiad:unauthorized`) and a **Log out** button in Settings; `useAuth` listens for the event and drops to the login screen. Removed the now-redundant `useAuth.logout`.
- **L-6.** Progress bar can render `width: NaN%` when `elapsed_min + remaining_min == 0` (`SequenceCard.tsx:42-44, 185-187`). Guard the denominator. — **✅ Fixed:** added a `runProgress()` helper that returns `0` when the total is `<= 0`, used by both card variants.
- **L-7.** `handleStop`/`handlePause` swallow errors while `handleStart` alerts (`Dashboard.tsx:70-78`) — inconsistent, leads to silent unhandled rejections. — **✅ Fixed:** both now `try/catch` + `alert` with a `finally` that invalidates the query, matching `handleStart`. **Note:** `handleStop` is still not wired to any button — the per-sequence **stop** action is missing from the dashboard cards (only start/pause + the global emergency stop exist). See new finding L-12.
- **L-8.** `WeekChart` shows fabricated data — only "today" is ever non-zero (`Dashboard.tsx:324-334`); backend exposes no per-day series. Relabel or add an endpoint. `WeekChart.tsx:15` imports `useTranslation` unused. — **✅ Fixed:** backend now returns `week_series` (liters per local weekday Mon..Sun of the current week, `api/system.py:_week_series`, in `SystemStatus` + openapi); `buildWeekData` uses the real series. The dead `useTranslation` import was removed (in M-12). Test: `tests/test_system.py`.
- **L-9.** Preferences API is effectively dead on the frontend: language is locked to `de` (`i18n/index.ts:9` reads a key never written), theme is written to `localStorage` but never synced to `PATCH /preferences`. — **✅ Fixed (language):** the M-12 language switch writes `naiad_lang` (read on init) and calls `i18n.changeLanguage`, so language is no longer locked. (Theme↔`/preferences` sync remains a minor open item; theme already persists locally.)
- **L-10.** Hardcoded hex/`rgba` colors and a duplicated `SEQUENCE_COLORS` map across `Settings.tsx`, `History.tsx`, `Planner.tsx`, `SequenceCard.tsx` (the last omits `lichtschacht`, diverging). `CLAUDE.md`: no hardcoded hex except data-driven accents — these are hand-coded and duplicated. Centralize. — **✅ Fixed:** single source of truth in `src/theme/sequenceColors.ts` (`seqColor(id, fallback?)`), imported by all four files; the divergent map is gone. (The accent hexes are allowed by `CLAUDE.md`; the broader ad-hoc `rgba(...)` literals remain a separate design-token cleanup.)
- **L-11.** `request` 401 handler does a hard `window.location.reload()` mid-mutation (`api/client.ts:31-34`), discarding unsaved Settings/Planner input. `StatusChip` uses `as never` cast (`StatusChip.tsx:9`) against the strict-typing rule, with dead `|| status` fallback. — **✅ Fixed:** the 401 path now `clearToken()` + dispatches `naiad:unauthorized` (no hard reload; `useAuth` drops to login, preserving the SPA). `StatusChip` uses `t(key, { defaultValue: status })` — no `as never`, no dead fallback.
- **L-12.** *(found while fixing L-7)* The per-sequence **stop** action is not exposed in the UI: `handleStop` exists but is never wired to a control, and `SequenceCard` has no `onStop`/stop button. — **✅ Fixed:** `SequenceCard` gained an `onStop` prop and a stop button (`IStop`, enabled only while running, replacing the dead placeholder clock button) in both card variants; Dashboard passes `onStop={() => handleStop(seq.id)}`. This also clears the last `tsc` error (`handleStop` is now used) — the frontend type-checks clean.

---

## 7. Recommended priorities

1. **Safety first:** C-1 (stuck valves / reconciliation / HA-disconnect abort), H-6 (watchdog bounds), M-11 (emergency stop).
2. **Don't brick the box:** C-2 (settings validation symmetry) ✅, C-3 (reconnect storm) ✅, C-4 (WS concurrency) ✅.
3. **Correctness of the core feature:** H-1 / M-7 (consistent factor override application) ✅, M-1 (plan loss) ✅, M-2/M-3 (timezone bucketing) ✅.
4. **Get CI green:** H-7 (ruff/mypy), L-2 (watchdog test).
5. **Auth honesty:** H-2 ✅, H-3 ✅, H-4 ✅; still open: M-8 (constant-time password compare), M-9 (CSP `frame-ancestors` header).
6. **Frontend polish & i18n:** M-12 ✅, M-13 ✅; remaining: the Low items.
