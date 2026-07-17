import type { Metadata } from "next";
import Link from "next/link";
import { CalibrationChart } from "@/components/calibration-chart";
import { CumulativeLossChart } from "@/components/cumulative-loss-chart";
import backtestJson from "@/data/backtest.json";
import { getTrackRecord } from "@/lib/api";
import {
  type Backtest,
  calibrationBins,
  cumulativeLoss,
  overallAccuracy,
  perSeason,
  seasonStarts,
} from "@/lib/backtest";

export const dynamic = "force-dynamic";

export const metadata: Metadata = {
  title: "Track record — GenPicks",
  description:
    "GenPicks backtest and live record: log loss versus bookmaker closing odds, calibration, and season-by-season results on held-out NRL seasons.",
};

const backtest = backtestJson as Backtest;

const fmt = (v: number) => v.toFixed(4);
const pct = (v: number) => `${(v * 100).toFixed(1)}%`;
const fmtDate = (iso: string) =>
  new Date(`${iso}T00:00:00`).toLocaleDateString("en-AU", {
    day: "numeric",
    month: "short",
    year: "numeric",
  });

function StatTile({
  label,
  value,
  note,
}: {
  label: string;
  value: string;
  note?: string;
}) {
  return (
    <div className="rounded-lg border border-hairline bg-surface p-4">
      <p className="text-xs text-muted">{label}</p>
      <p className="mt-1 text-2xl font-semibold">{value}</p>
      {note && <p className="mt-1 text-xs text-muted">{note}</p>}
    </div>
  );
}

