# Naiad — Code Review (2026-06-10)

Full review of the backend (`src/backend/naiad/`) and frontend
(`src/frontend/src/`). All low-risk findings — and several batches of agreed
follow-ups — have been implemented and verified (pytest 349 passed, vitest 46
passed, ruff, mypy, eslint, `tsc -b` all green); completed items have been
removed from this document. What remains below is the overall assessment and
the findings that still need a decision or were deliberately left untouched.

Feature ideas live separately in `future_improvements.md`.

---

## Overall assessment

### Architecture: very good

- **Clean layering**: `api/` (FastAPI routers) → `domain/` (runner, factors,
  recovery, tracking) → `drivers/` + `ha_client` (HA connectivity). The domain
  layer has no FastAPI dependencies; `auth_rules.py` is deliberately factored
  into pure predicates and therefore reused three times (REST, WebSocket,
  auto-login).
- **Safety thinking at the level of a critical system**: valve safety is
  layered and well thought out — `ActiveRun` (per-sequence crash recovery),
  `PendingClose` (per physical switch, survives config reloads), watchdog,
  staircase hardware timer as a second net, reconcile-on-reconnect, periodic
  close retry guarded by `is_switch_managed`. Ownership is correctly anchored
  to the physical switch (not the zone).
- **Deliberate concurrency invariants**: run registration before the first
  `await` ("asyncio mutex"), an await-free config swap with a re-check after
  `request.body()`, per-socket send locks in the WS manager. These invariants
  are documented in the code — exemplary.
- **Comment culture**: comments consistently explain the *why* (e.g. why
  `confirm_with_rain_sensor` is opt-in, why reload is not blocked on
  recovery). That is rare quality.
- **Test coverage**: 349 backend tests, 46 frontend tests, an OpenAPI contract
  test, and the HA client mocked everywhere (per the CLAUDE.md rule).

### Clean code: good, with few weak spots

- `domain/sequences.py` (~1250 lines) and `_run_zones` (~270 lines) are the
  biggest chunks. `_run_zones` reads linearly, but the result handling (STOP /
  WATCHDOG / RETRIGGER_FAILED / PAUSE / not-closed) would be more compact as a
  table or result object. No urgency, but worth refactoring with the next
  extension.
- Naive-UTC datetimes as the storage format are consistently documented and
  centralized in `timeutil.py` — it works, but remains a standing source of
  errors (every new query has to remember the convention). See finding B-7.
- Frontend: inline styles follow the project convention consistently;
  components are manageable; React Query usage is idiomatic (optimistic
  reorder updates with rollback are solved cleanly). The new settings-section
  architecture (`sectionsMeta.ts` as the single source of truth, config draft
  in `SettingsLayout`, the `usesDraft` distinction with per-section dirty
  markers) is well structured.

---

## Open findings — backend

### B-3: Login throttle is global behind a reverse proxy
`LoginThrottle` is keyed on `request.client.host`. Behind a reverse proxy (not
forward_header mode — e.g. plain TLS termination with password auth) every
client shares the proxy's IP, so five failed attempts from anyone lock everyone
out (self-DoS). X-Forwarded-For must not be trusted blindly without a
trusted-proxy concept.
**Suggestion:** reuse the `trusted_proxies` concept from `forward_header` for
client-IP resolution (e.g. uvicorn `--proxy-headers` + `forwarded_allow_ips`).
→ Deployment decision.

### B-4: Tokens are stored in plaintext (and the lookup is theoretically timing-sensitive)
`require_auth` does a PK lookup with the bearer token; tokens are stored
verbatim. If the SQLite file leaks, every session is compromised. The usual
approach is to store only a hash (e.g. SHA-256) of the token and hash on
lookup — cost-neutral, but a migration concern (existing tokens are
invalidated).
→ Needs a conscious decision, since every device would have to log in again.

### B-7: The naive-UTC convention remains error-prone
It works consistently today (good helpers in `timeutil.py`, the `UtcDatetime`
serializer), but every new query/comparison site has to know the convention
(`SkippedRun` matching, `_utcnow_naive`, `enqueued_at`, …). Mid-term, a central
SQLAlchemy `TypeDecorator` (aware in → naive out, always UTC) would be more
robust. → Larger refactor, noted as a recommendation only.

### B-10: `_RequestIDMiddleware` does not propagate the request ID into logs
The ID only lands in the response header. If you want request correlation in
the JSON logs, it would have to flow into `_JSONFormatter` via a `contextvar`.
→ Only worthwhile if you actually search logs by request.

---

## Security assessment (summary)

Positive: secrets come from the environment only and are stripped before
persistence; bearer tokens are never logged; ingress trust is correctly based
on the source IP rather than a header; `forward_header` fails closed without
`trusted_proxies`; referer matching is origin-exact instead of substring-based;
a lockout guard prevents password mode without a password; login throttling is
in place. Remaining items: B-3 (throttle behind a proxy) and B-4 (token
hashing). Neither is acutely critical for a LAN/ingress deployment.
