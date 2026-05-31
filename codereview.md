# Code Review — Naiad

**Scope:** Full-codebase re-review of the Naiad garden irrigation controller
(FastAPI/SQLModel backend + React/TypeScript frontend), integrating with Home
Assistant over WebSocket.
**Date:** 2026-05-31
**Branch reviewed:** `claude/naiad-review-docs-xYRMk`
**Reviewed against:** `CLAUDE.md` project rules, `docs/openapi.yaml` contract.

> This review supersedes the previous one. Findings that the current source
> genuinely resolves have been **removed** rather than re-reported; the
> remaining open items are re-derived from the code as it stands today, and a
> few new findings are added. CI was reproduced locally on Python 3.12 and is
> **fully green**: `ruff check`, `ruff format --check`, `mypy naiad`
> (35 files, no issues), and `pytest` (209 passed) all pass.

---

## 1. Summary / Verdict

Naiad remains a well-structured codebase. The layering
(config → domain → drivers → API → scheduler) is clean, the `IValveDriver`
abstraction keeps the HA client mockable, the sequence state machine is sound,
and crash recovery (`ActiveRun` + `recover_run` + `reconcile_valves`) closes the
biggest historical safety gap. Timezone handling is now centralized in
`timeutil.py` and used consistently on the status/history/plan paths.

Since the last review the codebase has closed a substantial block of findings
(verified against the source — see §6 *Resolved since last review*): the liter
double-count race, the `at_datetime` timezone bug, the calendar-week metric
mismatch, the temperature/rain factor bounds, unbounded run durations, the
HA-connection callback ordering, and the factor-breakdown delta/absolute
confusion are all fixed and covered by tests.

What remains clusters in three areas:

- **Auth still fails open by default in `forward_header` mode.** A startup
  warning was added, but at runtime a client-supplied header is still trusted
  when `trusted_proxies` is empty (the default) — on both the REST and the
  WebSocket path. There is also no throttling on `/auth/login`.
- **A computed factor of 0 % does not skip a scheduled run.** Heavy forecast
  rain drives the rain factor to `0.0` (by design, via `zero_above_mm`), but the
  per-zone duration is floored at `range[0]`, so the run still waters the
  minimum. Only `season_off` and the live rain *sensor* actually stop a run.
- **A handful of hardening / clarity items** (per-zone watchdog semantics, rain
  vs. paused runs, config-reload atomicity, token in `localStorage`, two
  hardcoded hex colors, a now-misleading "7 days" label).

Counts: **High 1 · Medium 2 · Low 7.**

---

## 2. Architecture Assessment

**Strengths**

- Clear separation of concerns; `domain/` is mostly pure and unit-testable.
- Driver/sensor `Protocol` abstraction enables the "mock the HA client" test
  rule; the suite (`tests/`, 209 tests) covers factors, the state machine
  (incl. watchdog/rain/resume), crash recovery, the WS manager, auth rules, and
  config round-trips.
- Config validation has real cross-field rules (`range`,
  `reduce_above_mm < zero_above_mm`, `min_pct <= max_pct`, zone-reference
  integrity, timezone) and a "lockout guard" on the config PUT/import path
  (`build_validated_config` refuses to switch to `mode=password` with no
  password set).
- Crash recovery is a thoughtful answer to the ephemeral-container / stuck-valve
  problem, with an explicit "zone duration as the bound" policy and idempotent
  `reconcile_valves`.
- Runtime config reload mutates a single shared `AppConfig` in place, preserving
  the object identity the scheduler/runner hold by reference.
- The liter-tracking ownership decision now happens on the valve **on** event
  (`tracking.py`), so a managed zone never enters the "external" off path — the
  whole double-count class of bug is gone.

**Concerns**

1. **Auth defaults fail open.** `mode=none` warns loudly, and
   `forward_header` with no `trusted_proxies` now *also* warns at startup — but
   it still trusts a spoofable header at request time (**H-1**), and there is no
   request throttling on `/auth/login` (**M-1**).

2. **"Factor" and "skip" are not the same decision.** The scheduler skips on
   `season_off` and on a wind alarm, and the live rain listener aborts a running
   sequence, but a *computed* factor of 0 % (forecast rain ≥ `zero_above_mm`)
   does not skip — `_run_zones` floors the duration at `range[0]` and waters the
   minimum anyway (**M-2**).

