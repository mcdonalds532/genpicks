# GenPicks

Machine-learning predictions for NRL matches: win probabilities, anytime
try-scorer and first try-scorer probabilities per player, converted to implied
betting odds and compared against live market prices.

**Status: phase 1 — data foundations.**

## Architecture

- **Data pipeline** (Python): scrapers write raw payloads to `data/raw/`, an
  idempotent transform validates and loads them into the relational schema.
  The clean database is always rebuildable from raw.
- **Database** (PostgreSQL in production, SQLite for local dev): normalized
  schema in `src/genpicks/db/models.py`, migrations via Alembic. Teams,
  venues, and players each have alias tables so differently-named source
  records (sponsor renames, "J. Tedesco" vs "James Tedesco") resolve to one
  canonical entity.
- **Models** (XGBoost / Poisson): match winner, team try rates, player try
  share; calibrated probabilities benchmarked against bookmaker closing odds.
- **Odds ingestion**: Betfair Exchange API (free delayed key, primary) and
  TAB JSON API (secondary), snapshotted into `odds_snapshots`.
- **Serving**: FastAPI reads precomputed rows from `predictions`; Next.js
  frontend on Vercel. Weekly refresh via GitHub Actions.

## Local setup

```powershell
py -3.11 -m venv .venv
.venv\Scripts\python -m pip install -e ".[dev]"
copy .env.example .env
.venv\Scripts\alembic upgrade head   # creates data/genpicks.db
.venv\Scripts\python -m pytest
```

To use Postgres instead, start it (`docker compose up -d db` or a free
Neon/Supabase instance) and set `GENPICKS_DATABASE_URL` in `.env`.

## Roadmap

1. ~~Foundations: repo, schema, migrations~~
2. Data pipeline: scrapers, raw landing zone, validated transforms, backfill ~10 seasons
3. Match-winner model with calibration, backtested against bookmaker closing odds
4. Try-scorer models (team Poisson rates × player shares; first-try derived)
5. FastAPI serving layer with weekly batch prediction jobs
6. Next.js frontend: fixtures, match detail, prediction track record
7. Odds pollers (Betfair, TAB) and model-vs-market edge display
8. Auth + Stripe subscription gating
9. Deployment, docs, responsible-gambling disclaimer

> GenPicks is a portfolio project for educational purposes and does not
> provide betting advice.
