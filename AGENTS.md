# Naiad — Codex Rules

## Language

All code must be in English: variable names, function names, class names, comments, docstrings, log messages, error messages, API field names, database column names, configuration keys.

Exception: user-visible UI strings are managed through i18n (`src/frontend/src/i18n/locales/`). German (`de.json`) and English (`en.json`) are both included — do not hardcode display strings in components.

## Architecture

- **Backend**: Python 3.12, FastAPI, SQLModel, APScheduler — source at `src/backend/`
- **Frontend**: React + Vite + TypeScript, custom CSS design system (`naiad-tokens.css`), TanStack React Query, react-i18next — source at `src/frontend/`
- **API contract**: `docs/openapi.yaml` is the reference specification. Frontend TypeScript types live in `src/frontend/src/api/client.ts` alongside the fetch wrappers.
- **Design reference**: `design/` contains the Codex Design prototype. Use it as the visual reference for components and layout. It is not a build input.

## Code style

- Python: follow `ruff` defaults (configured in `pyproject.toml`). Type-annotate all public functions.
- TypeScript: strict mode. No `any`. Prefer `const` over `let`.
- React components use inline styles referencing CSS custom properties (`var(--n-*)`) from `naiad-tokens.css`. This mirrors the design prototype in `design/`. Utility class names (`n-card`, `n-btn`, `n-chip`, etc.) are defined in `index.css`.
- Do not hardcode hex color values — always use `--n-*` tokens. Exception: sequence accent colors that are data-driven.

## Testing

- Backend unit tests in `src/backend/tests/` using pytest.
- Mock the HA client (`ha_client.py`) in all unit tests — never make real WebSocket calls in tests.
- Test all state machine paths: idle→running, running→paused, running→aborted (rain), running→aborted (watchdog).
- Frontend unit tests live alongside the code as `*.test.ts`/`*.test.tsx` files under `src/frontend/src/`, using Vitest. Run them with `npm test` (`vitest run`) or `npm run test:watch` during development.
- Both backend (pytest) and frontend (vitest) tests run on every CI pass — see `.github/workflows/ci.yml`.

## Security

- `HA_TOKEN` and `NAIAD_PASSWORD_HASH` come from environment variables only — never hardcode or log them.
- Bearer tokens must never be included in log output.
- Validate all user input at API boundaries with Pydantic models.

## Commits

Follow conventional commits: `feat:`, `fix:`, `chore:`, `docs:`, `test:`, `refactor:`.

A `pre-commit` hook enforces the linters/formatters on every commit (CI fails
the build otherwise). After cloning, install it once:

```
pip install pre-commit   # if not already available
pre-commit install
```

The hook (`.pre-commit-config.yaml`) runs:
- Backend: `ruff` (with `--fix`), `ruff-format`, `mypy`.
- Frontend: `eslint` and `tsc -b`.

To run it manually without committing: `pre-commit run --all-files`. If a commit
is ever made in an environment where the hook is not installed, run the checks by
hand first: `ruff format . && ruff check .` (in `src/backend/`) and
`npm run lint && npx tsc -b` (in `src/frontend/`).
