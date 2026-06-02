"""Smoke test for the FastAPI application lifespan.

The lifespan (``naiad.main._lifespan``) wires together config loading, the
scheduler, the sequence runner, the HA client and crash recovery. None of the
other tests exercise that startup path, so a regression that only surfaces at
process start — a missing module import, an undefined name, a renamed callback
signature — would otherwise sail through CI and only blow up at deploy time
(as a bare ``NameError: name 'asyncio' is not defined`` did).

It drives the real startup *and* shutdown with the HA websocket stubbed out, so
it stays hermetic (no network, temp data dir) while still importing and
executing every line of lifespan wiring. The lifespan context manager is entered
directly rather than via ``starlette.testclient.TestClient`` so the test needs no
``httpx`` dependency.
"""

from typing import Any

import pytest

import naiad.database as database
from naiad.ha_client import HAClient


@pytest.fixture
def isolated_app(tmp_path: Any, monkeypatch: pytest.MonkeyPatch) -> Any:
    # Hermetic data dir so create_tables()/get_engine() never touch the real /data
    # volume; reset the cached engine so the temp path actually takes effect.
    monkeypatch.setenv("NAIAD_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(database, "_engine", None)

    # Never open a real HA websocket during the smoke test. start() normally spawns
    # a background reconnect loop that would hammer localhost:8123; the no-ops keep
    # startup offline and make shutdown deterministic.
    async def _noop(self: HAClient) -> None:
        return None

    monkeypatch.setattr(HAClient, "start", _noop)
    monkeypatch.setattr(HAClient, "stop", _noop)

    import naiad.main as main

    return main.app


async def test_app_lifespan_starts_and_stops(isolated_app: Any) -> None:
    """The lifespan must complete startup and shutdown without raising.

    Entering the context runs lifespan startup; leaving it runs shutdown. A
    failure in either (e.g. a missing import in the recovery wiring) surfaces here
    as a test failure rather than a deploy-time crash.
    """
    async with isolated_app.router.lifespan_context(isolated_app):
        runner = isolated_app.state.runner
        # Startup wired the runner and started the scheduler.
        assert runner is not None
        assert isolated_app.state.scheduler.running
