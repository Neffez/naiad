# Naiad — Code Review (2026-11-20)

Full review of the backend (`src/backend/naiad/`), frontend (`src/frontend/src/`),
build/CI setup and the Home Assistant add-on repository (`app-naiad`), with a
focus on bugs and architecture. Everything clearly fixable was fixed in the same
change, with regression tests; what remains below needs a decision.

Verification after the changes: pytest 481 passed (+33), vitest 55 passed (+2),
ruff, ruff format, mypy (strict), eslint, `tsc -b`, `vite build`, typegen
consistency — all green. A uvicorn smoke run (no HA) confirmed the SPA
fallback, API 404s and config validation.

Feature ideas live separately in `future_improvements.md`.

---

## Overall assessment

The architecture remains strong: clean `api/ → domain/ → drivers/ha_client`
layering, layered valve safety (ActiveRun, per-switch PendingClose, watchdog,
staircase net, reconcile-on-reconnect), deliberate await-free critical
sections, and comments that explain the *why*. Most bugs found this round sit
at the **seams**: config round-trips through the UI, retry loops that also
notify, third-party semantics (APScheduler cron, MQTT discovery), and the build
not using the lockfile.

---

## Fixed in this review

### Backend — bugs
| # | Finding | Fix |
|---|---|---|
| 1 | `_run_zones` crashed with `UnboundLocalError` when every zone was skipped (et0_zonal, all saturated): the cleanup helper was defined inside the loop body. Logged as "unhandled error". | Cleanup inlined; an all-skipped run ends normally and is logged. |
| 2 | `merge_factor_config` (raises on invalid overrides) was used in the runner (`_zonal_durations`), the hourly/reconnect refreshes and the MQTT publisher. A stored override invalidated by a later config change crashed a run before its first valve opened, aborted the HA-reconnect callback and blanked all MQTT publishing. | All read paths use the tolerant `load_factor_config`; only the settings PATCH still validates strictly (422). |
| 3 | A plan (or deferred cron run) blocked by a long run is retried every minute — and pushed a conflict notification on **every** retry (unbounded for plans). | Conflict is announced once per plan/deferred run (`_conflict_notified`). |
| 4 | Saving the configuration in the UI reset `language` (server notifications back to English) and `auth.ingress` (re-enabling ingress trust / resetting its IP) because the UI document does not carry them. | `carry_unexposed_fields` keeps both on PUT. |
| 5 | APScheduler 3.x numbers cron weekdays 0=Monday; every crontab reference uses 0/7=Sunday, 1=Monday. An advanced cron `0 6 * * 1-5` fired **Tue–Sat**; `7` was rejected. | `to_apscheduler_crontab` rewrites numeric weekday fields to day names with standard semantics (schedules + evening reminder). |
| 6 | Invalid cron expressions (advanced schedule, reminder) were accepted and silently skipped at registration — the sequence just never ran. | Validated at the API boundary (PUT/import → 422). Not in the pydantic model, so a stored bad value cannot block startup. |
| 7 | `bcrypt.checkpw` (~0.25 s CPU) ran on the event loop inside `async def login`, delaying valve timers/requests on every attempt. | Runs in a worker thread; `$2y$` hashes are recognized. |
| 8 | Expired auth tokens were never deleted. | Pruned whenever a token is issued. |
| 9 | `POST /plans` with `in_hours` = `nan`/`inf`/huge → 500 (timedelta overflow). | Finite, `(0, 8784]` hours, else 422. |
| 10 | `GET /plans` hid due plans that are still retrying (conflict/busy) — invisible and impossible to cancel. | Lists every pending plan. |
| 11 | The dashboard "next run" ignored user-skipped occurrences (the upcoming list honoured them). | Built on `upcoming_run_candidates`. |
| 12 | `POST /sequences/__zone__<id>/pause` paused a standalone zone run and left an orphaned snapshot. | 404 for non-sequences (documented in OpenAPI). |
| 13 | SPA fallback answered unknown `/api/*` paths with `index.html` + 200. | Unknown API paths stay 404. |
| 14 | HA client: a clean websocket close reconnected immediately (hot loop possible); removed entities stayed in the state cache forever; numeric day bucketing used a different boundary rule than rain bucketing. | 1 s pause after clean close; cache eviction on `new_state=None`; shared `day_index`. |
| 15 | WebSocket handshake/loop assumed JSON objects (`[]` → AttributeError). | Type-checked. |
| 16 | MQTT: enabling/re-pointing the bridge in the UI did nothing until a restart; removed zones/sequences left "unavailable" ghost entities; `object_id` is deprecated in HA (2025.10+); fire-and-forget task without reference. | Live re-dial on broker-setting changes; empty retained discovery withdraws removed entities; `default_entity_id` sent alongside `object_id`; task references kept. Port validated 1–65535. |

### Frontend — bugs
| # | Finding | Fix |
|---|---|---|
| 17 | `NumberField`: Enter committed the value but also triggered the form's implicit submit with the parent's **previous** value — e.g. in the planner, typing `6` h + Enter scheduled the run in 4 h. | `preventDefault` on Enter (regression test). |
| 18 | History showed every non-manual run as "Scheduled" (external valve activity, MQTT, resume, plans). | Real trigger source labels (+ i18n keys). |
| 19 | Settings dirty markers missed frost/cistern (Connection) and water price (Advanced). | Included in the section slices. |
| 20 | Planner: double submit created duplicate plans; plan deletion failed silently. | Button disabled while pending; error toast. |
| 21 | Path parameters were not URL-encoded (IDs from imported YAML may contain any character). | `encodeURIComponent`. |

