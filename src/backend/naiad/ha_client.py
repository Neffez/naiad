import asyncio
import contextlib
import json
import logging
from collections.abc import Callable, Coroutine
from datetime import datetime
from typing import TYPE_CHECKING, Any

import websockets
import websockets.exceptions
from websockets.asyncio.client import ClientConnection

from naiad.domain.et0 import day_index

if TYPE_CHECKING:
    from naiad.domain.et0 import ZoneBalanceInput

logger = logging.getLogger(__name__)

StateCallback = Callable[[str, dict[str, Any]], Coroutine[Any, Any, None]]


def _entry_timestamp(entry: dict[str, Any]) -> float | None:
    """Epoch seconds of a recorder history entry, or None if unparseable.

    Minimal-response entries carry ``lu``/``lc`` (Unix timestamps); the first,
    full entry carries ISO ``last_updated``/``last_changed``."""
    for key in ("lu", "lc"):
        val = entry.get(key)
        if val is not None:
            try:
                return float(val)
            except (TypeError, ValueError):
                return None
    for key in ("last_updated", "last_changed"):
        val = entry.get(key)
        if isinstance(val, str):
            try:
                return datetime.fromisoformat(val).timestamp()
            except ValueError:
                return None
    return None


class HAError(Exception):
    def __init__(self, error: dict[str, Any]) -> None:
        super().__init__(error.get("message", str(error)))
        self.code: str | None = error.get("code")


