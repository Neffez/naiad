# Code Review — Naiad

**Scope:** Fresh full-codebase review of the Naiad garden irrigation controller
(FastAPI/SQLModel backend + React/TypeScript frontend), integrating with Home
Assistant over WebSocket.
**Date:** 2026-05-30
**Branch reviewed:** `claude/project-code-review-A3oX3` (at `de61ffb`)
**Reviewed against:** `CLAUDE.md` project rules, `docs/openapi.yaml` contract.

> This is an independent review of the code as it stands today. The previous
> review (and its "✅ Fixed" annotations) has been replaced — the items below were
> re-derived from the current source, and earlier findings that are genuinely
> resolved (startup valve reconciliation/crash recovery, WS per-connection send
> lock, factor-override symmetry, settings validation, CI import/format) are **not**
> re-reported. `ruff check` and `ruff format --check` were run locally and pass.
> `mypy`/`pytest` could not be executed here (the project requires Python 3.12; the
> review host only has 3.11), so the CI verdict on those two steps is unverified.

---

## 1. Summary / Verdict

Naiad is a well-structured codebase. The layering (config → domain → drivers →
API → scheduler) is clean, the `IValveDriver` abstraction makes the HA client
mockable, the sequence state machine is sound, and the recently-added crash
recovery / valve reconciliation closes the biggest historical safety gap. Most of
the timezone handling is now centralized in `timeutil.py`.

The remaining issues cluster in three areas:

- **Liter accounting is split-brained.** The `SequenceRunner` and the
  `LiterTracker` both write `RunHistory`, arbitrated by a live in-memory flag
  (`is_managed`). A state-event timing race makes the tracker double-count the
  **last zone of every managed run** as `external`, corrupting the core
  liters-today/week metric.
- **Auth fails open on misconfiguration.** `forward_header` mode trusts a
  client-supplied header when `trusted_proxies` is empty (the default), with no
  startup warning — anyone reaching the direct port can impersonate any user.
- **A few input boundaries and time conversions are incomplete** — `at_datetime`
  plans lose their timezone, manual-start/plan durations are unbounded, and the
  temperature-factor bounds aren't validated.

Counts: **High 2 · Medium 5 · Low 8.**

---

## 2. Architecture Assessment

**Strengths**

- Clear separation of concerns; `domain/` is mostly pure and unit-testable.
- Driver/sensor `Protocol` abstraction enables the "mock the HA client" test rule;
  the test suite (`tests/`, ~1.9k LOC) covers factors, the state machine
  (incl. watchdog/rain), resume, WS manager, auth rules and config round-trips.
- Config validation has real cross-field rules (`range`, `reduce_above_mm <
  zero_above_mm`, zone-reference integrity, timezone) and a "lockout guard" on the
  config PUT path.
- Crash recovery (`ActiveRun` + `recover_run` + `reconcile_valves`) is a thoughtful
  answer to the ephemeral-container / stuck-valve problem, with an explicit
  "zone duration as the bound" policy.
- Runtime config reload mutates a single shared `AppConfig` in place, preserving
  the object identity that the scheduler/runner hold by reference — neat.

**Concerns**

1. **Two writers for `RunHistory` arbitrated by volatile state.** The runner owns
   managed runs; the `LiterTracker` owns "external" valve activity, and the only
   thing keeping them from both recording the same watering is the live
   `runner.is_managed()` flag, which flips to `False` the instant a run ends. This
   is the root cause of **H-2** and is inherently racy. A durable handshake (e.g.
   the runner records its own off-events, or the tracker keys off a per-zone
   "managed until" timestamp) would remove the whole class of bug.

2. **Two different definitions of "this week."** `GET /status` returns
   `liters_week` as a **rolling 7-day** sum (`now − 7d`) but `week_series` as the
   **current calendar week** (Mon→Sun). The dashboard shows the rolling number
   above the calendar-week chart, so the headline never equals the sum of the bars
   (**M-2**).

3. **Auth defaults fail open.** `mode=none` warns loudly at startup, but
   `forward_header` with no `trusted_proxies` (the default) silently trusts a
   spoofable header (**H-1**), and there is no request throttling on `/auth/login`
   (**M-5**).