3. **Two writers for `RunHistory`, now safely arbitrated.** The runner owns
   managed runs; the `LiterTracker` owns external valve activity. Ownership is
   decided at *valve-on* time and the managed zone is never added to the
   tracker's `_on_times`, so the previous off-event race is closed. This is
   sound; it is noted here only because the two-writer design still relies on the
   `is_managed` predicate staying correct.

---

## 3. High

### H-1. `forward_header` auth trusts a client-supplied header by default
**Files:** `auth_rules.py:28-39`, `config.py:116-122`, `dependencies.py:66-70`, `api/ws.py:226-228`, `main.py:136-142`

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

The default header is `X-Forwarded-User`, and `trusted_proxies` defaults to `[]`.
So with `auth.mode: forward_header` and no `trusted_proxies` configured, **any
client that can reach the direct port can send `X-Forwarded-User: anyone` and is
authenticated** — a full auth bypass. The same logic gates the WebSocket
handshake (`api/ws.py:228`).

**Partial mitigation present:** `main.py:136-142` now logs a startup warning when
this combination is configured, but the runtime behaviour is unchanged — it
warns, then fails open.

**Fix:** Fail closed when `trusted_proxies` is empty in `forward_header` mode
(reject the request), or require `trusted_proxies` at config-validation time so
the dangerous state can't be persisted.

---

## 4. Medium

### M-1. No rate limiting / lockout on `/auth/login`
**File:** `api/auth.py:57-69`

Password verification is bcrypt with a constant-time plaintext fallback (good),
but there is no throttling, backoff, or lockout on repeated failures. The single
shared password is open to online brute force from anyone who can reach the
endpoint. For a controller that may sit behind a reverse proxy this warrants at
least a simple per-IP attempt limit.

**Fix:** Add a small in-memory (or DB-backed) per-IP attempt counter with
backoff / temporary lockout, or document that Naiad must sit behind a proxy that
provides it.

### M-2. A computed factor of 0 % does not skip a run (range floor overrides it)
**Files:** `domain/sequences.py:525-531`, `domain/factors.py:45-62`, `scheduler.py:140-161`

`_compute_rain_factor` returns `0.0` once forecast rain reaches `zero_above_mm`
(documented in `config.example.yaml` as "factor = 0.0 at or above this"), and
`compute_factors` multiplies it into `factor_pct = 0`. But `_run_zones` clamps:

```python
lo, hi = seq.range
basis = effective_basis * factor_pct / 100.0
duration_min = max(float(lo), min(float(hi), basis))   # floor at lo even when basis == 0
```

So a cron run with `factor_pct == 0` still waters every zone for `range[0]`
minutes (5 min by default). The scheduler only skips on `season_off` and a wind
alarm; the *forecast* rain factor reaching 0 is not a skip condition (only the
live rain *binary sensor* aborts, via `_on_rain`). The result is that the
explicit "zero out watering above N mm" knob never actually reaches zero on a
scheduled run.

**Fix:** Decide the intended semantics and make them consistent — either skip the
run when `round(factor_pct) == 0` (e.g. in `_run_sequence_job`, alongside
`season_off`), or document that `range[0]` is a hard floor that overrides the
factor and rename the knob's promise accordingly. A skip is the less surprising
behaviour given the existing `zero_above_mm` configuration.

---

## 5. Low

- **L-1. Per-zone watchdog semantics are undocumented.** `_wait_zone`
  (`domain/sequences.py:578-580`) is invoked per zone with the full
  `watchdog_min`, so a run of *N* zones can stay active up to *N × watchdog_min*.
  The scheduler only warns when `watchdog_min <= basis_min_per_zone`
  (`scheduler.py:458-465`). Document that the watchdog bounds a single zone, not
  the whole run, so operators size it correctly.

- **L-2. Rain abort ignores paused runs.** `_on_rain`
  (`scheduler.py:307-309`) returns when no run is *live*. A run that is **paused**
  (a `ResumeSnapshot` exists, runner reads as IDLE) is untouched, so it can later
  be resumed even though rain occurred during the pause. Consider clearing the
  resume snapshot on rain.

- **L-3. Unbounded task spawn per `state_changed` event.** `_dispatch`
  (`ha_client.py:175-176`) spawns one task per registered callback for every
  state change. The tasks are GC-safe, but a busy HA instance can produce a large
  fan-out (several subscribers × every entity change). Consider running callbacks
  sequentially in the dispatch loop or bounding concurrency.

