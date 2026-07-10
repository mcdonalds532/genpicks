# GenPicks web

Next.js (App Router) frontend for [GenPicks](../README.md): fixtures, match
detail with model-vs-market odds, the prediction track record, GitHub
sign-in, and the demo-paywalled player try-scorer markets.

## Development

Runs against the FastAPI serving layer (see the root README for how to
start it):

```powershell
npm install
npm run dev   # http://localhost:3000
```

## Environment

Set in `.env.local` for dev, in Vercel project settings for prod:

| Variable | Purpose |
|---|---|
| `API_URL` | FastAPI base URL (defaults to `http://localhost:8000`) |
| `AUTH_SECRET` | Auth.js JWT signing secret (`npx auth secret`) |
| `AUTH_GITHUB_ID` / `AUTH_GITHUB_SECRET` | GitHub OAuth app credentials |
| `GENPICKS_INTERNAL_API_KEY` | Shared secret for the internal user-sync and entitlement endpoints on the API |

## Deployment

Deployed on Vercel with root directory `web/`. See the root README's
Deployment section for the full picture (API on Render, Postgres on Neon,
weekly GitHub Actions refresh).
