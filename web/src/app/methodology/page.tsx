import type { Metadata } from "next";
import Link from "next/link";

export const metadata: Metadata = {
  title: "Methodology — GenPicks",
  description:
    "How the GenPicks NRL models work: data pipeline, features, the try-scorer decomposition, calibration, and how the predictions are evaluated.",
};

// Static prose — no data fetching, renders instantly even when the API
// is cold. Numbers quoted here are from the committed training report and
// must move together with the track-record page when the model retrains.
export default function MethodologyPage() {
  return (
    <div className="max-w-prose">
      <h1 className="mb-2 text-xl font-semibold tracking-tight">
        Methodology
      </h1>
      <p className="mb-8 text-sm text-ink-2">
        What the numbers on this site mean, where the data comes from, and
        what the models do — including what they don&apos;t know.
      </p>

      <section className="mb-8">
        <h2 className="mb-2 text-base font-medium">Data</h2>
        <p className="mb-3 text-sm text-ink-2">
          Eleven seasons (2016–2026) from four sources: match results and
          team sheets scraped from public rugby-league archives, per-player
          statistics and try order from NRL.com match centres, historical
          bookmaker closing odds from aussportsbetting.com, and live market
          prices from The Odds API across eleven Australian bookmakers.
        </p>
        <p className="mb-3 text-sm text-ink-2">
          Every scrape lands as a raw payload first and is transformed into
          the database by an idempotent loader, so the clean database is
          always rebuildable from raw files. Teams, venues, and players each
          carry alias tables: sponsor renames and &quot;J. Tedesco&quot; vs
          &quot;James Tedesco&quot; resolve to one canonical entity before
          any model sees the data.
        </p>
      </section>

      <section className="mb-8">
        <h2 className="mb-2 text-base font-medium">Match winner</h2>
        <p className="mb-3 text-sm text-ink-2">
          A gradient-boosted model (XGBoost, deliberately small and heavily
          regularised) over pre-match features: an Elo rating maintained
          across seasons with a home-ground offset; rolling form — win
          rates, margins, and points for/against over the last 5 and 10
          matches; rest days and season context; travel — how far each side
          travelled to the venue, and whether the nominal home team is
          actually on its own patch (it isn&apos;t in Las Vegas); and lineup
          availability — how much of the previous match&apos;s side returns,
          and how many of the team&apos;s recent regulars are in today&apos;s
          17, read from the officially published team lists. Raw scores are
          then calibrated with Platt scaling so a &quot;60%&quot; means 60%.
        </p>
        <p className="mb-3 text-sm text-ink-2">
          The one rule everything obeys: features for a match are computed
          strictly from information available before kickoff. The pipeline
          snapshots each team&apos;s state first and only then lets the
          result update it, so nothing the model trains on could leak from
          the future. Each match page shows the model&apos;s own accounting
          — a &quot;why this price&quot; panel with how much each factor
          pulled the probability toward either side.
        </p>
      </section>

      <section className="mb-8">
        <h2 className="mb-2 text-base font-medium">Try-scorer markets</h2>
        <p className="mb-3 text-sm text-ink-2">
          Player markets are derived, not directly classified. A Poisson
          count model predicts each team&apos;s expected tries in the match
          (λ) from attacking and defensive form. Each of those tries then
          goes to player <em>p</em> with probability share<sub>p</sub> —
          the player&apos;s trailing try share over their recent
          appearances, shrunk toward a position prior when history is thin
          (wingers start with winger rates, props with prop rates), and
          renormalised over the actual named lineup.
        </p>
        <p className="mb-3 text-sm text-ink-2">
          The market probabilities follow from that decomposition: anytime
          try is 1 − exp(−λ · share), and first try-scorer treats the two
          teams as competing Poisson processes. When official team lists
          are published each week, predictions built on projected lineups
          are superseded append-only — the projected generation stays in
          the log.
        </p>
      </section>

      <section className="mb-8">
        <h2 className="mb-2 text-base font-medium">Evaluation</h2>
        <p className="mb-3 text-sm text-ink-2">
          The split is by time, never shuffled: trained on 2016–2021, tuned
          on 2022–2023, and evaluated once on 2024–2026 — seasons the model
          never saw. The primary metric is log loss, which scores the
          probabilities themselves rather than win/lose calls, benchmarked
          against bookmaker closing odds with the bookmaker&apos;s margin
          removed. Closing odds are the strongest public benchmark there
          is: they embed team news, injuries, and sharp money.
        </p>
        <p className="mb-3 text-sm text-ink-2">
          On the 557 held-out matches the model scores 0.6454 — level with
          the market&apos;s 0.6454 (a coin flip scores 0.693) — and calls
          the winner more often, 65.0% to the market&apos;s 62.8%. The{" "}
          <Link href="/track-record" className="underline">
            track record page
          </Link>{" "}
          shows this match by match — cumulative log loss over time,
          calibration, and a season-by-season breakdown — alongside the
          live record, where every prediction is logged before kickoff and
          never rewritten.
        </p>
        <p className="mb-3 text-sm text-ink-2">
          One fixed split can get lucky, so the same model is also validated
          walk-forward: retrained once per season from 2022 to 2026 using
          only earlier seasons, then scored on that season out of sample —
          exactly what an annual retrain would have done. Pooled over those
          five seasons the market stays ahead (0.6352 vs 0.6150), mostly on
          2022–23 when it was unusually sharp; the model closes the gap as
          its training data grows, and is in front in 2026.
        </p>
      </section>

      <section className="mb-8">
        <h2 className="mb-2 text-base font-medium">
          What the model doesn&apos;t know
        </h2>
        <p className="mb-3 text-sm text-ink-2">
          The model now reads the official team lists, but it counts heads
          rather than names: a missing regular is a missing regular, whether
          he&apos;s the reserve hooker or the captain. It also can&apos;t see
          late changes after lists are published, weather, referee
          appointments, or where sharp money is moving — bookmakers price
          all of that. Treat large model-vs-market gaps as information
          about what the model can&apos;t see, not as free money.
        </p>
        <p className="mb-3 text-sm text-ink-2">
          GenPicks is a portfolio project for educational purposes and does
          not provide betting advice. Probabilities are model outputs, not
          offers —{" "}
          <Link href="/responsible-gambling" className="underline">
            responsible gambling
          </Link>
          .
        </p>
      </section>
    </div>
  );
}
