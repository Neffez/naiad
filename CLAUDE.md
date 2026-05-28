# Naiad — Claude Code Rules

## Language

All code must be in English: variable names, function names, class names, comments, docstrings, log messages, error messages, API field names, database column names, configuration keys.

Exception: user-visible UI strings are managed through i18n (`src/frontend/src/i18n/locales/`). German (`de.json`) and English (`en.json`) are both included — do not hardcode display strings in components.

## Architecture

- **Backend**: Python 3.12, FastAPI, SQLModel, APScheduler — source at `src/backend/`
- **Frontend**: React + Vite + TypeScript, Tailwind CSS, shadcn/ui — source at `src/frontend/`
- **API contract**: `docs/openapi.yaml` is the source of truth. Frontend TypeScript types are generated from it via `openapi-typescript` — do not write types by hand.
- **Design reference**: `design/` contains the Claude Design prototype. Use it as the visual reference for components and layout. It is not a build input.

## Code style

- Python: follow `ruff` defaults (configured in `pyproject.toml`). Type-annotate all public functions.
- TypeScript: strict mode. No `any`. Prefer `const` over `let`.
- No inline styles in React components unless directly mirroring a design token from `naiad-tokens.css`.
- Tailwind classes for layout; CSS variables (`--n-*`) for brand colors and radii — do not hardcode hex values.

## Testing

- Backend unit tests in `src/backend/tests/` using pytest.
- Mock the HA client (`ha_client.py`) in all unit tests — never make real WebSocket calls in tests.
- Test all state machine paths: idle→running, running→paused, running→aborted (rain), running→aborted (watchdog).

## Security

- `HA_TOKEN` and `NAIAD_PASSWORD_HASH` come from environment variables only — never hardcode or log them.
- Bearer tokens must never be included in log output.
- Validate all user input at API boundaries with Pydantic models.

## Commits

Follow conventional commits: `feat:`, `fix:`, `chore:`, `docs:`, `test:`, `refactor:`.
