from fastapi import APIRouter, Depends
from sqlmodel import Session

from naiad.api.schemas import UpdatePreferencesRequest, UserPreferencesResponse
from naiad.database import get_session
from naiad.dependencies import require_auth
from naiad.domain.models import UserPreference

router = APIRouter(prefix="/preferences", tags=["preferences"])

_DEFAULTS = {"theme": "dark", "language": "de"}


def _get(session: Session, key: str) -> str:
    pref = session.get(UserPreference, key)
    return pref.value if pref is not None else _DEFAULTS[key]


def _set(session: Session, key: str, value: str) -> None:
    pref = session.get(UserPreference, key) or UserPreference(key=key, value="")
    pref.value = value
    session.add(pref)


@router.get("", response_model=UserPreferencesResponse)
async def get_preferences(
    _: None = Depends(require_auth),
    session: Session = Depends(get_session),
) -> UserPreferencesResponse:
    return UserPreferencesResponse(
        theme=_get(session, "theme"),
        language=_get(session, "language"),
    )


@router.patch("", response_model=UserPreferencesResponse)
async def update_preferences(
    body: UpdatePreferencesRequest,
    _: None = Depends(require_auth),
    session: Session = Depends(get_session),
) -> UserPreferencesResponse:
    if body.theme is not None:
        _set(session, "theme", body.theme)
    if body.language is not None:
        _set(session, "language", body.language)
    session.commit()
    return UserPreferencesResponse(
        theme=_get(session, "theme"),
        language=_get(session, "language"),
    )
