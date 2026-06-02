"""Minimal server-side i18n for user-facing notifications.

Notifications are pushed to Home Assistant (phones) and broadcast in-app, so the
final text has to be rendered on the server — unlike the frontend, which renders
its own UI through i18next. This module carries a small message catalog and a
``t()`` helper for exactly those server-side strings.

The active language comes from :attr:`naiad.config.AppConfig.language`
(default English). Anything missing in the selected language falls back to the
``DEFAULT_LANGUAGE``, and an unknown key falls back to the key itself, so a
notification is never lost.
"""

from typing import Any

DEFAULT_LANGUAGE = "en"

# One catalog per supported language. Keys are dotted (``category.event``) and
# templates use ``str.format`` placeholders so callers pass named parameters.
_MESSAGES: dict[str, dict[str, str]] = {
    "en": {
        "trigger.cron": "schedule",
        "trigger.plan": "planned",
        "trigger.manual": "manual",
        "skip.wind": "⚠️ {label}: wind — run skipped",
        "skip.zero_factor": "💧 {label}: factor 0 % — run skipped",
        "skip.conflict_sequence": "⚠️ Schedule conflict: {label} skipped — {running} still running",
        "skip.conflict_zone": "⚠️ Schedule conflict: zone {label} skipped — {running} still running",
        "start.sequence": "🌿 {label} started ({trigger}, factor {pct} %)",
        "start.zone": "🌿 Zone {label} started ({trigger}, {minutes} min)",
        "abort.paused_rain": "🌧 Paused run discarded: rain ({label})",
        "abort.rain": "🌧 Watering stopped: rain ({label})",
        "abort.watchdog": "🚨 Watchdog: {label} — zone {zone} ran too long, stopped.",
        "abort.staircase_failed": (
            "⚠️ {label} ended early — zone {zone}: the actuator stopped responding "
            "(staircase re-trigger failed)."
        ),
        "reminder.header": "💦🌱 Tomorrow:",
        "reminder.line": "• {time} {label}",
        "reminder.planned": "{label} (planned)",
        "test.notification": "🌿 Naiad: test notification — if you see this, notifications work.",
    },
    "de": {
        # How a run was triggered — embedded into the start messages below.
        "trigger.cron": "Zeitplan",
        "trigger.plan": "geplant",
        "trigger.manual": "manuell",
        # Skips (deterministic refusals)
        "skip.wind": "⚠️ {label}: Wind — Lauf übersprungen",
        "skip.zero_factor": "💧 {label}: Faktor 0 % — Lauf übersprungen",
        "skip.conflict_sequence": (
            "⚠️ Zeitplan-Konflikt: {label} übersprungen — {running} läuft noch"
        ),
        "skip.conflict_zone": (
            "⚠️ Zeitplan-Konflikt: Zone {label} übersprungen — {running} läuft noch"
        ),
        # Starts
        "start.sequence": "🌿 {label} gestartet ({trigger}, Faktor {pct} %)",
        "start.zone": "🌿 Zone {label} gestartet ({trigger}, {minutes} min)",
        # Aborts
        "abort.paused_rain": "🌧 Pausierte Bewässerung verworfen: Regen ({label})",
        "abort.rain": "🌧 Bewässerung gestoppt: Regen ({label})",
        "abort.watchdog": "🚨 Watchdog: {label} — Zone {zone} lief zu lange, gestoppt.",
        "abort.staircase_failed": (
            "⚠️ {label} vorzeitig beendet — Zone {zone}: Aktor reagierte nicht "
            "(Treppenlicht-Re-Trigger fehlgeschlagen)."
        ),
        # Nightly reminder
        "reminder.header": "💦🌱 Morgen:",
        "reminder.line": "• {time} {label}",
        "reminder.planned": "{label} (geplant)",
        # Notify self-test
        "test.notification": (
            "🌿 Naiad: Testbenachrichtigung — wenn du das siehst, funktionieren Benachrichtigungen."
        ),
    },
}


def t(key: str, lang: str = DEFAULT_LANGUAGE, **params: Any) -> str:
    """Render message *key* in *lang*, formatted with *params*.

    Falls back to English for an unknown language or a key missing in *lang*, and
    to the raw key if it is unknown everywhere — a notification is never dropped
    just because a translation is missing.
    """
    catalog = _MESSAGES.get(lang, _MESSAGES[DEFAULT_LANGUAGE])
    template = catalog.get(key) or _MESSAGES[DEFAULT_LANGUAGE].get(key, key)
    try:
        return template.format(**params)
    except (KeyError, IndexError):
        return template