- **L-4. Config-reload race with a starting run.** The PUT/import endpoints reject
  changes while a run is live (`api/config.py:175, 220`), but the check and the
  in-place mutation (`runtime_reload.apply_reloaded_config`) aren't atomic, and
  the reload rewrites the same `AppConfig` the runner reads by reference. A reload
  that races a just-started run could see `zones`/`sequences` change
  mid-iteration. Narrow window, but worth a guard or copy-on-write.

- **L-5. Auth token in `localStorage`.** `api/client.ts:8` /
  `hooks/useWebSocket.ts:49` store the bearer token in `localStorage`, which is
  XSS-exfiltratable. No obvious stored-XSS sink was found (React escapes rendered
  strings), so this is a documented trade-off rather than an active vuln — but it
  remains the weakest point of the auth design and is called out by `CLAUDE.md`'s
  security section.

- **L-6. Hardcoded hex colors violate the design-token rule.**
  `pages/Planner.tsx:100` and `:185` use a literal `'#04181c'` for active-button
  text. `CLAUDE.md` requires `var(--n-*)` tokens (the sequence-accent exception
  doesn't apply here). Replace with a token (e.g. an `--n-on-accent` text color).
  *(The `icons.tsx` logo fills are intentional branding, not a violation.)*

- **L-7. Dashboard "7 days" label is now misleading.** The backend headline
  `liters_week` is now the **current local calendar week** (Mon→Sun, summing the
  `week_series` bars below it). The frontend still labels it
  `dashboard.usage7d` ("Usage · 7 days" / "Verbrauch · 7 Tage", and the mobile
  "this week"/"diese Woche"). The number and chart now agree, but the "7 days"
  wording describes the old rolling window. Relabel to "this week" / "diese
  Woche" consistently (`pages/Dashboard.tsx:307,375,378`, i18n
  `dashboard.usage7d`).

---

## 6. Resolved since last review (verified, not re-reported)

These previously-reported items are confirmed fixed in the current source and
backed by passing tests:

- **Liter double-count of the last zone (was H-2):** the `LiterTracker` now
  decides ownership on the valve **on** event and never stores a managed zone in
  `_on_times` (`domain/tracking.py:44-63`), so the off-event race that produced a
  duplicate `external` row is gone.
- **`at_datetime` plan timezone (was M-1):** `api/plans.py:101-120` interprets a
  naive wall-clock value in `config.timezone` and stores it as naive UTC via
  `timeutil.to_naive_utc`.
- **`liters_week` vs `week_series` (was M-2):** `api/system.py:248,275` both
  bucket from the local Monday (`local_week_start_utc`), so the headline equals
  the sum of the chart. *(Residual: the UI label still says "7 days" — see L-7.)*
- **Temperature / rain factor bounds (was M-3):** `TempFactorConfig` validates
  `min_pct <= max_pct` with `ge=0`; `RainFactorConfig` bounds `threshold_prob`
  (0–100), `forecast_days` (≥1), `forecast_decay` (0–1) (`config.py:319-347`).
  `merge_factor_config` re-validates, covering the override path.
- **Unbounded run durations (was M-4):** `StartSequenceRequest`,
  `StartZoneRequest`, and `CreatePlanRequest` all constrain `duration_min` with
  `gt=0` (`api/schemas.py:62-67, 225`). *(Still no upper bound, but the per-zone
  watchdog bounds an over-long override — see L-1.)*
- **HA callback ordering (was L-2):** `ha.on_connection_change` is assigned
  before `await ha.start()` (`main.py:238, 243`), so the first connect (crash
  recovery) can't fire before its handler is attached.
- **Factor-breakdown delta/absolute mix (was L-5):** `api/system.py:262-269` now
  emits both `temp_pct` and `rain_pct` as signed deltas from neutral, documented
  in `api/schemas.py:130-136`.
- **WS per-connection send lock & startup `forward_header` warning** were already
  in place and remain correct.
- **Cold sensor cache (was L-7):** now fails *safe* — an empty cache leaves the
  season sensor `unavailable`, which yields `season_off` and *skips* the run
  rather than over-watering. No longer a concern.

---

## 7. Recommended priorities

1. **Close the auth fail-open:** H-1 (`forward_header` default — enforce, don't
   just warn), then M-1 (login throttling).
2. **Make the rain knob honest:** M-2 (factor 0 % should skip, or document the
   floor).
3. **Hardening / clarity:** the Low items — especially L-2 (rain vs. paused) and
   L-1 (watchdog semantics).
4. **UI polish:** L-6 (hardcoded colors) and L-7 ("7 days" relabel).