export default async function TrackRecordPage() {
  const record = await getTrackRecord();

  const points = cumulativeLoss(backtest.matches);
  const seasons = seasonStarts(backtest.matches, points);
  const bins = calibrationBins(backtest.matches);
  const seasonStats = perSeason(backtest.matches);
  const last = points[points.length - 1];
  const accuracy = overallAccuracy(backtest.matches);

  // Table twin for the cumulative chart: checkpoints, not all 557 rows.
  const checkpoints = points.filter(
    (p, i) => p.n % 100 === 0 || i === points.length - 1,
  );

  return (
    <div>
      <h1 className="mb-2 text-xl font-semibold tracking-tight">
        Track record
      </h1>
      <p className="mb-8 max-w-prose text-sm text-ink-2">
        Two kinds of evidence: a backtest on seasons the model never saw in
        training, and a live record where every prediction is written to an
        append-only log before kickoff. Nothing is retracted or rewritten.
      </p>

      <section className="mb-10">
        <h2 className="mb-1 text-base font-medium">
          Backtest — held-out seasons {backtest.splits.test[0]}–
          {backtest.splits.test[backtest.splits.test.length - 1] % 100}
        </h2>
        <p className="mb-4 max-w-prose text-sm text-ink-2">
          Trained on {backtest.splits.train[0]}–
          {backtest.splits.train[backtest.splits.train.length - 1]}, tuned on{" "}
          {backtest.splits.val.join("–")}, then evaluated once on everything
          after. Log loss scores the probabilities themselves, not just
          win/lose calls — lower is better, and 0.693 is a coin flip.
        </p>
        <div className="mb-3 grid grid-cols-1 gap-4 sm:grid-cols-3">
          <StatTile
            label="Model log loss"
            value={fmt(last.model)}
            note={`${last.n} matches`}
          />
          <StatTile
            label="Bookmaker closing odds"
            value={fmt(last.market)}
            note="same matches, de-vigged"
          />
          <StatTile
            label="Winner accuracy"
            value={pct(accuracy.model)}
            note={`bookmakers ${pct(accuracy.market)} on the same matches`}
          />
        </div>
        {/* The direction words ("level with", "ahead of") are claims about
            the committed backtest — re-check them, with the methodology
            page and the responsible-gambling page, on every retrain. */}
        <p className="mb-6 max-w-prose text-sm text-ink-2">
          Bookmakers set closing prices with team news, market moves and
          sharp money — the strongest public benchmark there is. On these{" "}
          {last.n} held-out matches the model is level with that benchmark
          on log loss and ahead of it on picking winners, from public box
          scores alone. One fixed split can flatter, so the{" "}
          <Link href="/methodology" className="underline">
            methodology page
          </Link>{" "}
          also reports the same model validated walk-forward, season by
          season.
        </p>

        <div className="mb-6 rounded-lg border border-hairline bg-surface p-4">
          <h3 className="mb-1 text-sm font-medium">
            Cumulative log loss as the test seasons unfold
          </h3>
          <p className="mb-4 text-xs text-muted">
            Running average from match 20 (earlier values swing on tiny
            samples). Hover or use arrow keys for exact values.
          </p>
          <CumulativeLossChart points={points} seasons={seasons} />
          <details className="mt-3">
            <summary className="cursor-pointer text-xs text-muted hover:text-ink-2">
              View as data table
            </summary>
            <table className="mt-2 w-full max-w-md text-xs">
              <thead>
                <tr className="border-b border-hairline text-left text-muted">
                  <th className="py-1.5 pr-4 font-normal">After matches</th>
                  <th className="py-1.5 pr-4 font-normal">Date</th>
                  <th className="py-1.5 pr-4 font-normal">Model</th>
                  <th className="py-1.5 font-normal">Bookmakers</th>
                </tr>
              </thead>
              <tbody className="tabular-nums">
                {checkpoints.map((p) => (
                  <tr key={p.n} className="border-b border-hairline">
                    <td className="py-1.5 pr-4">{p.n}</td>
                    <td className="py-1.5 pr-4">{fmtDate(p.date)}</td>
                    <td className="py-1.5 pr-4">{fmt(p.model)}</td>
                    <td className="py-1.5">{fmt(p.market)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </details>
        </div>

        <div className="mb-6 rounded-lg border border-hairline bg-surface p-4">
          <h3 className="mb-1 text-sm font-medium">Calibration</h3>
          <p className="mb-4 max-w-prose text-xs text-muted">
            When the model says 60%, does the home side win about 60% of the
            time? Each dot is a probability bin of the {last.n} test matches;
            dots on the diagonal mean yes.
          </p>
          <CalibrationChart bins={bins} />
          <details className="mt-3">
            <summary className="cursor-pointer text-xs text-muted hover:text-ink-2">
              View as data table
            </summary>
            <table className="mt-2 w-full max-w-md text-xs">
              <thead>
                <tr className="border-b border-hairline text-left text-muted">
                  <th className="py-1.5 pr-4 font-normal">Predicted bin</th>
                  <th className="py-1.5 pr-4 font-normal">Matches</th>
                  <th className="py-1.5 pr-4 font-normal">Mean predicted</th>
                  <th className="py-1.5 font-normal">Actual rate</th>
                </tr>
              </thead>
              <tbody className="tabular-nums">
                {bins.map((b) => (
                  <tr key={b.lo} className="border-b border-hairline">
                    <td className="py-1.5 pr-4">
                      {b.lo.toFixed(1)}–{b.hi.toFixed(1)}
                    </td>
                    <td className="py-1.5 pr-4">{b.n}</td>
                    <td className="py-1.5 pr-4">{pct(b.predicted)}</td>
                    <td className="py-1.5">{pct(b.actual)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </details>
        </div>

        <div className="rounded-lg border border-hairline bg-surface p-4">
          <h3 className="mb-3 text-sm font-medium">Season by season</h3>
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-hairline text-left text-muted">
                  <th className="py-1.5 pr-4 font-normal">Season</th>
                  <th className="py-1.5 pr-4 font-normal">Matches</th>
                  <th className="py-1.5 pr-4 font-normal">Model log loss</th>
                  <th className="py-1.5 pr-4 font-normal">Market log loss</th>
                  <th className="py-1.5 pr-4 font-normal">Model accuracy</th>
                  <th className="py-1.5 font-normal">Market accuracy</th>
                </tr>
              </thead>
              <tbody className="tabular-nums">
                {seasonStats.map((s) => (
                  <tr key={s.season} className="border-b border-hairline">
                    <td className="py-1.5 pr-4">{s.season}</td>
                    <td className="py-1.5 pr-4">{s.n}</td>
                    <td className="py-1.5 pr-4">{fmt(s.modelLoss)}</td>
                    <td className="py-1.5 pr-4">{fmt(s.marketLoss)}</td>
                    <td className="py-1.5 pr-4">{pct(s.modelAccuracy)}</td>
                    <td className="py-1.5">{pct(s.marketAccuracy)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="mt-3 text-xs text-muted">
            Backtest by model {backtest.model_version}, reproduced exactly
            from the committed training report.
          </p>
        </div>
      </section>

      <section>
        <h2 className="mb-1 text-base font-medium">Live record</h2>
        <p className="mb-4 max-w-prose text-sm text-ink-2">
          Predictions for upcoming fixtures are logged before kickoff and
          scored once results settle — the same numbers shown on the
          fixtures page, held to account.
        </p>
        {record === null ? (
          <p className="text-sm text-muted">
            The live record is temporarily unavailable — the prediction API
            is not responding. Try refreshing in a minute.
          </p>
        ) : Object.keys(record).length === 0 ? (
          <p className="text-sm text-muted">
            No settled predictions yet — the current round&apos;s picks are on
            the books and will appear here once results are in.
          </p>
        ) : (
          Object.entries(record).map(([version, stats]) => (
            <section key={version} className="mb-6">
              <h3 className="mb-3 text-sm font-medium text-ink-2">
                {version}
              </h3>
              <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
                <StatTile label="Settled picks" value={String(stats.settled)} />
                <StatTile
                  label="Winner accuracy"
                  value={pct(stats.accuracy)}
                />
                <StatTile
                  label="Log loss"
                  value={stats.log_loss.toFixed(4)}
                  note="lower is better · 0.693 = coin flip"
                />
              </div>
            </section>
          ))
        )}
      </section>
    </div>
  );
}
