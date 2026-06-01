import pytest
from fastapi import HTTPException
from sqlmodel import Session, SQLModel, create_engine, select

from naiad.api.settings import clear_all_sequence_overrides, clear_sequence_override
from naiad.config import AppConfig
from naiad.domain.models import SequenceOverride


def _engine():
    eng = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(eng)
    return eng


@pytest.fixture(autouse=True)
def _no_broadcast(monkeypatch):
    """The delete endpoints broadcast over WS; stub it out in unit tests."""

    async def _noop() -> None:
        return None

    import naiad.api.ws as ws

    monkeypatch.setattr(ws, "broadcast_factor_updated", _noop)


async def test_clear_all_removes_every_override(minimal_config: AppConfig) -> None:
    eng = _engine()
    with Session(eng) as s:
        s.add(SequenceOverride(sequence_id="seq_1", basis_min_per_zone=12, paused=True))
        s.add(SequenceOverride(sequence_id="seq_wind", watchdog_min=99))
        s.commit()

    with Session(eng) as s:
        result = await clear_all_sequence_overrides(_=None, config=minimal_config, session=s)

    with Session(eng) as s:
        assert s.exec(select(SequenceOverride)).all() == []

    # Response reflects YAML defaults: no override values, paused False.
    assert result.sequences["seq_1"].basis_min_per_zone is None
    assert result.sequences["seq_1"].paused is False
    assert result.sequences["seq_wind"].watchdog_min is None


async def test_clear_single_leaves_others(minimal_config: AppConfig) -> None:
    eng = _engine()
    with Session(eng) as s:
        s.add(SequenceOverride(sequence_id="seq_1", basis_min_per_zone=12))
        s.add(SequenceOverride(sequence_id="seq_wind", paused=True))
        s.commit()

    with Session(eng) as s:
        await clear_sequence_override(sequence_id="seq_1", _=None, config=minimal_config, session=s)

    with Session(eng) as s:
        remaining = s.exec(select(SequenceOverride)).all()
        assert len(remaining) == 1
        assert remaining[0].sequence_id == "seq_wind"
        assert remaining[0].paused is True


async def test_clear_single_unknown_sequence_raises(minimal_config: AppConfig) -> None:
    eng = _engine()
    with Session(eng) as s, pytest.raises(HTTPException) as exc:
        await clear_sequence_override(
            sequence_id="does_not_exist",
            _=None,
            config=minimal_config,
            session=s,
        )
    assert exc.value.status_code == 404


async def test_clear_single_no_override_is_noop(minimal_config: AppConfig) -> None:
    eng = _engine()
    with Session(eng) as s:
        result = await clear_sequence_override(
            sequence_id="seq_1", _=None, config=minimal_config, session=s
        )
    # No row existed; call still succeeds and reports defaults.
    assert result.sequences["seq_1"].basis_min_per_zone is None
    assert result.sequences["seq_1"].paused is False


# ── Manual adjustment override ────────────────────────────────────────────────


async def test_manual_pct_clamped_to_temp_bounds(minimal_config: AppConfig) -> None:
    """Setting a manual percentage above max_pct pins it to the limit."""
    from naiad.api.schemas import FactorSettingsInput, UpdateSettingsRequest
    from naiad.api.settings import update_settings
    from naiad.domain.models import FactorOverride

    eng = _engine()
    with Session(eng) as s:
        body = UpdateSettingsRequest(
            factors=FactorSettingsInput(manual_mode=True, manual_pct=999)
        )
        result = await update_settings(body=body, _=None, config=minimal_config, session=s)

    # minimal_config temp max_pct = 150
    assert result.factors.manual_mode is True
    assert result.factors.manual_pct == 150

    with Session(eng) as s:
        fo = s.get(FactorOverride, 1)
        assert fo is not None
        assert fo.manual_pct == 150


async def test_manual_mode_toggle_off_persists(minimal_config: AppConfig) -> None:
    """Toggling manual_mode off keeps the stored manual_pct but disables it."""
    from naiad.api.schemas import FactorSettingsInput, UpdateSettingsRequest
    from naiad.api.settings import update_settings

    eng = _engine()
    with Session(eng) as s:
        await update_settings(
            body=UpdateSettingsRequest(
                factors=FactorSettingsInput(manual_mode=True, manual_pct=110)
            ),
            _=None,
            config=minimal_config,
            session=s,
        )
    with Session(eng) as s:
        result = await update_settings(
            body=UpdateSettingsRequest(factors=FactorSettingsInput(manual_mode=False)),
            _=None,
            config=minimal_config,
            session=s,
        )

    assert result.factors.manual_mode is False
    assert result.factors.manual_pct == 110
