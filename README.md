# GenPicks

Machine-learning predictions for NRL matches: win probabilities, anytime
try-scorer and first try-scorer probabilities per player, converted to implied
betting odds and compared against live market prices.

**Live at [genpicks.vercel.app](https://genpicks.vercel.app)** — full data
pipeline (2016–2026, four sources), trained models, serving API, Next.js
frontend, live market odds, and official team lists driving the player
markets, refreshed weekly by GitHub Actions. Next: auth + payments.

Headline numbers on the held-out 2024–26 test seasons:

- match winner: **0.6498 log loss vs 0.6454 for bookmaker closing odds**
  (Elo-only 0.6533, always-home 0.6821), 557 matches
- first try scorer: top-1 hit rate 9.0%, top-3 24.3% (uniform lineup: 2.9%),
  534 matches with verified try order
- anytime try: log loss 0.4253 over 20,396 player-appearances, well
  calibrated below 50%

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
- **Odds ingestion**: The Odds API (free tier, 11 Australian bookmakers),
  polled into timestamped raw snapshots and replayed into `odds_snapshots`;
  aussportsbetting.com closing odds for the historical benchmark. (TAB and
  Betfair AU geo-block non-Australian IPs; polling them directly is a
  deployment-time option from an AU host.)
- **Team lists**: officially named lineups ingested from NRL.com each week;
  try-scorer predictions regenerate append-only when a projected lineup is
  superseded by the official one.
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

## Pipeline commands

```powershell
# download raw pages (cache-first; resumable; ~1h per source first time)
.venv\Scripts\python -m genpicks.scrape --seasons 2016-2026
.venv\Scripts\python -m genpicks.scrape --source nrl --seasons 2016-2026
# aussportsbetting closing odds: manual browser download to data\raw\asb\nrl.xlsx
# (the site is Cloudflare-protected; see src/genpicks/scrape/asb.py)

# load into the database — order matters: rlp creates canonical rows,
# nrl attaches stats/try order, asb attaches closing odds
.venv\Scripts\python -m genpicks.ingest --seasons 2016-2026
.venv\Scripts\python -m genpicks.ingest --source nrl --seasons 2016-2026
.venv\Scripts\python -m genpicks.ingest --source asb --seasons 2016-2026

# train (writes versioned artifacts + evaluation reports to data/models/)
.venv\Scripts\python -m genpicks.ml.train
.venv\Scripts\python -m genpicks.ml.train_tries

# weekly in-season: official team lists + live market odds
# (odds need GENPICKS_ODDS_API_KEY in .env — free key from the-odds-api.com)
.venv\Scripts\python -m genpicks.scrape --source nrl-teamlists --seasons 2026
.venv\Scripts\python -m genpicks.scrape --source oddsapi
.venv\Scripts\python -m genpicks.ingest --source nrl-teamlists --seasons 2026
.venv\Scripts\python -m genpicks.ingest --source oddsapi

# score upcoming fixtures (append-only predictions table) and serve
.venv\Scripts\python -m genpicks.ml.predict
.venv\Scripts\uvicorn genpicks.api.main:app

# frontend (web/): expects the API; set API_URL if not on :8000
cd web; npm install; npm run dev
```

## Deployment

| Piece | Where | Notes |
|---|---|---|
| Frontend | Vercel | root directory `web/`, `API_URL` env pointing at the API |
| API | Render (free tier, Docker) | `Dockerfile` at repo root; serving-only image, honors `$PORT`; needs `GENPICKS_DATABASE_URL` |
| Database | Neon Postgres (Sydney) | seeded once via `pg_dump`/`pg_restore` from a fully-ingested local Postgres |
| Refresh | GitHub Actions | `.github/workflows/weekly-refresh.yml` |

The weekly workflow runs Monday 22:00 UTC (settles the finished round's
results) and Wednesday 22:00 UTC (official team lists + fresh odds), then
rescores upcoming fixtures. It needs two repo secrets:
`GENPICKS_DATABASE_URL` and `GENPICKS_ODDS_API_KEY`. Every step is
idempotent, so manual `workflow_dispatch` runs are always safe. Model
artifacts are committed to the repo (< 1 MB per version), so CI scoring
loads them straight from checkout — training stays a local, deliberate act.

Free-tier trade-off: the Render instance sleeps after ~15 minutes idle and
cold-starts in under a minute; the first page load after a quiet period is
slow while the API wakes.

## Roadmap

1. ~~Foundations: repo, schema, migrations~~
2. ~~Data pipeline: scrapers, raw landing zone, validated transforms, backfill ~10 seasons~~
3. ~~Match-winner model with calibration, backtested against bookmaker closing odds~~
4. ~~Try-scorer models (team Poisson rates × player shares; first-try derived)~~
5. ~~FastAPI serving layer with batch prediction jobs~~
6. ~~Next.js frontend: fixtures, match detail, prediction track record~~
7. ~~Live odds (The Odds API) with model-vs-market display; official team lists~~
8. Auth + Stripe subscription gating
9. ~~Deployment (Neon + Render + Vercel + weekly GitHub Actions refresh)~~
10. Docs polish, responsible-gambling disclaimer page

> GenPicks is a portfolio project for educational purposes and does not
> provide betting advice.
