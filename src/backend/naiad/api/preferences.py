import json

from fastapi import APIRouter, Depends
from sqlmodel import Session

from naiad.api.schemas import UpdatePreferencesRequest, UserPreferencesResponse
from naiad.database import get_session
from naiad.dependencies import require_auth
from naiad.domain.models import UserPreference

router = APIRouter(prefix="/preferences", tags=["preferences"])

# The theme is deliberately not a server preference: it is a per-device choice
# kept in the browser's localStorage by the frontend.
_DEFAULTS = {"language": "de"}

# Preference keys whose value is a JSON-encoded list of entity IDs (display order).
_ORDER_KEYS = ("sequence_order", "zone_order")


def _get(session: Session, key: str) -> str:
    pref = session.get(UserPreference, key)
    return pref.value if pref is not None else _DEFAULTS[key]


def _get_order(session: Session, key: str) -> list[str]:
    pref = session.get(UserPreference, key)
    if pref is None:
        return []
    try:
        value = json.loads(pref.value)
    except (ValueError, TypeError):
        return []
    return [str(item) for item in value] if isinstance(value, list) else []


def _set(session: Session, key: str, value: str) -> None:
    pref = session.get(UserPreference, key) or UserPreference(key=key, value="")
    pref.value = value
    session.add(pref)


def _response(session: Session) -> UserPreferencesResponse:
    return UserPreferencesResponse(
        language=_get(session, "language"),
        sequence_order=_get_order(session, "sequence_order"),
        zone_order=_get_order(session, "zone_order"),
    )


@router.get("", response_model=UserPreferencesResponse)
async def get_preferences(
    _: None = Depends(require_auth),
    session: Session = Depends(get_session),
) -> UserPreferencesResponse:
    return _response(session)


@router.patch("", response_model=UserPreferencesResponse)
async def update_preferences(
    body: UpdatePreferencesRequest,
    _: None = Depends(require_auth),
    session: Session = Depends(get_session),
) -> UserPreferencesResponse:
    if body.language is not None:
        _set(session, "language", body.language)
    for key in _ORDER_KEYS:
        value = getattr(body, key)
        if value is not None:
            _set(session, key, json.dumps(value))
    session.commit()
    return _response(session)