class HAClient:
    def __init__(self, url: str, token: str) -> None:
        self._url = url
        self._token = token
        self._ws: ClientConnection | None = None
        self._msg_id = 0
        self._pending: dict[int, asyncio.Future[Any]] = {}
        self._state_cache: dict[str, dict[str, Any]] = {}
        # Cached "max value over a period" per entity (e.g. yesterday's max
        # temperature), refreshed out-of-band so synchronous callers can read it.
        self._daily_max_cache: dict[str, float | None] = {}
        # Per forecast entity: the peak value it reached while the binary rain sensor
        # was on today (reconstructed from the recorder). Lets synchronous callers
        # (read_sensor_snapshot) confirm today's forecast peak against actual rain.
        self._rain_confirmed_peak_cache: dict[str, float | None] = {}
        self._recent_rain_credit_cache: dict[str, float | None] = {}
        # Soil water balance for the et0 rain mode (one global value, mm). None =
        # never computed; refreshed out-of-band like the rain credit.
        self._et0_balance_mm: float | None = None
        # Per-zone soil water balances for the et0_zonal rain mode (zone_id → mm).
        # Empty = never computed; refreshed out-of-band like the global balance.
        self._zone_balance_mm: dict[str, float] = {}
        # The HA home latitude (from the server's get_config), needed for the
        # internal Hargreaves ET₀ calculation. Refreshed on every (re)connect.
        self._latitude: float | None = None
        self._state_callbacks: list[StateCallback] = []
        self._connected = asyncio.Event()
        self._loop_task: asyncio.Task[None] | None = None
        # Strong references to fire-and-forget tasks; the event loop only keeps
        # weak refs, so without this they could be garbage-collected mid-flight.
        self._bg_tasks: set[asyncio.Task[Any]] = set()
        self.on_connection_change: Callable[[bool], Coroutine[Any, Any, None]] | None = None

    def _spawn(self, coro: Coroutine[Any, Any, None], *, name: str | None = None) -> None:
        task = asyncio.create_task(coro, name=name)
        self._bg_tasks.add(task)
        task.add_done_callback(self._bg_tasks.discard)

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def start(self) -> None:
        self._loop_task = asyncio.create_task(self._connect_loop(), name="ha-connect-loop")

    async def stop(self) -> None:
        if self._loop_task:
            self._loop_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._loop_task
        for task in list(self._bg_tasks):
            task.cancel()
        if self._ws:
            await self._ws.close()

    # ── Connection loop ───────────────────────────────────────────────────────

    def _mark_disconnected(self) -> None:
        """Tear down a dropped connection: clear state, fail pending requests and
        fire the offline callback.

        Idempotent and called from both close paths, because a websocket can end
        two ways: abnormally (``async for`` raises → handled in ``_connect_loop``)
        or *normally* when HA closes cleanly (codes 1000/1001 — the iterator just
        stops, no exception). Without covering the normal path too, a clean HA
        restart would leave pending futures hanging until their own timeout and
        never broadcast that HA went offline.
        """
        was_connected = self._connected.is_set()
        self._connected.clear()
        self._ws = None
        for fut in self._pending.values():
            if not fut.done():
                fut.cancel()
        self._pending.clear()
        if was_connected and self.on_connection_change:
            self._spawn(self.on_connection_change(False), name="ha-conn-change")

    async def _connect_loop(self) -> None:
        delay = 1.0
        while True:
            try:
                await self._connect()
                delay = 1.0
            except asyncio.CancelledError:
                raise
            except Exception:
                # Cleanup normally already ran in _connect's finally; this covers the
                # case where the failure happened before that finally could run (e.g.
                # websockets.connect() itself failed). _mark_disconnected is idempotent.
                self._mark_disconnected()
                logger.warning("HA connection lost — retrying in %.0fs", delay, exc_info=True)
                await asyncio.sleep(delay)
                delay = min(delay * 2, 60.0)

    async def _connect(self) -> None:
        logger.info("Connecting to Home Assistant at %s", self._url)
        async with websockets.connect(self._url, max_size=2**24) as ws:
            # Auth handshake
            raw = await ws.recv()
            msg: dict[str, Any] = json.loads(raw)
            if msg.get("type") != "auth_required":
                raise HAError({"message": f"Expected auth_required, got: {msg.get('type')}"})

            await ws.send(json.dumps({"type": "auth", "access_token": self._token}))
            raw = await ws.recv()
            msg = json.loads(raw)
            if msg.get("type") != "auth_ok":
                raise HAError({"message": "HA authentication failed — check HA_TOKEN"})

            self._ws = ws
            ha_version = msg.get("ha_version", "unknown")
            logger.info("Authenticated with Home Assistant %s", ha_version)

            # Start message dispatch as a concurrent task
            msg_task = asyncio.create_task(self._message_loop(ws), name="ha-msg-loop")

            try:
                # Subscribe to state_changed events first (lightweight)
                await self._send_command(
                    ws,
                    {"type": "subscribe_events", "event_type": "state_changed"},
                )

                # Connection is usable for call_service now
                self._connected.set()
                logger.info("Home Assistant connection ready")
                if self.on_connection_change:
                    self._spawn(self.on_connection_change(True), name="ha-conn-change")

                # Load full state cache in background (best-effort)
                self._spawn(self._load_state_cache(ws), name="ha-state-cache")
                # Cache the HA home latitude for the internal ET₀ calculation
                # (best-effort; et0 mode falls back to its decay heuristic).
                self._spawn(self._load_ha_latitude(ws), name="ha-latitude")

                await msg_task  # runs until connection drops
            finally:
                msg_task.cancel()
                with contextlib.suppress(Exception):
                    async with asyncio.timeout(2):
                        await msg_task
                # Runs whether the message loop ended via exception or a clean close,
                # so pending requests fail fast and the offline callback always fires.
                self._mark_disconnected()

    async def _load_state_cache(self, ws: ClientConnection) -> None:
        """Best-effort bulk load of all entity states."""
        try:
            states: list[dict[str, Any]] = await self._send_command(
                ws,
                {"type": "get_states"},
                timeout=120.0,
            )
            for state in states:
                self._state_cache[state["entity_id"]] = state
            logger.info("State cache loaded (%d entities)", len(self._state_cache))
        except Exception:
            logger.warning(
                "Could not bulk-load state cache — states will populate incrementally from events",
                exc_info=True,
            )

    async def _load_ha_latitude(self, ws: ClientConnection) -> None:
        """Best-effort fetch of the HA home latitude (server ``get_config``)."""
        try:
            result: dict[str, Any] = await self._send_command(ws, {"type": "get_config"})
            latitude = (result or {}).get("latitude")
            self._latitude = float(latitude) if latitude is not None else None
            logger.info("HA home latitude: %s", self._latitude)
        except Exception:
            logger.warning(
                "Could not fetch HA latitude — internal ET₀ calculation unavailable",
                exc_info=True,
            )

    async def _message_loop(self, ws: ClientConnection) -> None:
        async for raw in ws:
            try:
                await self._dispatch(json.loads(raw))
            except Exception:
                logger.exception("Error dispatching HA message")

    async def _dispatch(self, msg: dict[str, Any]) -> None:
        match msg.get("type"):
            case "result":
                fut = self._pending.pop(msg["id"], None)
                if fut and not fut.done():
                    if msg.get("success"):
                        fut.set_result(msg.get("result"))
                    else:
                        fut.set_exception(HAError(msg.get("error", {})))
            case "event":
                event = msg.get("event", {})
                if event.get("event_type") == "state_changed":
                    data = event["data"]
                    entity_id: str = data["entity_id"]
                    new_state: dict[str, Any] | None = data.get("new_state")
                    if new_state:
                        self._state_cache[entity_id] = new_state
                        if self._state_callbacks:
                            # One task per event (not per callback): the callbacks
                            # still run concurrently, but the fan-out is bounded to a
                            # single task per state change instead of one × every
                            # registered subscriber.
                            self._spawn(
                                self._run_callbacks(entity_id, new_state),
                                name=f"state-cbs-{entity_id}",
                            )

    async def _run_callbacks(self, entity_id: str, new_state: dict[str, Any]) -> None:
        """Run every registered state callback concurrently for one event.

        A failure in one callback must not prevent the others from running, so
        results are gathered with ``return_exceptions=True`` and any exception is
        logged rather than propagated."""
        results = await asyncio.gather(
            *(cb(entity_id, new_state) for cb in self._state_callbacks),
            return_exceptions=True,
        )
        for result in results:
            if isinstance(result, Exception):
                logger.exception("State callback failed for %s", entity_id, exc_info=result)

    # ── Command helper ────────────────────────────────────────────────────────

    def _next_id(self) -> int:
        self._msg_id += 1
        return self._msg_id

    async def _send_command(
        self,
        ws: ClientConnection,
        msg: dict[str, Any],
        timeout: float = 10.0,
    ) -> Any:
        msg_id = self._next_id()
        full = {**msg, "id": msg_id}
        fut: asyncio.Future[Any] = asyncio.get_running_loop().create_future()
        self._pending[msg_id] = fut
        await ws.send(json.dumps(full))
        try:
            return await asyncio.wait_for(fut, timeout=timeout)
        except TimeoutError as err:
            self._pending.pop(msg_id, None)
            raise HAError(
                {"message": f"Command timed out (id={msg_id}, type={msg.get('type')})"}
            ) from err
        except asyncio.CancelledError:
            self._pending.pop(msg_id, None)
            # Two distinct cancellations end up here. (a) The *caller's task* is being
            # cancelled (process shutdown) — propagate, so e.g. a run task keeps its
            # crash-recovery semantics. (b) Only the *future* was cancelled by
            # _mark_disconnected (HA dropped) — surface that as an HAError so callers'
            # `except Exception` retry paths (e.g. _safe_turn_off) handle it instead
            # of the BaseException silently killing their task.
            task = asyncio.current_task()
            if task is not None and task.cancelling():
                raise
            raise HAError(
                {"message": f"Connection lost (id={msg_id}, type={msg.get('type')})"}
            ) from None

    # ── Public API ────────────────────────────────────────────────────────────

    async def call_service(self, domain: str, service: str, **service_data: Any) -> Any:
        if not self._connected.is_set() or self._ws is None:
            raise HAError({"message": "Not connected to Home Assistant"})
        return await self._send_command(
            self._ws,
            {
                "type": "call_service",
                "domain": domain,
                "service": service,
                "service_data": service_data,
            },
        )

    async def get_services(self, domain: str | None = None) -> list[str]:
        """List available services as ``<domain>.<service>`` ids (optionally one domain).

        Services (e.g. ``notify.mobile_app_*``) are not entities and aren't in the
        state cache, so this issues a one-off ``get_services`` command.
        """
        if not self._connected.is_set() or self._ws is None:
            raise HAError({"message": "Not connected to Home Assistant"})
        result: dict[str, dict[str, Any]] = await self._send_command(
            self._ws, {"type": "get_services"}
        )
        services: list[str] = []
        for dom, svc_map in (result or {}).items():
            if domain is not None and dom != domain:
                continue
            services.extend(f"{dom}.{svc}" for svc in svc_map)
        services.sort()
        return services

    def get_state(self, entity_id: str) -> dict[str, Any] | None:
        return self._state_cache.get(entity_id)

    def get_state_value(self, entity_id: str) -> str | None:
        state = self._state_cache.get(entity_id)
        return state["state"] if state else None

    async def fetch_history_max(
        self, entity_id: str, start: datetime, end: datetime
    ) -> float | None:
        """Maximum numeric state of ``entity_id`` in ``[start, end)`` from the HA
        recorder, or None if there's no numeric history in the window."""
        if not self._connected.is_set() or self._ws is None:
            raise HAError({"message": "Not connected to Home Assistant"})
        result: dict[str, list[dict[str, Any]]] = await self._send_command(
            self._ws,
            {
                "type": "history/history_during_period",
                "start_time": start.isoformat(),
                "end_time": end.isoformat(),
                "entity_ids": [entity_id],
                "minimal_response": True,
                "no_attributes": True,
            },
            timeout=30.0,
        )
        values: list[float] = []
        for entry in (result or {}).get(entity_id, []):
            raw = entry.get("s", entry.get("state"))
            if raw is None:
                continue
            try:
                values.append(float(raw))
            except (TypeError, ValueError):
                continue  # ignore "unavailable"/"unknown"/non-numeric states
        return max(values) if values else None

    def get_cached_daily_max(self, entity_id: str) -> float | None:
        """Last refreshed max for ``entity_id`` (see ``refresh_daily_max``)."""
        return self._daily_max_cache.get(entity_id)

    async def refresh_daily_max(self, entity_id: str, start: datetime, end: datetime) -> None:
        """Refresh the cached max for ``entity_id`` over ``[start, end)``. Best-effort:
        a failed fetch leaves the previous cached value untouched."""
        try:
            self._daily_max_cache[entity_id] = await self.fetch_history_max(entity_id, start, end)
            logger.debug(
                "Refreshed daily max for %s: %s", entity_id, self._daily_max_cache[entity_id]
            )
        except Exception:
            logger.warning("Could not fetch history max for '%s'", entity_id, exc_info=True)

    def get_rain_confirmed_peak(self, entity_id: str) -> float | None:
        """The forecast peak for ``entity_id`` confirmed by actual rain today.

        The maximum value ``entity_id`` reached while the binary rain sensor was on
        (see ``refresh_rain_confirmed_peak``). Distinguishes:
          * ``None`` — not yet computed (no rain history, or fetch failed): callers
            should fall back to the unconfirmed peak (conservative).
          * ``0.0`` — computed, but it never rained today: today's peak is unconfirmed.
          * ``> 0`` — the highest forecast value that coincided with real rain.
        """
        return self._rain_confirmed_peak_cache.get(entity_id)

    def get_recent_rain_credit(self, entity_id: str) -> float | None:
        """Recent actual rain credit in mm for the water-balance rain mode."""
        return self._recent_rain_credit_cache.get(entity_id)

    async def refresh_recent_rain_credit(
        self,
        entity_id: str,
        start: datetime,
        end: datetime,
        decay: float,
        rain_entity: str | None = None,
    ) -> None:
        """Refresh recent actual rain credit from a numeric precipitation sensor.

        The sensor may be either daily-reset or total-increasing. Positive deltas
        count as rain; negative deltas are treated as resets and ignored. The final
        credit decays continuously with age (``decay ** age_in_days``, fractional
        days included) so Monday rain can still suppress a Wednesday run without
        lasting indefinitely. When ``rain_entity`` is set, deltas only count while
        that binary rain sensor is on.
        """
        try:
            samples = await self.fetch_history(entity_id, start, end)
            rain_hist = await self.fetch_history(rain_entity, start, end) if rain_entity else []
            current = self.get_state_value(entity_id)
            if current is not None:
                samples.append((end.timestamp(), str(current)))
            samples.sort(key=lambda s: s[0])
            if len(samples) < 2:
                self._recent_rain_credit_cache[entity_id] = 0.0
                return

            credit = 0.0
            for (_prev_ts, prev_raw), (cur_ts, cur_raw) in zip(samples, samples[1:], strict=False):
                try:
                    prev_val = float(prev_raw)
                    cur_val = float(cur_raw)
                except (TypeError, ValueError):
                    continue
                delta = cur_val - prev_val
                if delta <= 0:
                    continue
                if rain_entity and self._state_at(rain_hist, cur_ts, default="off") != "on":
                    continue
                age_days = max(0.0, (end.timestamp() - cur_ts) / 86400.0)
                credit += delta * (decay**age_days)
            self._recent_rain_credit_cache[entity_id] = round(credit, 2)
            logger.debug(
                "Refreshed recent rain credit for %s: %s",
                entity_id,
                self._recent_rain_credit_cache[entity_id],
            )
        except Exception:
            logger.warning(
                "Could not refresh recent rain credit for '%s'", entity_id, exc_info=True
            )

    @staticmethod
    def _state_at(samples: list[tuple[float, str]], timestamp: float, default: str) -> str:
        """Piecewise-constant state at ``timestamp`` for chronological HA samples."""
        state = default
        for ts, raw in samples:
            if ts > timestamp:
                break
            state = raw
        return state

    @property
    def latitude(self) -> float | None:
        """The HA home latitude, or None until fetched (see ``_load_ha_latitude``)."""
        return self._latitude

    def get_et0_balance(self) -> float | None:
        """Soil water balance in mm for the et0 rain mode (see ``refresh_et0_balance``)."""
        return self._et0_balance_mm

    def get_zone_balance(self, zone_id: str) -> float | None:
        """The et0_zonal soil balance (mm) for one zone, or None until computed."""
        return self._zone_balance_mm.get(zone_id)

    def get_et0_zonal_aggregate(self, zone_ids: list[str] | None = None) -> float | None:
        """Aggregate et0_zonal credit (mm): the most-depleted zone's balance, so
        the driest zone drives the adjustment.

        ``zone_ids`` restricts the aggregate to a single sequence's zones (the
        correct scope for that sequence's skip gate); None aggregates over every
        zone (a whole-install indicator for status/MQTT). Returns None until any
        of the requested zones has a computed balance.
        """
        if zone_ids is None:
            values = list(self._zone_balance_mm.values())
        else:
            values = [self._zone_balance_mm[z] for z in zone_ids if z in self._zone_balance_mm]
        return min(values) if values else None

    @staticmethod
    def _daily_rain_mm(
        samples: list[tuple[float, str]],
        day_bounds: list[tuple[float, float]],
        gate_samples: list[tuple[float, str]] | None,
    ) -> list[float]:
        """Rain per local day from a cumulative/daily-reset precipitation sensor.

        Positive deltas count as rain (negative ones are resets, like
        ``refresh_recent_rain_credit``); each delta is attributed to the day
        containing its sample timestamp. The last window is closed on the right
        so the appended live reading (timestamped exactly at the window end)
        still counts toward today. When ``gate_samples`` is given, deltas only
        count while that binary rain sensor was on.
        """
        rain = [0.0] * len(day_bounds)
        for (_prev_ts, prev_raw), (cur_ts, cur_raw) in zip(samples, samples[1:], strict=False):
            try:
                delta = float(cur_raw) - float(prev_raw)
            except (TypeError, ValueError):
                continue
            if delta <= 0:
                continue
            if gate_samples is not None and HAClient._state_at(gate_samples, cur_ts, "off") != "on":
                continue
            idx = day_index(cur_ts, day_bounds)
            if idx is not None:
                rain[idx] += delta
        return rain

    @staticmethod
    def _daily_numeric(
        samples: list[tuple[float, str]], day_bounds: list[tuple[float, float]]
    ) -> list[list[float]]:
        """Numeric sample values bucketed per day (non-numeric states skipped)."""
        values: list[list[float]] = [[] for _ in day_bounds]
        for ts, raw in samples:
            try:
                val = float(raw)
            except (TypeError, ValueError):
                continue
            for idx, (start, end) in enumerate(day_bounds):
                if start <= ts < end:
                    values[idx].append(val)
                    break
        return values

    async def refresh_et0_balance(
        self,
        *,
        day_bounds: list[tuple[datetime, datetime]],
        days_of_year: list[int],
        rain_entity: str | None,
        temperature_entity: str | None,
        et0_entity: str | None,
        reservoir_mm: float,
        fallback_decay: float,
        confirm_rain_entity: str | None = None,
    ) -> None:
        """Refresh the soil water balance for the et0 rain mode.

        ``day_bounds`` are UTC ``[start, end)`` windows of consecutive *local*
        days, oldest first; the last entry is today up to now. Per full day the
        balance gains the day's actual rain (positive sensor deltas, optionally
        gated on ``confirm_rain_entity``) and loses the day's ET₀: the value of
        ``et0_entity`` (its daily maximum) when configured, else the internal
        Hargreaves calculation from the temperature sensor's daily min/max and
        the HA latitude. A day with neither falls back to the multiplicative
        ``fallback_decay`` (the water-balance heuristic). Today only adds rain —
        its evaporation has mostly not happened yet at decision time, and the
        forecast side of the factor covers the day ahead. Best-effort: a failed
        refresh leaves the previous cached balance untouched.
        """
        from naiad.domain.et0 import BalanceDay, soil_balance_mm

        if not day_bounds:
            return
        try:
            daily_rain, daily_et0_ref = await self._daily_rain_and_reference_et0(
                day_bounds=day_bounds,
                days_of_year=days_of_year,
                rain_entity=rain_entity,
                temperature_entity=temperature_entity,
                et0_entity=et0_entity,
                confirm_rain_entity=confirm_rain_entity,
            )
            days: list[BalanceDay] = []
            last = len(daily_rain) - 1
            for idx in range(len(daily_rain)):
                # Today only adds rain — its evaporation has mostly not happened
                # yet, and the forecast side of the factor covers the day ahead.
                et0_mm = 0.0 if idx == last else daily_et0_ref[idx]
                days.append(BalanceDay(rain_mm=daily_rain[idx], et0_mm=et0_mm))

            self._et0_balance_mm = round(soil_balance_mm(days, reservoir_mm, fallback_decay), 2)
            logger.debug("Refreshed ET₀ balance: %s mm", self._et0_balance_mm)
        except Exception:
            logger.warning("Could not refresh ET₀ balance", exc_info=True)

    async def _daily_rain_and_reference_et0(
        self,
        *,
        day_bounds: list[tuple[datetime, datetime]],
        days_of_year: list[int],
        rain_entity: str | None,
        temperature_entity: str | None,
        et0_entity: str | None,
        confirm_rain_entity: str | None,
    ) -> tuple[list[float], list[float | None]]:
        """Shared history math for both et0 balance refreshes.

        Returns (daily rain mm, daily *reference* ET₀ mm) aligned to
        ``day_bounds`` (oldest first). The reference ET₀ is the ``et0_entity``
        daily maximum when configured, else the internal Hargreaves value from
        the temperature sensor's daily min/max and the HA latitude, else None
        (unknown — the balance then falls back to its decay heuristic for that
        day). The per-zone caller still scales it by each zone's crop coefficient.
        """
        from naiad.domain.et0 import extraterrestrial_radiation_mm, hargreaves_et0_mm

        start, end = day_bounds[0][0], day_bounds[-1][1]
        bounds_epoch = [(s.timestamp(), e.timestamp()) for s, e in day_bounds]

        rain_samples: list[tuple[float, str]] = []
        if rain_entity:
            rain_samples = await self.fetch_history(rain_entity, start, end)
            current = self.get_state_value(rain_entity)
            if current is not None:
                rain_samples.append((end.timestamp(), str(current)))
                rain_samples.sort(key=lambda s: s[0])
        gate_samples = (
            await self.fetch_history(confirm_rain_entity, start, end)
            if confirm_rain_entity
            else None
        )
        et0_samples = await self.fetch_history(et0_entity, start, end) if et0_entity else []
        temp_samples = (
            await self.fetch_history(temperature_entity, start, end)
            if temperature_entity and not et0_entity
            else []
        )

        daily_rain = self._daily_rain_mm(rain_samples, bounds_epoch, gate_samples)
        daily_et0_values = self._daily_numeric(et0_samples, bounds_epoch)
        daily_temps = self._daily_numeric(temp_samples, bounds_epoch)

        daily_et0_ref: list[float | None] = []
        for idx in range(len(bounds_epoch)):
            if daily_et0_values[idx]:
                daily_et0_ref.append(max(daily_et0_values[idx]))
            elif daily_temps[idx] and self._latitude is not None:
                ra_mm = extraterrestrial_radiation_mm(self._latitude, days_of_year[idx])
                daily_et0_ref.append(
                    hargreaves_et0_mm(min(daily_temps[idx]), max(daily_temps[idx]), ra_mm)
                )
            else:
                daily_et0_ref.append(None)
        return daily_rain, daily_et0_ref

    async def refresh_et0_zonal_balance(
        self,
        *,
        day_bounds: list[tuple[datetime, datetime]],
        days_of_year: list[int],
        rain_entity: str | None,
        temperature_entity: str | None,
        et0_entity: str | None,
        zones: list["ZoneBalanceInput"],
        fallback_decay: float,
        confirm_rain_entity: str | None = None,
    ) -> None:
        """Refresh per-zone soil water balances for the et0_zonal rain mode.

        Shares the rain/ET₀ history with ``refresh_et0_balance`` (fetched once),
        but per zone the reference ET₀ is scaled by the crop coefficient
        (ETc = Kc·ET₀), the zone's own irrigation is added as income, and the
        balance is clamped to the zone's reservoir. Today only adds rain and
        irrigation (see ``refresh_et0_balance``). Best-effort: a failed refresh
        leaves the previous cached balances untouched.
        """
        from naiad.domain.et0 import BalanceDay, soil_balance_mm

        if not day_bounds or not zones:
            return
        try:
            daily_rain, daily_et0_ref = await self._daily_rain_and_reference_et0(
                day_bounds=day_bounds,
                days_of_year=days_of_year,
                rain_entity=rain_entity,
                temperature_entity=temperature_entity,
                et0_entity=et0_entity,
                confirm_rain_entity=confirm_rain_entity,
            )
            last = len(daily_rain) - 1
            new_balances: dict[str, float] = {}
            for zone in zones:
                days: list[BalanceDay] = []
                for idx in range(len(daily_rain)):
                    ref = daily_et0_ref[idx]
                    if idx == last:
                        etc_mm: float | None = 0.0
                    elif ref is not None:
                        etc_mm = ref * zone.crop_coefficient
                    else:
                        etc_mm = None
                    irrigation = zone.irrigation_mm[idx] if idx < len(zone.irrigation_mm) else 0.0
                    days.append(
                        BalanceDay(rain_mm=daily_rain[idx], et0_mm=etc_mm, irrigation_mm=irrigation)
                    )
                new_balances[zone.zone_id] = round(
                    soil_balance_mm(days, zone.reservoir_mm, fallback_decay), 2
                )
            self._zone_balance_mm = new_balances
            logger.debug("Refreshed zonal ET₀ balances: %s", self._zone_balance_mm)
        except Exception:
            logger.warning("Could not refresh zonal ET₀ balance", exc_info=True)

    async def refresh_rain_confirmed_peak(
        self, forecast_entities: list[str], rain_entity: str, start: datetime, end: datetime
    ) -> None:
        """Recompute each forecast entity's rain-confirmed peak over ``[start, end)``.

        For every ``forecast_entities`` value, caches the maximum it reached while
        ``rain_entity`` was ``on`` — i.e. the forecast level that actually coincided
        with rain, not a spike the forecast merely predicted. Run on the same
        hourly/reconnect cadence as the forecast peak (and on rain transitions) so the
        window resets across local midnight. Best-effort: a failed fetch leaves the
        previous cached values untouched.
        """
        try:
            rain_hist = await self.fetch_history(rain_entity, start, end)
            for entity_id in forecast_entities:
                if not entity_id:
                    continue
                forecast_hist = await self.fetch_history(entity_id, start, end)
                peak = self._max_forecast_during_rain(forecast_hist, rain_hist)
                self._rain_confirmed_peak_cache[entity_id] = peak
                logger.debug("Refreshed rain-confirmed peak for %s: %s", entity_id, peak)
        except Exception:
            logger.warning(
                "Could not refresh rain-confirmed peak for %s", forecast_entities, exc_info=True
            )

    @staticmethod
    def _max_forecast_during_rain(
        forecast_hist: list[tuple[float, str]], rain_hist: list[tuple[float, str]]
    ) -> float | None:
        """Maximum forecast value over the intervals when rain was on.

        Both series are piecewise-constant state timelines of ``(timestamp, state)``.
        Merge them and sweep: a forecast value is a candidate only while the rain
        state is ``on``. Returns ``None`` when there is no rain history at all
        (unknown), ``0.0`` when there is rain history but it was never on (provably
        unconfirmed), else the confirmed peak.
        """
        if not rain_hist:
            return None
        events: list[tuple[float, str, str]] = [(ts, "f", s) for ts, s in forecast_hist]
        events += [(ts, "r", s) for ts, s in rain_hist]
        events.sort(key=lambda e: e[0])

        cur_forecast: float | None = None
        rain_on = False
        confirmed: float | None = None
        for _ts, kind, raw in events:
            if kind == "f":
                try:
                    cur_forecast = float(raw)
                except (TypeError, ValueError):
                    cur_forecast = None  # "unavailable"/"unknown" breaks the value
            else:
                rain_on = raw == "on"
            # State is piecewise-constant, so evaluating after each change visits every
            # distinct (value, rain) interval at least once.
            if rain_on and cur_forecast is not None:
                confirmed = cur_forecast if confirmed is None else max(confirmed, cur_forecast)
        return confirmed if confirmed is not None else 0.0

    async def fetch_history(
        self, entity_id: str, start: datetime, end: datetime
    ) -> list[tuple[float, str]]:
        """Recorder history of ``entity_id`` over ``[start, end)`` as ``(epoch, state)``
        samples in chronological order. Entries without a parseable timestamp or state
        are skipped."""
        if not self._connected.is_set() or self._ws is None:
            raise HAError({"message": "Not connected to Home Assistant"})
        result: dict[str, list[dict[str, Any]]] = await self._send_command(
            self._ws,
            {
                "type": "history/history_during_period",
                "start_time": start.isoformat(),
                "end_time": end.isoformat(),
                "entity_ids": [entity_id],
                "minimal_response": True,
                "no_attributes": True,
            },
            timeout=30.0,
        )
        samples: list[tuple[float, str]] = []
        for entry in (result or {}).get(entity_id, []):
            state = entry.get("s", entry.get("state"))
            if state is None:
                continue
            ts = _entry_timestamp(entry)
            if ts is None:
                continue
            samples.append((ts, str(state)))
        samples.sort(key=lambda s: s[0])
        return samples

    def list_entities(self, domain: str | None = None) -> list[dict[str, Any]]:
        """List cached entities (optionally filtered by domain) for the UI entity picker."""
        entities: list[dict[str, Any]] = []
        for entity_id, state in self._state_cache.items():
            entity_domain = entity_id.split(".", 1)[0]
            if domain is not None and entity_domain != domain:
                continue
            attributes = state.get("attributes", {})
            entities.append(
                {
                    "entity_id": entity_id,
                    "friendly_name": attributes.get("friendly_name"),
                    "state": state.get("state", ""),
                    "domain": entity_domain,
                }
            )
        entities.sort(key=lambda e: e["entity_id"])
        return entities

    def subscribe_state_changes(self, callback: StateCallback) -> None:
        self._state_callbacks.append(callback)

    @property
    def is_connected(self) -> bool:
        return self._connected.is_set()
