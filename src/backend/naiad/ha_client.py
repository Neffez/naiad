import asyncio
import contextlib
import json
import logging
from collections.abc import Callable, Coroutine
from datetime import datetime
from typing import Any

import websockets
import websockets.exceptions
from websockets.asyncio.client import ClientConnection

logger = logging.getLogger(__name__)

StateCallback = Callable[[str, dict[str, Any]], Coroutine[Any, Any, None]]


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
        # Whether the binary rain sensor has been "on" at any point today. Set live
        # by the rain callback and reconstructed from the recorder on refresh, so
        # synchronous callers (read_sensor_snapshot) can gate today's forecast peak.
        self._rain_confirmed_today: bool = False
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

    def get_rain_confirmed_today(self) -> bool:
        """Whether the binary rain sensor fired at any point today (see refresh)."""
        return self._rain_confirmed_today

    def set_rain_confirmed_today(self, value: bool) -> None:
        """Record a live rain-sensor transition (the callback calls this with True)."""
        self._rain_confirmed_today = value

    async def refresh_rain_confirmed_today(
        self, entity_id: str, start: datetime, end: datetime
    ) -> None:
        """Recompute ``rain_confirmed_today`` from the recorder over ``[start, end)``.

        True if the binary rain sensor was ``on`` at any point in the window. Run on
        the same hourly/reconnect cadence as the forecast peak so the window resets
        across local midnight. Best-effort: a failed fetch leaves the flag untouched.
        """
        try:
            confirmed = await self.fetch_history_contains_on(entity_id, start, end)
        except Exception:
            logger.warning("Could not fetch rain history for '%s'", entity_id, exc_info=True)
            return
        self._rain_confirmed_today = confirmed
        logger.debug("Refreshed rain_confirmed_today for %s: %s", entity_id, confirmed)

    async def fetch_history_contains_on(
        self, entity_id: str, start: datetime, end: datetime
    ) -> bool:
        """True if ``entity_id`` held state ``on`` at any point in ``[start, end)``."""
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
        for entry in (result or {}).get(entity_id, []):
            if entry.get("s", entry.get("state")) == "on":
                return True
        return False

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
