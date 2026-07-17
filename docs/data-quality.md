# Data-quality war stories

The models get the headlines, but most of the engineering in GenPicks went
into making four data sources agree about eleven seasons of rugby league.
This page records the failures that shaped the pipeline — each one found in
real data, and each one now encoded as a loader rule (usually with a test)
rather than a one-off fix.

The sources, for context: a community results archive
(rugbyleagueproject.org, "RLP") for match results and scoresheets, NRL.com
match centres for per-player statistics and try timelines,
aussportsbetting.com for historical closing odds, and The Odds API for live
market prices.

## The stadium that keeps changing its name

NRL venues are renamed for sponsors constantly, and NRL.com renames them
*retroactively* — a 2017 match served today carries the venue's 2026
sponsor name. So NRL.com is never trusted for venue history; RLP, which
preserves era-correct names, is the canonical venue source, and every
sponsor name ever seen becomes an alias pointing at the same venue row.

The twist that broke the "just alias the names" plan: two *different*
venues can share a name. The old Sydney Football Stadium and the rebuilt
one that replaced it are both "Allianz Stadium" on RLP, but they are
different buildings with different RLP ids. They stay separate venues with
disambiguated canonical names (`src/genpicks/ingest/resolve.py`) — which is
the correct call for home-ground and travel features, and the reason all
entity resolution here keys on stable source ids, never on display names.

## Three sources, three try counts

A 2017 match had 10 tries on RLP's curated scoresheet, 7 in NRL.com's
event timeline, and 5 in NRL.com's own stats table for the same match.
Old match centres are simply incomplete, and nothing in the payload tells
you so.

The rule that came out of it (`src/genpicks/ingest/nrl_loader.py`): RLP's
scoresheet is the authority on *how many* tries each team scored; the NRL
timeline — the only source of try order and minute — is trusted only when
its per-team totals reconcile exactly with RLP's. When they disagree, the
match keeps RLP's counts and gets **no try order at all**, because an
incomplete timeline would silently corrupt `scoring_order`. That costs
coverage (97.3% of played matches have verified-complete try order, mostly
missing pre-2019) and is still the right trade: a NULL is recoverable, a
plausible wrong value poisons the first-try-scorer training set.

## The player who became two people

A debutant can enter the database through NRL.com first: real minutes in
the match centre while RLP still lists him as an unused reserve. Weeks
later RLP catches up and credits him — under a fresh RLP id. Naive
get-or-create then mints a second `Player` row, and one human is suddenly
two players, each with half a career. Found on a full-replay shakedown as
Xavier Savage, round 15, 2021.

The fix is `adopt_orphan_player` (`src/genpicks/ingest/resolve.py`): before
creating a player for an unseen source id, look for an existing same-name
player that this source has never claimed, and adopt it instead; ambiguous
names decline and create nothing. It is wired into both arrival orders —
RLP-second (the weekly refresh) and NRL-second (a full replay) — because
the duplicate appears in either direction.

## Nobody agrees whose home game it is

At neutral venues — notably grand finals — the sources can disagree about
which team is the designated "home" side. The 2016 Grand Final reconciled
against nothing until match matching learned to retry with home and away
swapped (`src/genpicks/ingest/nrl_loader.py`,
`src/genpicks/ingest/oddsapi_loader.py`). The same swap-retry now protects
odds matching too, where a flipped designation would attach each team's
price to its opponent.

## Legal names vs preferred names

RLP records legal names; NRL.com uses preferred names, so the same player
arrives spelled two ways. Cross-source player reconciliation therefore
happens *inside an already-reconciled match*: match by full name first,
fall back to jersey number within that match. Between sources, players
alias only on numeric source ids — name collisions among the ~1,200
players in the dataset are not hypothetical.

## The kickoff times that were honestly unknowable

RLP publishes local dates, not UTC kickoffs. Converting needs a
venue-to-timezone map, and NRL edge cases make that map genuinely hard:
Las Vegas season openers, New Zealand home games, and Queensland's refusal
to observe daylight saving. Rather than guess, the schema gained a
`match_date` (local calendar date) column and left `kickoff_utc` NULL —
until NRL.com's JSON endpoints turned out to carry real UTC kickoffs back
to 2016, which filled the column properly. Same principle as the try
order: an honest NULL beats a plausible fabrication.

## Phantom appearances

NRL.com squads list 18 players including a non-playing reserve, and early
loader versions dutifully created zero-minute stat rows for them. Those
phantoms dilute every per-appearance rate the try-scorer model trains on,
so the loaders skip players with no minutes. Related: official pre-match
team lists name 22, of which jerseys 18+ are cover — prediction only
treats a lineup as "official" when at least 13 resolved players wear
jersey 17 or lower.

## The benchmark that quietly changed underneath

The historical closing-odds spreadsheet uses Sydney dates (so matches are
reconciled on teams plus date ± one day), and its closing-price bookmaker
changed twice across the decade — Pinnacle until April 2018, bet365 until
April 2024, BlueBet since (`src/genpicks/scrape/asb.py`). "The market"
the model is benchmarked against is therefore not one bookmaker over time,
which is worth knowing before reading too much into small per-era
differences.

## The principles all of this converges on

- **Raw payloads are immutable; loaders are idempotent.** Every scrape
  lands in `data/raw/` first, and the clean database is always rebuildable
  from raw. Every one of the bugs above was diagnosed by replaying raws.
- **Alias on stable source ids, never on display names.** Names are what
  sponsors, style guides, and the players themselves change.
- **Cross-source disagreement is signal.** Reconcile, and when
  reconciliation fails, record less data rather than wrong data.
- **Prefer NULL to a plausible guess.** NULLs are visible and fixable;
  fabricated values surface two models downstream as a mystery.
- **Encode the lesson where it recurs.** Each story above lives in a
  loader as a rule with a comment and, where practical, a fixture test on
  the real payload that caused it.
