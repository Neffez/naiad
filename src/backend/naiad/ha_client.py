import asyncio
import contextlib
import json
import logging
from collections.abc import Callable, Coroutine
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

    async def _connect_loop(self) -> None:
        delay = 1.0
        while True:
            try:
                await self._connect()
                delay = 1.0
            except asyncio.CancelledError:
                raise
            except Exception:
                was_connected = self._connected.is_set()
                self._connected.clear()
                self._ws = None
                for fut in self._pending.values():
                    if not fut.done():
                        fut.cancel()
                self._pending.clear()
                if was_connected and self.on_connection_change:
                    self._spawn(self.on_connection_change(False), name="ha-conn-change")
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
                self._connected.clear()
                self._ws = None

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
                        for cb in self._state_callbacks:
                            self._spawn(cb(entity_id, new_state), name=f"state-cb-{entity_id}")

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

    def get_state(self, entity_id: str) -> dict[str, Any] | None:
        return self._state_cache.get(entity_id)

    def get_state_value(self, entity_id: str) -> str | None:
        state = self._state_cache.get(entity_id)
        return state["state"] if state else None

    def subscribe_state_changes(self, callback: StateCallback) -> None:
        self._state_callbacks.append(callback)

    @property
    def is_connected(self) -> bool:
        return self._connected.is_set()
