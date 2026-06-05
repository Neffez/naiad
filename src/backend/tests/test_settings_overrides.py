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
        body = UpdateSettingsRequest(factors=FactorSettingsInput(manual_mode=True, manual_pct=999))
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


# ── Auto-login reporting ──────────────────────────────────────────────────────


async def test_auto_login_response_falls_back_to_yaml(minimal_config: AppConfig) -> None:
    """With no DB preference, the settings response mirrors the YAML default
    rather than always reporting False (which misled the UI)."""
    from naiad.api.settings import get_settings

    minimal_config.auth.auto_login.enabled = True
    eng = _engine()
    with Session(eng) as s:
        result = await get_settings(_=None, config=minimal_config, session=s)
    assert result.auto_login_enabled is True


async def test_auto_login_db_pref_overrides_yaml(minimal_config: AppConfig) -> None:
    from naiad.api.settings import get_settings
    from naiad.domain.models import UserPreference

    minimal_config.auth.auto_login.enabled = True
    eng = _engine()
    with Session(eng) as s:
        s.add(UserPreference(key="auto_login_enabled", value="0"))
        s.commit()
    with Session(eng) as s:
        result = await get_settings(_=None, config=minimal_config, session=s)
    assert result.auto_login_enabled is False


# ── Rain peak_tomorrow override ───────────────────────────────────────────────


async def test_rain_peak_tomorrow_defaults_to_yaml(minimal_config: AppConfig) -> None:
    """With no override stored, the response reflects the YAML default (False)."""
    from naiad.api.settings import get_settings

    eng = _engine()
    with Session(eng) as s:
        result = await get_settings(_=None, config=minimal_config, session=s)
    assert result.factors.rain.peak_tomorrow is False


async def test_rain_peak_tomorrow_round_trips(minimal_config: AppConfig) -> None:
    """PATCHing peak_tomorrow persists it and is reflected on read-back."""
    from naiad.api.schemas import (
        FactorSettingsInput,
        RainFactorSettingsInput,
        UpdateSettingsRequest,
    )
    from naiad.api.settings import update_settings
    from naiad.domain.models import FactorOverride

    eng = _engine()
    with Session(eng) as s:
        body = UpdateSettingsRequest(
            factors=FactorSettingsInput(rain=RainFactorSettingsInput(peak_tomorrow=True))
        )
        result = await update_settings(body=body, _=None, config=minimal_config, session=s)
    assert result.factors.rain.peak_tomorrow is True

    with Session(eng) as s:
        fo = s.get(FactorOverride, 1)
        assert fo is not None
        assert fo.rain_peak_tomorrow is True


# ── Factor override reset ─────────────────────────────────────────────────────


async def test_clear_factors_group_leaves_other_group(minimal_config: AppConfig) -> None:
    """Resetting the temp group nulls only temp fields; rain stays overridden."""
    from naiad.api.settings import clear_factor_overrides
    from naiad.domain.models import FactorOverride

    eng = _engine()
    with Session(eng) as s:
        s.add(FactorOverride(id=1, temp_basis_c=18.0, rain_threshold_prob=55))
        s.commit()

    with Session(eng) as s:
        result = await clear_factor_overrides(
            group="temp", _=None, config=minimal_config, session=s
        )

    # The temp override is gone (falls back to base), the rain override survives.
    assert result.factors.temp_overridden is False
    assert result.factors.rain_overridden is True
    assert result.factors.rain.threshold_prob == 55

    with Session(eng) as s:
        fo = s.get(FactorOverride, 1)
        assert fo is not None
        assert fo.temp_basis_c is None
        assert fo.rain_threshold_prob == 55


async def test_clear_factors_all_removes_row(minimal_config: AppConfig) -> None:
    """Resetting both groups with no manual state drops the row entirely."""
    from naiad.api.settings import clear_factor_overrides
    from naiad.domain.models import FactorOverride

    eng = _engine()
    with Session(eng) as s:
        s.add(FactorOverride(id=1, temp_basis_c=18.0, rain_threshold_prob=55))
        s.commit()

    with Session(eng) as s:
        result = await clear_factor_overrides(group=None, _=None, config=minimal_config, session=s)

    assert result.factors.temp_overridden is False
    assert result.factors.rain_overridden is False

    with Session(eng) as s:
        assert s.get(FactorOverride, 1) is None


async def test_clear_factors_keeps_manual_state(minimal_config: AppConfig) -> None:
    """A reset clears factor overrides but never the separate manual adjustment."""
    from naiad.api.settings import clear_factor_overrides
    from naiad.domain.models import FactorOverride

    eng = _engine()
    with Session(eng) as s:
        s.add(FactorOverride(id=1, temp_basis_c=18.0, manual_mode=True, manual_pct=120))
        s.commit()

    with Session(eng) as s:
        result = await clear_factor_overrides(group=None, _=None, config=minimal_config, session=s)

    assert result.factors.temp_overridden is False
    assert result.factors.manual_mode is True
    assert result.factors.manual_pct == 120

    with Session(eng) as s:
        fo = s.get(FactorOverride, 1)
        assert fo is not None
        assert fo.temp_basis_c is None
        assert fo.manual_mode is True


async def test_clear_factors_no_override_is_noop(minimal_config: AppConfig) -> None:
    """Clearing with no override row present still succeeds and reports base."""
    from naiad.api.settings import clear_factor_overrides

    eng = _engine()
    with Session(eng) as s:
        result = await clear_factor_overrides(group=None, _=None, config=minimal_config, session=s)
    assert result.factors.temp_overridden is False
    assert result.factors.rain_overridden is False


# ── Token lifetime validation ─────────────────────────────────────────────────


@pytest.mark.parametrize("bad", [0, -1, 366])
def test_token_lifetime_out_of_range_rejected(bad: int) -> None:
    """A login must never mint an already-expired or effectively-permanent token."""
    from pydantic import ValidationError

    from naiad.api.schemas import UpdateSettingsRequest

    with pytest.raises(ValidationError):
        UpdateSettingsRequest(token_lifetime_days=bad)
