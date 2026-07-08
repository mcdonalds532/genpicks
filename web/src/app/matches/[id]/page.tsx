import { notFound } from "next/navigation";
import {
  formatOdds,
  formatPercent,
  getMatchMarkets,
  type PlayerMarketEntry,
} from "@/lib/api";
import { MarketOddsLine } from "@/components/market-odds";
import { ProbBar } from "@/components/prob-bar";

export const dynamic = "force-dynamic";

// Ranked single-measure table: the in-row bar is magnitude, so it uses one
// hue (not per-row colors); length is scaled to the table's top entry and
// every value is also printed as text.
function MarketTable({
  title,
  entries,
  homeTeam,
}: {
  title: string;
  entries: PlayerMarketEntry[];
  homeTeam: string | null;
}) {
  const max = entries.length ? entries[0].probability : 1;
  return (
    <section className="rounded-lg border border-hairline bg-surface p-4">
      <h2 className="mb-3 text-sm font-semibold">{title}</h2>
      {entries.length === 0 ? (
        <p className="text-sm text-muted">No prices generated.</p>
      ) : (
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-xs text-muted">
              <th className="pb-2 font-normal">Player</th>
              <th className="pb-2 font-normal" aria-hidden />
              <th className="pb-2 text-right font-normal">Prob.</th>
              <th className="pb-2 text-right font-normal">Odds</th>
            </tr>
          </thead>
          <tbody>
            {entries.map((e) => (
              <tr key={`${e.player}-${e.team}`} className="border-t border-hairline">
                <td className="py-1.5 pr-2">
                  <span
                    aria-hidden
                    className={`mr-1.5 inline-block h-2 w-2 rounded-full ${
                      e.team === homeTeam ? "bg-series-home" : "bg-series-away"
                    }`}
                  />
                  {e.player}
                  <span className="ml-1 text-xs text-muted">{e.team}</span>
                </td>
                <td className="w-1/4 py-1.5 pr-3">
                  <div className="h-1.5 w-full">
                    <div
                      className="h-full rounded-[3px] bg-bar-hue"
                      style={{ width: `${(e.probability / max) * 100}%` }}
                    />
                  </div>
                </td>
                <td className="py-1.5 text-right tabular-nums text-ink-2">
                  {formatPercent(e.probability)}
                </td>
                <td className="py-1.5 text-right tabular-nums">
                  ${formatOdds(e.implied_odds)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}

export default async function MatchPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const markets = await getMatchMarkets(id);
  if (markets === null) notFound();

  return (
    <div>
      <div className="mb-6">
        <p className="mb-1 text-xs text-muted">{markets.date}</p>
        <h1 className="mb-4 text-xl font-semibold tracking-tight">
          {markets.home_team} v {markets.away_team}
        </h1>
        <div className="rounded-lg border border-hairline bg-surface p-4">
          <ProbBar
            homeTeam={markets.home_team}
            awayTeam={markets.away_team}
            home={markets.h2h.home}
            away={markets.h2h.away}
          />
          <MarketOddsLine odds={markets.market_odds} />
        </div>
      </div>
      <div className="grid gap-4 md:grid-cols-2">
        <MarketTable
          title="Anytime try scorer"
          entries={markets.anytime_try}
          homeTeam={markets.home_team}
        />
        <MarketTable
          title="First try scorer"
          entries={markets.first_try}
          homeTeam={markets.home_team}
        />
      </div>
      {markets.lineup_source !== null && (
        <p className="mt-4 text-xs text-muted">
          {markets.lineup_source === "official"
            ? "Player markets use the officially named team lists."
            : "Player markets use lineups projected from each team's most recent match; they update when official team lists are published."}
        </p>
      )}
    </div>
  );
}
