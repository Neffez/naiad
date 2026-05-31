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
> (35 files, no issues), and `pytest` (217 passed) all pass.

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

The one substantive item left open is:

- **Auth still fails open by default in `forward_header` mode.** A startup
  warning was added, but at runtime a client-supplied header is still trusted
  when `trusted_proxies` is empty (the default) — on both the REST and the
  WebSocket path. (Left open because hard enforcement is a deployment decision:
  failing closed would break setups that rely on network isolation instead of
  `trusted_proxies`.)

The rest are hardening items (config-reload atomicity, unbounded per-event task
fan-out, token in `localStorage`).

Counts: **High 1 · Medium 0 · Low 3.** Two passes in this branch fixed the
remainder — see §6: the four low-risk doc/UI/behaviour items (watchdog docs,
rain vs. paused, hardcoded colors, the "7 days" label), plus **login throttling
(M-1)** and **the factor-0 % skip (M-2)**.

---

## 2. Architecture Assessment

**Strengths**

- Clear separation of concerns; `domain/` is mostly pure and unit-testable.
- Driver/sensor `Protocol` abstraction enables the "mock the HA client" test
  rule; the suite (`tests/`, 217 tests) covers factors, the state machine
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
   it still trusts a spoofable header at request time (**H-1**). `/auth/login`
   now has per-IP throttling (fixed, see §6).

2. **Two writers for `RunHistory`, now safely arbitrated.** The runner owns
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

None open. Both medium findings were fixed in this branch (see §6): per-IP login
throttling (was M-1) and skipping an automatic run when the factor is 0 %
(was M-2).

---

## 5. Low

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
  the sum of the chart. *(The UI label was relabelled to "this week" to match —
  see "Fixed in this branch" below.)*
- **Temperature / rain factor bounds (was M-3):** `TempFactorConfig` validates
  `min_pct <= max_pct` with `ge=0`; `RainFactorConfig` bounds `threshold_prob`
  (0–100), `forecast_days` (≥1), `forecast_decay` (0–1) (`config.py:319-347`).
  `merge_factor_config` re-validates, covering the override path.
- **Unbounded run durations (was M-4):** `StartSequenceRequest`,
  `StartZoneRequest`, and `CreatePlanRequest` all constrain `duration_min` with
  `gt=0` (`api/schemas.py:62-67, 225`). *(Still no upper bound, but the per-zone
  watchdog bounds an over-long override.)*
- **HA callback ordering (was L-2):** `ha.on_connection_change` is assigned
  before `await ha.start()` (`main.py:238, 243`), so the first connect (crash
  recovery) can't fire before its handler is attached.
- **Factor-breakdown delta/absolute mix (was L-5):** `api/system.py:262-269` now
  emits both `temp_pct` and `rain_pct` as signed deltas from neutral, documented
  in `api/schemas.py:130-136`.
- **WS per-connection send lock & startup `forward_header` warning** were already
  in place and remain correct.
- **Cold sensor cache:** fails *safe* — an empty cache leaves the season sensor
  `unavailable`, which yields `season_off` and *skips* the run rather than
  over-watering. No longer a concern.

**Fixed in this branch (second pass):**

- **Rain abort now honors paused runs.** `_on_rain` discards the resume snapshot
  when rain starts while a run is paused, so it can't be resumed afterwards
  (`scheduler.py`, `SequenceRunner.clear_paused_snapshot`,
  `domain/resume.clear_any_snapshot`; tests in `tests/test_scheduler.py`).
- **Per-zone watchdog semantics documented.** README "Scheduling & safety" and a
  comment on `watchdog_min` in `config.example.yaml` now state that the watchdog
  bounds a single zone (a run of *N* zones can take up to *N × watchdog_min*).
- **Hardcoded hex colors removed.** `#04181c` is centralized as a new
  `--n-on-accent` token in `index.css` and referenced from `index.css` and
  `pages/Planner.tsx` instead of being inlined.
- **Misleading "7 days" label relabelled.** The dashboard headline key was
  renamed `usage7d → usageWeek` ("Usage · this week" / "Verbrauch · diese
  Woche") to match the now calendar-week figure (`Dashboard.tsx`, both locales).
- **Login throttling added (was M-1).** `LoginThrottle` (`api/auth.py`) imposes a
  growing per-IP temporary lockout after repeated failed logins (in-memory, keyed
  on the socket IP; a correct password clears the counter), and `/auth/login`
  returns `429` with `Retry-After` while locked. Unit + endpoint tests in
  `tests/test_auth.py`.
- **Factor-0 % now skips an automatic run (was M-2).** `_run_sequence_job` skips
  when `round(factor_pct) == 0` (alongside `season_off`), so heavy forecast rain
  (≥ `zero_above_mm`) no longer waters the range floor on cron/plan runs. Manual
  starts are intentionally exempt. Test in `tests/test_scheduler.py`.

---

## 7. Recommended priorities

1. **Close the auth fail-open:** H-1 (`forward_header` default — enforce rather
   than only warn). This is the one remaining substantive finding; it is left as
   a deployment decision (failing closed breaks setups relying on network
   isolation instead of `trusted_proxies`).
2. **Hardening:** the remaining Low items — L-3 (per-event task fan-out),
   L-4 (config-reload atomicity), L-5 (token in `localStorage`).
