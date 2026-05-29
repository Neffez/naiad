"""Database-backed configuration store.

Once seeded, the SQLite database — not ``config.yaml`` — is the source of truth
for the full Naiad configuration, so it can be edited from the UI at runtime
(Phase 6a). ``config.yaml`` becomes an optional first-boot seed and an
import/export format.

Secrets (``ha.token``, ``auth.password``) are never written to the database:
they are stripped before persistence and re-injected from the environment on
load. This mirrors the rule that ``HA_TOKEN`` and ``NAIAD_PASSWORD_HASH`` come
from environment variables only.
"""

import json
import logging
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

from sqlmodel import Session

from naiad.config import AppConfig, load_config
from naiad.domain.models import ConfigDocument

logger = logging.getLogger(__name__)

SessionFactory = Callable[[], Session]


def _strip_secrets(config: AppConfig) -> dict[str, Any]:
    """Serialize an AppConfig to a JSON-ready dict with secret fields blanked."""
    data = config.model_dump(mode="json")
    data["ha"]["token"] = ""
    data.setdefault("auth", {})["password"] = ""
    return data


def to_export_dict(config: AppConfig) -> dict[str, Any]:
    """Return a JSON/YAML-ready config dict with secrets blanked (for export)."""
    return _strip_secrets(config)


def _inject_secrets(data: dict[str, Any]) -> dict[str, Any]:
    """Re-inject environment-managed secrets into a persisted config dict."""
    data.setdefault("ha", {})["token"] = os.environ.get("HA_TOKEN", "")
    password = os.environ.get("NAIAD_PASSWORD_HASH", "")
    if password:
        data.setdefault("auth", {})["password"] = password
    return data


def load_config_doc(session: Session) -> AppConfig | None:
    """Return the persisted configuration, or None if the store is empty."""
    row = session.get(ConfigDocument, 1)
    if row is None:
        return None
    data = _inject_secrets(json.loads(row.data))
    return AppConfig.model_validate(data)


def save_config_doc(session: Session, config: AppConfig) -> None:
    """Persist a (validated) configuration, stripping secrets first."""
    payload = json.dumps(_strip_secrets(config))
    row = session.get(ConfigDocument, 1)
    if row is None:
        session.add(ConfigDocument(id=1, data=payload))
    else:
        row.data = payload
        session.add(row)
    session.commit()


_SENSOR_KEYS = (
    "rain",
    "wind",
    "season",
    "temperature",
    "precipitation_prob_today",
    "precipitation_prob_tomorrow",
    "precipitation_today",
    "precipitation_tomorrow",
)


def build_bootstrap_config() -> AppConfig:
    """A minimal valid configuration for a zero-config first boot.

    HA connection comes from the environment (or the app's supervisor wiring);
    sensors/zones/sequences start empty and are filled in via the UI.

    Auth starts as ``none`` so the UI is reachable immediately without a password
    (there is no password yet to log in with). The user secures it from the UI /
    environment afterwards; the app (Phase 6c) uses ingress-trust instead.
    """
    return AppConfig.model_validate(
        {
            "ha": {
                "url": os.environ.get("HA_URL", "ws://homeassistant.local:8123/api/websocket"),
                "token": os.environ.get("HA_TOKEN", ""),
            },
            "auth": {"mode": "none"},
            "sensors": dict.fromkeys(_SENSOR_KEYS, ""),
            "zones": {},
            "sequences": {},
        }
    )


def load_or_seed_config(
    session_factory: SessionFactory, yaml_path: Path | None = None
) -> AppConfig:
    """Load the configuration from the database, seeding it on first boot.

    Resolution order:
      1. A persisted config document → use it (database is source of truth).
      2. Otherwise, seed from ``config.yaml`` if one exists.
      3. Otherwise, start empty — a minimal config that is then filled in via the UI.

    config.yaml is therefore entirely optional; it is only a convenience seed.
    """
    with session_factory() as session:
        config = load_config_doc(session)
        if config is not None:
            logger.info("Configuration loaded from database")
            return config

    path = yaml_path or Path(os.environ.get("NAIAD_CONFIG", "/data/config.yaml"))
    if path.exists():
        config = load_config(path)
        with session_factory() as session:
            save_config_doc(session, config)
        logger.info("Configuration seeded from YAML into database")
        return config

    config = build_bootstrap_config()
    with session_factory() as session:
        save_config_doc(session, config)
    logger.info("No config found — started with an empty configuration (configure it in the UI)")
    return config