### Build / architecture
| # | Finding | Fix |
|---|---|---|
| 22 | The Docker image ignored `uv.lock` and let pip resolve the open `>=` ranges at build time → production could ship untested majors (e.g. the sqlmodel/FastAPI breaks below). | Image installs exactly the locked set (`uv export --locked`). |
| 23 | Pre-commit hooks pinned ruff 0.4 / mypy 1.10 while CI ran ruff 0.17 / mypy 2.x → commits passed locally and failed CI formatting. | Hooks run the lockfile versions via `uv run --frozen`. |
| 24 | Add-on built `FROM ghcr.io/neffez/naiad:latest`: the installed app version depended on build time; a cached `latest` could keep an old app after an add-on update. | Pinned to `BUILD_VERSION` (lockstep with the app). |
| 25 | README referenced a non-existent `ISensorSource`/`HAEntitySensorSource`. | Corrected. |

### Dependency updates
- Backend (`uv lock --upgrade`): FastAPI 0.165, Starlette 1.10, SQLAlchemy 2.1, sqlmodel 0.0.50, pydantic 2.14, uvicorn 0.54, websockets 17, paho-mqtt 2.2, ruff 0.17, mypy 2.4, pytest 9.2 … APScheduler stays on 3.x (4.x is a rewrite).
  - **sqlmodel ≥ 0.0.45** maps bare `datetime` fields to a tz-aware `UTCDateTime` that rejects naive values. All table timestamps are now annotated `NaiveDatetime` — storage behaviour is unchanged. Minimum versions raised (`sqlmodel>=0.0.45`, `websockets>=13`).
  - **FastAPI 0.165** nests included routers as internal `_IncludedRouter` nodes; the OpenAPI contract test walked `app.routes` and silently compared against an empty set. It now uses `app.openapi()`.
- Frontend: all in-range updates plus majors i18next 27, react-i18next 18, vitest 5, jsdom 31, @testing-library/jest-dom 8. TypeScript 7 is not adopted (typescript-eslint supports < 6.1, openapi-typescript needs ^5 — hence `legacy-peer-deps` stays).

---

## Open findings — need a decision

### R-1: No live rain gate at automatic start
`run_sequence_job` gates on master, pause, wind, season, frost, cistern and the
zero factor — but not on the rain sensor's *current* state. The live rain abort
only fires on a state *change*, so a cron run that starts while it is already
raining runs to completion. Adding a `rain` skip reason is easy (new
`DecisionReason`, i18n, notification), but some rain sensors latch "on" for hours
after rain and would then suppress runs — product decision.

### R-2: Naive-UTC storage (was B-7) — now cheap to migrate
sqlmodel now ships `UTCDateTime` (aware in, aware UTC out) and reads existing
naive-UTC SQLite values back as UTC, so the migration needs **no data
migration** — only the code paths that build naive datetimes / compare with them
(`timeutil`, `_utcnow_naive`, `.replace(tzinfo=None)` sites). Recommended as a
dedicated refactor; the `NaiveDatetime` annotations are the bridge until then.

### R-3: Login throttle is global behind a reverse proxy (was B-3)
Unchanged: keyed on `request.client.host`; behind a TLS-terminating proxy all
clients share one IP. Needs a trusted-proxy concept (uvicorn `--proxy-headers`
+ `forwarded_allow_ips`).

### R-4: Tokens stored in plaintext (was B-4)
Unchanged: storing SHA-256 of the token is cheap but logs every device out once.

### R-5: Graceful shutdown leaves a running valve to the staircase/recovery net
On SIGTERM the run task is cancelled and the ActiveRun record kept for crash
recovery; the valve is not closed. That is consistent with the recovery design
(resume after a quick restart), but during a longer outage the valve stays open
unless the actuator has a staircase timer. Option: close valves on shutdown
unless a restart is expected.

### R-6: CI action majors
`actions/checkout@v4`, `setup-python@v5`, `setup-node@v4`, `setup-uv@v8.2.0`,
docker actions v3/v5/v6 are several majors behind (latest: checkout v7,
setup-python/-node v7, setup-uv v10, build-push v7). Not bumped blind because
they cannot be exercised here. Suggest adding `.github/dependabot.yml` for
`github-actions`, `npm`, `uv` and `docker` so updates arrive as tested PRs.

### R-7: Smaller items
- WebSocket in `forward_header` mode does not check `Origin` (cross-site
  WebSocket reads of status data with the proxy's session cookie; read-only).
- `_consume_skip` matches the skip against wall-clock fire time; a job running
  late within its 300 s misfire grace misses the 120 s tolerance.
- An unhandled runner exception leaves that zone's history row open
  (`ended_at` NULL) forever.
- Zone/sequence IDs are not validated; imported YAML can contain characters that
  break MQTT topics (`/`, `+`, `#`). The UI slugifies, so only imports are affected.
- The service worker skips every path containing `/api/` — under HA ingress
  (`/api/hassio_ingress/…`) it therefore never caches anything.
- `_RequestIDMiddleware` does not feed the request ID into the JSON logs (was B-10).
