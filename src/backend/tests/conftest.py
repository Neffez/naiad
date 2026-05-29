import pytest

from naiad.config import AppConfig

MINIMAL_CONFIG_DATA = {
    "ha": {
        "url": "ws://localhost:8123/api/websocket",
        "token": "test_token",
    },
    # Explicit, reachable auth state. The AuthConfig default is mode="password"
    # with an empty password, which is a permanently-locked-out config (login
    # returns 503, require_auth rejects everything) — not a realistic fixture.
    "auth": {"mode": "none"},
    "sensors": {
        "rain": "binary_sensor.regen",
        "wind": "binary_sensor.windalarm",
        "season": "binary_sensor.jahreszeit",
        "temperature": "sensor.temperature",
        "precipitation_prob_today": "sensor.prec_prob_today",
        "precipitation_prob_tomorrow": "sensor.prec_prob_tomorrow",
        "precipitation_today": "sensor.prec_today",
        "precipitation_tomorrow": "sensor.prec_tomorrow",
    },
    "zones": {
        "zone_a": {"label": "Zone A", "switch": "switch.zone_a", "flow_lph": 500.0},
        "zone_b": {"label": "Zone B", "switch": "switch.zone_b", "flow_lph": 300.0},
    },
    "sequences": {
        "seq_1": {
            "label": "Sequence 1",
            "zones": ["zone_a"],
            "basis_min_per_zone": 30,
            "watchdog_min": 60,
            "schedule": {"cron": "0 6 * * *"},
        },
        "seq_wind": {
            "label": "Lawn",
            "zones": ["zone_b"],
            "basis_min_per_zone": 40,
            "watchdog_min": 60,
            "schedule": {"cron": "0 5 * * 1"},
            "wind_blocks": True,
        },
    },
}


@pytest.fixture
def minimal_config() -> AppConfig:
    return AppConfig.model_validate(MINIMAL_CONFIG_DATA)
