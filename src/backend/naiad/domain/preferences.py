"""Shared accessors for the master on/off switch.

The master switch is a single ``UserPreference`` row read from several places
(the scheduler's run gate and the REST status/start paths). Centralizing the
read/write here keeps the "absent means on" default in one spot instead of being
reimplemented at every call site.
"""

from sqlmodel import Session

from naiad.domain.models import UserPreference

_MASTER_KEY = "master_on"


def read_master_on(session: Session) -> bool:
    """True if watering is enabled. A missing preference defaults to on."""
    pref = session.get(UserPreference, _MASTER_KEY)
    return pref is None or pref.value == "1"


def set_master_on(session: Session, value: bool) -> None:
    """Persist the master switch state."""
    pref = session.get(UserPreference, _MASTER_KEY)
    if pref is None:
        pref = UserPreference(key=_MASTER_KEY, value="1" if value else "0")
    else:
        pref.value = "1" if value else "0"
    session.add(pref)
    session.commit()
