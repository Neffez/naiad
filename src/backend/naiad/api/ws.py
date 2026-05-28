import asyncio
import json
import logging
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sqlmodel import Session

from naiad.config import AppConfig
from naiad.domain.factors import compute_factors
from naiad.domain.models import AuthToken
from naiad.domain.sensors import read_sensor_snapshot
from naiad.domain.sequences import SequenceRunner
from naiad.ha_client import HAClient

logger = logging.getLogger(__name__)

router = APIRouter(tags=["ws"])

# ── Connection manager ────────────────────────────────────────────────────────

class WsManager:
    def __init__(self) -> None:
        self._connections: set[WebSocket] = set()

    def connect(self, ws: WebSocket) -> None:
        self._connections.add(ws)

    def disconnect(self, ws: WebSocket) -> None:
        self._connections.discard(ws)

    async def broadcast(self, msg: dict[str, Any]) -> None:
        if not self._connections:
            return
        data = json.dumps(msg, default=str)
        dead: list[WebSocket] = []
        for ws in self._connections:
            try:
                await ws.send_text(data)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self._connections.discard(ws)

    async def send(self, ws: WebSocket, msg: dict[str, Any]) -> None:
        await ws.send_text(json.dumps(msg, default=str))


manager = WsManager()


# ── Broadcast helpers (called from other modules) ─────────────────────────────

async def broadcast_sequence_changed(
    sequence_id: str, status: str, triggered_by: str = "manual",
) -> None:
    await manager.broadcast({
        "type": "sequence_changed",
        "data": {
            "sequence_id": sequence_id,
            "status": status,
            "triggered_by": triggered_by,
            "ts": datetime.now(UTC).isoformat(),
        },
    })


async def broadcast_valve_changed(zone_id: str, state: str, entity_id: str) -> None:
    await manager.broadcast({
        "type": "valve_changed",
        "data": {
            "zone_id": zone_id,
            "state": state,
            "entity_id": entity_id,
            "ts": datetime.now(UTC).isoformat(),
        },
    })


async def broadcast_notification(message: str, level: str = "info") -> None:
    await manager.broadcast({
        "type": "notification",
        "data": {
            "message": message,
            "level": level,
            "ts": datetime.now(UTC).isoformat(),
        },
    })


async def broadcast_factor_updated() -> None:
    await manager.broadcast({
        "type": "factor_updated",
        "data": {"ts": datetime.now(UTC).isoformat()},
    })


async def broadcast_ha_state(connected: bool) -> None:
    await manager.broadcast({
        "type": "ha_state",
        "data": {
            "connected": connected,
            "ts": datetime.now(UTC).isoformat(),
        },
    })


# ── Auth helper ───────────────────────────────────────────────────────────────

def _authenticate(token_str: str, session: Session) -> bool:
    db_token = session.get(AuthToken, token_str)
    if db_token is None:
        return False
    if db_token.expires_at.replace(tzinfo=UTC) < datetime.now(UTC):
        return False
    db_token.last_used_at = datetime.now(UTC)
    session.commit()
    return True


# ── Snapshot builders ─────────────────────────────────────────────────────────

def _status_snapshot(
    runner: SequenceRunner,
    ha: HAClient,
    config: AppConfig,
) -> dict[str, Any]:
    snapshot = read_sensor_snapshot(ha, config)
    factors = compute_factors(snapshot, config)
    status = runner.status()
    return {
        "type": "status_snapshot",
        "data": {
            "ha_connected": ha.is_connected,
            "sequence_running": status.sequence_id,
            "factor_pct": int(round(factors.factor_pct)),
            "season_off": factors.season_off,
            "wind_on": factors.wind_on,
            "temp_c": snapshot.temperature_c,
            "rain_mm": snapshot.precipitation_today_mm,
            "ts": datetime.now(UTC).isoformat(),
        },
    }


# ── Endpoint ──────────────────────────────────────────────────────────────────

@router.websocket("/ws")
async def websocket_endpoint(
    websocket: WebSocket,
) -> None:
    from sqlmodel import Session as _Session

    from naiad.database import get_engine

    await websocket.accept()

    # Auth handshake — first message must be {"type": "auth", "token": "..."}
    try:
        raw = await asyncio.wait_for(websocket.receive_text(), timeout=10.0)
        msg = json.loads(raw)
    except (TimeoutError, json.JSONDecodeError):
        await websocket.send_text(json.dumps({"type": "auth_failed", "detail": "Auth timeout"}))
        await websocket.close()
        return

    if msg.get("type") != "auth":
        await websocket.send_text(
            json.dumps({"type": "auth_failed", "detail": "Expected auth message"})
        )
        await websocket.close()
        return

    token_str: str = msg.get("token", "")

    app = websocket.app  # type: ignore[attr-defined]
    config: AppConfig = app.state.config
    runner: SequenceRunner = app.state.runner
    ha: HAClient = app.state.ha_client

    if config.auth.mode == "none":
        authed = True
    else:
        with _Session(get_engine()) as session:
            authed = _authenticate(token_str, session)

    if not authed:
        await websocket.send_text(
            json.dumps({"type": "auth_failed", "detail": "Token invalid or expired"})
        )
        await websocket.close()
        return

    await websocket.send_text(json.dumps({"type": "auth_ok"}))
    manager.connect(websocket)

    with _Session(get_engine()) as session:
        snapshot_msg = _status_snapshot(runner, ha, config)
    await manager.send(websocket, snapshot_msg)

    heartbeat_task = asyncio.create_task(_heartbeat(websocket, runner, ha, config))
    run_tick_task = asyncio.create_task(_run_tick(websocket, runner))

    try:
        while True:
            raw = await websocket.receive_text()
            try:
                client_msg = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if client_msg.get("type") == "ping":
                await websocket.send_text(json.dumps({"type": "pong"}))
    except WebSocketDisconnect:
        pass
    except Exception:
        logger.exception("WebSocket error")
    finally:
        heartbeat_task.cancel()
        run_tick_task.cancel()
        manager.disconnect(websocket)


async def _heartbeat(
    ws: WebSocket,
    runner: SequenceRunner,
    ha: HAClient,
    config: AppConfig,
) -> None:
    while True:
        await asyncio.sleep(30)
        try:
            msg = _status_snapshot(runner, ha, config)
            await manager.send(ws, msg)
        except Exception:
            break


async def _run_tick(ws: WebSocket, runner: SequenceRunner) -> None:
    while True:
        await asyncio.sleep(10)
        status = runner.status()
        if status.sequence_id is None or status.current_zone is None:
            continue
        z = status.current_zone
        elapsed = (datetime.now(UTC) - z.started_at).total_seconds() / 60.0
        remaining = max(0.0, z.duration_min - elapsed)
        try:
            await manager.send(ws, {
                "type": "run_tick",
                "data": {
                    "sequence_id": status.sequence_id,
                    "zone_id": z.zone_id,
                    "elapsed_min": round(elapsed, 2),
                    "remaining_min": round(remaining, 2),
                },
            })
        except Exception:
            break
