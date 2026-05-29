import asyncio

from naiad.api.ws import WsManager


class FakeWS:
    """Minimal WebSocket double that detects overlapping (concurrent) sends."""

    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.sent: list[str] = []
        self._in_send = False
        self.overlapped = False

    async def send_text(self, data: str) -> None:
        if self._in_send:
            self.overlapped = True  # a second send entered before the first finished
        self._in_send = True
        await asyncio.sleep(0)  # yield — would interleave if not serialized by a lock
        self._in_send = False
        if self.fail:
            raise RuntimeError("send failed")
        self.sent.append(data)


async def test_send_to_one_socket_is_serialized() -> None:
    mgr = WsManager()
    ws = FakeWS()
    mgr.connect(ws)  # type: ignore[arg-type]

    await asyncio.gather(*(mgr.send(ws, {"i": i}) for i in range(25)))  # type: ignore[arg-type]

    assert ws.overlapped is False  # the per-connection lock prevented concurrent writes
    assert len(ws.sent) == 25


async def test_broadcast_serializes_with_concurrent_send() -> None:
    mgr = WsManager()
    ws = FakeWS()
    mgr.connect(ws)  # type: ignore[arg-type]

    await asyncio.gather(
        mgr.broadcast({"type": "a"}),
        mgr.send(ws, {"type": "b"}),  # type: ignore[arg-type]
        mgr.broadcast({"type": "c"}),
    )

    assert ws.overlapped is False
    assert len(ws.sent) == 3


async def test_broadcast_drops_failed_connection() -> None:
    mgr = WsManager()
    good, bad = FakeWS(), FakeWS(fail=True)
    mgr.connect(good)  # type: ignore[arg-type]
    mgr.connect(bad)  # type: ignore[arg-type]

    await mgr.broadcast({"x": 1})

    assert good.sent  # healthy connection received the message
    assert good in mgr._locks
    assert bad not in mgr._locks  # failed connection was dropped


async def test_send_to_unknown_connection_returns_false() -> None:
    mgr = WsManager()
    ws = FakeWS()
    assert await mgr.send(ws, {"x": 1}) is False  # type: ignore[arg-type]


async def test_send_returns_false_when_send_raises() -> None:
    mgr = WsManager()
    ws = FakeWS(fail=True)
    mgr.connect(ws)  # type: ignore[arg-type]
    assert await mgr.send(ws, {"x": 1}) is False  # type: ignore[arg-type]
