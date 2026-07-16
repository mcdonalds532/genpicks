---
name: verify
description: How to run and drive the GenPicks API and frontend locally to verify changes at their real surface.
---

# Verifying GenPicks changes

## API (FastAPI)

Launch against the committed local SQLite data (full real dataset, no setup):

```bash
./.venv/Scripts/python -m uvicorn genpicks.api.main:app --port 8123 > api.log 2>&1 &
```

- Default `GENPICKS_DATABASE_URL` is `sqlite:///data/genpicks.db` (relative — run from repo root).
- Logs are JSON lines (one per request via `genpicks.api` logger; uvicorn output rides the same formatter). `/health` requests are deliberately not logged.
- Good drive targets: `/health`, `/matches/upcoming?limit=2`, `/matches/{id}/markets` (locked without internal key), `/track-record`.
- To force a 500: point `GENPICKS_DATABASE_URL` at a nonexistent/empty SQLite path and hit `/matches/upcoming`.
- Sentry init is gated on `GENPICKS_SENTRY_DSN`; a well-formed dummy DSN (`https://<32 hex>@o000000.ingest.sentry.io/0000000`) starts cleanly for testing.
- Kill with `taskkill //PID <pid> //F` (PID is in the first startup log line).

## Frontend (Next.js)

```bash
cd web && npm run dev   # expects API on :8000, else set API_URL
```

## Gotchas

- Windows + Git Bash: `taskkill` needs doubled slashes for flags.
- The `.env` at repo root is loaded by pydantic-settings; env vars you pass inline override it.
