from sqlmodel import Session, SQLModel, create_engine

from naiad.api.preferences import get_preferences, update_preferences
from naiad.api.schemas import UpdatePreferencesRequest


def _engine():
    eng = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(eng)
    return eng


async def test_defaults_when_unset() -> None:
    eng = _engine()
    with Session(eng) as s:
        prefs = await get_preferences(_=None, session=s)

    assert prefs.theme == "dark"
    assert prefs.language == "de"
    assert prefs.sequence_order == []
    assert prefs.zone_order == []


async def test_order_persists_and_round_trips() -> None:
    eng = _engine()
    with Session(eng) as s:
        await update_preferences(
            UpdatePreferencesRequest(sequence_order=["b", "a", "c"], zone_order=["z2", "z1"]),
            _=None,
            session=s,
        )

    with Session(eng) as s:
        prefs = await get_preferences(_=None, session=s)

    assert prefs.sequence_order == ["b", "a", "c"]
    assert prefs.zone_order == ["z2", "z1"]
    # Unrelated preferences keep their defaults.
    assert prefs.theme == "dark"


async def test_partial_update_leaves_other_keys_untouched() -> None:
    eng = _engine()
    with Session(eng) as s:
        await update_preferences(
            UpdatePreferencesRequest(sequence_order=["a", "b"]),
            _=None,
            session=s,
        )
    with Session(eng) as s:
        await update_preferences(
            UpdatePreferencesRequest(theme="light"),
            _=None,
            session=s,
        )

    with Session(eng) as s:
        prefs = await get_preferences(_=None, session=s)

    assert prefs.theme == "light"
    assert prefs.sequence_order == ["a", "b"]