4. **Timezone handling is centralized except where it isn't.** `timeutil.py` is
   used for status/history bucketing, but `plans.py` builds `scheduled_at`
   independently and never normalizes to the storage convention (naive UTC), so
   `at_datetime` plans fire at the wrong wall-clock time (**M-1**).

5. **Input validation is asymmetric.** `PATCH /settings` now guards
   `basis_min_per_zone`/`watchdog_min > 0` and re-validates the merged factor
   config, but the manual-start and plan duration overrides are unbounded
   (**M-4**), and `TempFactorConfig` has no `min_pct < max_pct` validator
   (**M-3**), so a nonsensical temp config is accepted and silently pins the
   factor.

---

## 3. High

### H-1. `forward_header` auth trusts a client-supplied header by default
**Files:** `auth_rules.py:28-39`, `config.py:33-39`, `dependencies.py:61-65`, `api/ws.py:226-228`

`forward_header_ok` returns `True` as soon as the configured header is present,
**unless** `trusted_proxies` is non-empty:

```python
def forward_header_ok(header_value, client_ip, cfg):
    if not header_value:
        return False
    if not cfg.trusted_proxies:   # default is []
        return True
    return client_ip in cfg.trusted_proxies
```

The default header is `X-Forwarded-User`. So with `auth.mode: forward_header` and
no `trusted_proxies` configured, **any client that can reach the direct port can
set `X-Forwarded-User: anyone` and is authenticated** — a full auth bypass. Unlike
`mode=none`, this dangerous state produces no startup warning, and the same logic
gates the WebSocket handshake (`api/ws.py:226`).

**Fix:** Fail closed when `trusted_proxies` is empty in `forward_header` mode (or
require it at config-validation time), and emit a startup warning analogous to the
`mode=none` warning in `main.py:_lifespan`.

### H-2. `LiterTracker` double-counts the last zone of every managed run
**Files:** `domain/tracking.py:35-84`, `domain/sequences.py:209-215, 427-472`

The tracker records "external" valve activity and skips runner-managed zones via
`is_managed(zone_id)` — but it makes that decision on the valve's **off** event:

```python
elif state["state"] == "off" and entity_id in self._on_times:
    on_time = self._on_times.pop(entity_id)
    if self._is_managed(zone_id):
        return  # SequenceRunner handles this entry
    ... writes a RunHistory(triggered_by="external") ...
```

`is_managed` is `True` only while `runner._running` is set. For every zone *except
the last*, `_running` is still set when the next zone is processed, so the off
event is correctly skipped. But for the **last zone**, the sequence of events is:

1. `_safe_turn_off()` issues `switch.turn_off` and awaits the HA result.
2. The loop writes the runner's own `RunHistory`, clears `ActiveRun`, returns.
3. `_execute`'s `finally` sets `_running = None` — **no `await` between step 1 and
   here**, so a queued off-event callback cannot run in this window.
4. HA's `state_changed` "off" event is delivered. If it arrives **after** the
   `turn_off` result (the two are independent messages and ordering is not
   guaranteed), it is dispatched only now — when `_running` is already `None`.
   `is_managed` returns `False`, and the tracker writes a **second**
   `RunHistory(triggered_by="external")` for the same watering.

The result is intermittent (HA-ordering-dependent) **double counting of liters**
and bogus `external` history rows for the final zone of normal runs — directly
corrupting `liters_today`, `liters_week`, `week_series` and the history view, which
are the controller's main reporting surface. Single-zone sequences double-count on
every run.

**Fix:** Don't arbitrate ownership on a volatile flag observed at off-event time.
Options: have the `SequenceRunner` record (and the tracker honor) the off-events it
caused; or have the tracker mark a zone "managed until N seconds after the last
managed off" with a small grace window; or write all rows in one place and tag the
trigger from a durable record rather than `is_managed()`.

---

## 4. Medium

### M-1. `at_datetime` plans are stored without timezone normalization → fire at the wrong time
**Files:** `api/plans.py:66-77`, `scheduler.py:120-125`, `timeutil.py` (unused here)

Datetimes are stored as **naive UTC** (SQLModel strips tzinfo without converting —
see the `timeutil.py` docstring). But `create_plan` does:

```python
scheduled_at = datetime.fromisoformat(str(body.value))
if scheduled_at.tzinfo is None:
    scheduled_at = scheduled_at.replace(tzinfo=UTC)   # assumes input is UTC
```

- A naive local time from the UI (e.g. `2026-05-30T14:00`) is *assumed UTC*, so a
  user wanting 14:00 Berlin gets a run at 16:00 Berlin (CEST).
- An offset-aware time (`...+02:00`) keeps its offset, but on persistence the
  tzinfo is dropped **without conversion**, so the wall-clock value is stored as if
  it were UTC — same 2-hour error.

`_plan_tick` then compares the naive-stored value against `datetime.now(UTC)`.
`POST /plans` with `mode=in_hours` is fine (it's relative).

**Fix:** Interpret naive `at_datetime` input in `config.timezone` and convert to
naive UTC before storing (reuse a `timeutil` helper); for aware input, `astimezone(UTC)`
first. Add tests around DST.

### M-2. `liters_week` (rolling 7 days) ≠ `week_series` (calendar week)
**Files:** `api/system.py:42-61, 109-133`, `pages/Dashboard.tsx:242-251, 304-321`

`liters_week = _liters_since(now − 7 days)` is a trailing-7-day total, while
`week_series` buckets from **Monday of the current local week**. The dashboard
renders `liters_week` as the headline ("Diese Woche" / "Usage 7d") directly above
the Mon→Sun `WeekChart`, so the big number and the sum of the bars disagree (and on
a Monday the chart is nearly empty while the headline shows a full week). The label
"this week" is wrong for a rolling window.

**Fix:** Pick one window. Either make `liters_week` the calendar-week sum
(`sum(week_series)`) or relabel the headline to "last 7 days" and keep the rolling
number — but make the chart and the number consistent with the label.

### M-3. Temperature-factor bounds are not validated (min_pct can exceed max_pct)
**Files:** `config.py:116-122`, `domain/factors.py:36-39`, `api/settings.py:97-130`

`TempFactorConfig` has no cross-field validator, and the settings PATCH only
re-runs the model validators (which don't constrain temp at all). A config with
`temp_min_pct=200, temp_max_pct=80` is accepted; `_compute_temp_factor` then
computes `max(2.0, min(0.8, factor)) = 2.0` and permanently pins the temperature
multiplier to 200% regardless of temperature. Similarly `threshold_prob`
(intended 0–100) and `forecast_days` have no range bounds in `RainFactorConfig`.

**Fix:** Add a `min_pct < max_pct` validator to `TempFactorConfig` and sensible
bounds (`ge/le`) to `min_pct`/`max_pct`/`threshold_prob`/`forecast_days`. Because
`merge_factor_config` already re-validates, this also closes the override path.

### M-4. Manual-start and plan `duration_min` are unbounded
**Files:** `api/schemas.py:44-45, 156-160`, `api/sequences.py:226-229`, `domain/sequences.py:384-389`

`StartSequenceRequest.duration_min` and `CreatePlanRequest.duration_min` are
`int | None` with no lower bound. A `0` or negative override flows through as
`override_min` and bypasses the `range` clamp in `_run_zones` (the clamp only
applies when `override_min is None`), producing a zero-length or instantly-completing
run (`asyncio.sleep` treats negatives as 0). The settings path guards
`basis_min_per_zone > 0`, but the per-run override — the value a user actually types
into the start dialog — is unchecked.

**Fix:** Constrain `duration_min` (`gt=0`, and ideally `le` some sane max) in the
Pydantic models, or clamp `override_min` to `range` in `_run_zones`.

### M-5. No rate limiting / lockout on `/auth/login`
**File:** `api/auth.py:57-69`

Password verification is bcrypt (good), but there is no throttling, backoff, or
lockout on repeated failures, so the single shared password is open to online
brute force from anyone who can reach the endpoint. For a controller that may be
exposed via a reverse proxy this is worth at least a simple per-IP attempt limit.

**Fix:** Add a small in-memory (or DB-backed) per-IP attempt counter with
exponential backoff / temporary lockout, or document that Naiad must sit behind a
proxy that provides it.

---

## 5. Low

- **L-1. Per-zone watchdog semantics are undocumented.** `_wait_zone` is invoked
  per zone with the full `watchdog_min` (`domain/sequences.py:423-425`), so a run of
  *N* zones can stay active up to *N × watchdog_min*. The scheduler only warns when
  `watchdog_min <= basis_min_per_zone` (`scheduler.py:199-206`). Document that the
  watchdog bounds a single zone, not the whole run, so operators size it correctly.

- **L-2. `ha.on_connection_change` is assigned after `ha.start()`.**
  `main.py:140` starts the connect loop; the callback that drives crash recovery is
  set at `main.py:206`. This is safe today only because there is no `await` between
  the two points (the loop can't run yet). Any future `await` inserted in between
  would cause the first `on_connection_change(True)` — and thus crash recovery — to
  be silently skipped. Assign the callback before `await ha.start()`.

- **L-3. Unbounded task spawn per `state_changed` event.** `_dispatch`
  (`ha_client.py:171-172`) spawns one task per registered callback for every state
  change. The tasks are now GC-safe, but a busy HA instance can produce a large
  fan-out (several subscribers × every entity change). Consider running callbacks
  sequentially in the dispatch loop or bounding concurrency.

- **L-4. Rain abort ignores paused runs.** `_on_rain` (`scheduler.py:168-169`)
  returns when no run is *live*. A run that is **paused** (a `ResumeSnapshot`
  exists) is untouched, so it can later be resumed even though rain occurred during
  the pause. Consider clearing the resume snapshot on rain.

- **L-5. `FactorBreakdownResponse` mixes deltas and absolutes.** `temp_pct` is the
  temperature *delta* (`temp_delta_pct`) while `rain_pct` is the *absolute* rain
  factor (`rain_factor_pct`) and `combined_pct` is the absolute combined factor
  (`api/system.py:123-128`). Three numbers in one breakdown with two different
  meanings is easy to misread; document or unify.

- **L-6. Config-reload race with a starting run.** The PUT/import endpoints reject
  changes while a run is live (`api/config.py:153, 196`), but the check and the
  in-place mutation aren't atomic, and `mutate_config_in_place`
  (`runtime_reload.py:25-29`) rewrites the same `AppConfig` the runner reads by
  reference. A reload that races a just-started run could see `zones`/`sequences`
  change mid-iteration. Narrow window, but worth a guard or a copy-on-write.

- **L-7. Cold sensor cache fails open.** After (re)connect, `read_sensor_snapshot`
  returns defaults (and marks sensors `unavailable`) until `_load_state_cache`
  finishes (`ha_client.py:130-145`, `domain/sensors.py:10-19`). A cron firing in
  that window waters at full/temp-only factor (rain → 0 mm). It's logged as a
  warning, but for a water controller consider deferring the first run until the
  cache is warm.

- **L-8. Auth token in `localStorage`.** `client.ts` / `useWebSocket.ts` store the
  bearer token in `localStorage`, which is XSS-exfiltratable. React escapes
  rendered backend strings (no obvious stored-XSS sink found), so this is a
  documented trade-off rather than an active vuln — but it remains the weakest point
  of the auth design and is called out by `CLAUDE.md`'s security section.

---

## 6. Recommended priorities

1. **Fix the reporting corruption:** H-2 (liter double-count) — it silently
   distorts every usage number the UI shows.
2. **Close the auth fail-open:** H-1 (`forward_header` default), then M-5 (login
   throttling).
3. **Correct scheduling/time math:** M-1 (`at_datetime` timezone), M-2 (week
   window consistency).
4. **Tighten input boundaries:** M-3 (temp factor bounds), M-4 (duration overrides).
5. **Hardening / clarity:** the Low items, especially L-2 (callback ordering) and
   L-4 (rain vs paused).
